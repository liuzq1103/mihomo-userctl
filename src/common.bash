#!/usr/bin/env bash

# Shared implementation for mihomoctl and shell.bash.
# This file may be sourced, but user configuration files are always parsed as
# data and are never sourced or evaluated.

# Used by src/mihomoctl after this shared module is sourced.
# shellcheck disable=SC2034
MIHOMO_USERCTL_VERSION="0.1.1"

_muc_err() {
  printf 'mihomo-userctl: %s\n' "$*" >&2
}

_muc_config_home() {
  printf '%s' "${XDG_CONFIG_HOME:-$HOME/.config}"
}

_muc_data_home() {
  printf '%s' "${XDG_DATA_HOME:-$HOME/.local/share}"
}

_muc_config_file() {
  printf '%s' "${MIHOMO_USERCTL_CONFIG:-$(_muc_config_home)/mihomo/mihomo-shell.conf}"
}

_muc_credentials_file() {
  printf '%s' "${MIHOMO_USERCTL_CREDENTIALS:-$(_muc_config_home)/mihomo/client.env}"
}

_muc_clear_proxy_environment() {
  unset http_proxy https_proxy all_proxy no_proxy
  unset HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
  unset MIHOMO_HTTP_PROXY MIHOMO_HTTPS_PROXY MIHOMO_ALL_PROXY
}

_muc_mode() {
  stat -c '%a' -- "$1" 2>/dev/null
}

_muc_owner_uid() {
  stat -c '%u' -- "$1" 2>/dev/null
}

_muc_require_owned_file() {
  local path=$1 expected_mode=$2 mode owner
  [[ -f $path && -r $path ]] || {
    _muc_err "required file is missing or unreadable: $path"
    return 2
  }
  owner=$(_muc_owner_uid "$path") || return 2
  [[ $owner == "$(id -u)" ]] || {
    _muc_err "file is not owned by the current user: $path"
    return 2
  }
  mode=$(_muc_mode "$path") || return 2
  [[ $mode == "$expected_mode" ]] || {
    _muc_err "file must have mode $expected_mode: $path"
    return 2
  }
}

_muc_require_safe_module() {
  local path=$1 owner mode parent parent_mode
  [[ -f $path && -r $path ]] || {
    _muc_err "module is missing or unreadable: $path"
    return 2
  }
  owner=$(_muc_owner_uid "$path") || return 2
  [[ $owner == "$(id -u)" ]] || {
    _muc_err "module is not owned by the current user: $path"
    return 2
  }
  mode=$(_muc_mode "$path") || return 2
  (( (8#$mode & 022) == 0 )) || {
    _muc_err "module must not be writable by group or others: $path"
    return 2
  }
  parent=${path%/*}
  [[ $parent != "$path" ]] || parent=.
  owner=$(_muc_owner_uid "$parent") || return 2
  parent_mode=$(_muc_mode "$parent") || return 2
  [[ $owner == "$(id -u)" ]] || {
    _muc_err "module directory is not owned by the current user: $parent"
    return 2
  }
  (( (8#$parent_mode & 022) == 0 )) || {
    _muc_err "module directory must not be writable by group or others: $parent"
    return 2
  }
}

_muc_decode_value() {
  local raw=$1 first last
  [[ $raw != *$'\n'* && $raw != *$'\r'* ]] || return 2
  if [[ $raw == "''" || $raw == '""' ]]; then
    printf ''
    return 0
  fi
  first=${raw:0:1}
  last=${raw: -1}
  if [[ $first == "'" || $first == '"' ]]; then
    [[ $last == "$first" && ${#raw} -ge 2 ]] || return 2
    raw=${raw:1:${#raw}-2}
    [[ $raw != *"$first"* ]] || return 2
  elif [[ $raw =~ [[:space:]] ]]; then
    return 2
  fi
  printf '%s' "$raw"
}

_muc_parse_file() {
  local path=$1 kind=$2 line key raw value
  local -A seen=()
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%$'\r'}
    [[ -z $line || $line == \#* ]] && continue
    [[ $line =~ ^([A-Z][A-Z0-9_]*)=(.*)$ ]] || {
      _muc_err "invalid $kind syntax in $path"
      return 2
    }
    key=${BASH_REMATCH[1]}
    raw=${BASH_REMATCH[2]}
    case "$kind:$key" in
      config:MIHOMO_SERVICE|config:MIHOMO_PORT|config:MIHOMO_READY_URL|config:MIHOMO_READY_TIMEOUT|config:MIHOMO_STOP_TIMEOUT|credentials:MIHOMO_HTTP_PROXY|credentials:MIHOMO_HTTPS_PROXY|credentials:MIHOMO_ALL_PROXY) ;;
      *)
        _muc_err "unknown $kind key: $key"
        return 2
        ;;
    esac
    [[ -z ${seen[$key]+x} ]] || {
      _muc_err "duplicate $kind key: $key"
      return 2
    }
    seen[$key]=1
    value=$(_muc_decode_value "$raw") || {
      _muc_err "invalid value for $key"
      return 2
    }
    printf -v "$key" '%s' "$value"
  done < "$path"
}

_muc_load_config() {
  local path
  path=$(_muc_config_file)
  _muc_require_owned_file "$path" 600 || return 2
  MIHOMO_SERVICE=mihomo
  MIHOMO_PORT=
  MIHOMO_READY_URL=https://example.com/
  MIHOMO_READY_TIMEOUT=30
  MIHOMO_STOP_TIMEOUT=5
  _muc_parse_file "$path" config || return 2
  [[ $MIHOMO_SERVICE =~ ^[A-Za-z0-9_.@-]+$ ]] || {
    _muc_err "invalid MIHOMO_SERVICE"
    return 2
  }
  if [[ ! $MIHOMO_PORT =~ ^[0-9]+$ ]] ||
     (( MIHOMO_PORT < 1024 || MIHOMO_PORT > 65535 )); then
    _muc_err "MIHOMO_PORT must be between 1024 and 65535"
    return 2
  fi
  [[ $MIHOMO_READY_URL =~ ^https://[^[:space:]]+$ ]] || {
    _muc_err "MIHOMO_READY_URL must be an HTTPS URL"
    return 2
  }
  if [[ ! $MIHOMO_READY_TIMEOUT =~ ^[0-9]+$ ]] ||
     (( MIHOMO_READY_TIMEOUT < 1 || MIHOMO_READY_TIMEOUT > 300 )); then
    _muc_err "MIHOMO_READY_TIMEOUT must be between 1 and 300"
    return 2
  fi
  if [[ ! $MIHOMO_STOP_TIMEOUT =~ ^[0-9]+$ ]] ||
     (( MIHOMO_STOP_TIMEOUT < 1 || MIHOMO_STOP_TIMEOUT > 60 )); then
    _muc_err "MIHOMO_STOP_TIMEOUT must be between 1 and 60"
    return 2
  fi
}

_muc_load_credentials() {
  local path
  path=$(_muc_credentials_file)
  _muc_require_owned_file "$path" 600 || return 2
  MIHOMO_HTTP_PROXY=
  MIHOMO_HTTPS_PROXY=
  MIHOMO_ALL_PROXY=
  _muc_parse_file "$path" credentials || return 2
  [[ $MIHOMO_HTTP_PROXY =~ ^http://[^/@[:space:]]+@127\.0\.0\.1:${MIHOMO_PORT}/?$ ]] || {
    _muc_err "invalid HTTP proxy endpoint in client.env"
    _muc_clear_proxy_environment
    return 2
  }
  [[ $MIHOMO_HTTPS_PROXY =~ ^http://[^/@[:space:]]+@127\.0\.0\.1:${MIHOMO_PORT}/?$ ]] || {
    _muc_err "invalid HTTPS proxy endpoint in client.env"
    _muc_clear_proxy_environment
    return 2
  }
  [[ $MIHOMO_ALL_PROXY =~ ^socks5h://[^/@[:space:]]+@127\.0\.0\.1:${MIHOMO_PORT}/?$ ]] || {
    _muc_err "invalid SOCKS proxy endpoint in client.env"
    _muc_clear_proxy_environment
    return 2
  }
}

_muc_service_active() {
  systemctl --user is-active --quiet "$MIHOMO_SERVICE" 2>/dev/null
}

_muc_service_enabled_state() {
  systemctl --user is-enabled "$MIHOMO_SERVICE" 2>/dev/null || true
}

_muc_listening() {
  command -v ss >/dev/null 2>&1 || return 1
  ss -H -ltn "sport = :$MIHOMO_PORT" 2>/dev/null |
    awk -v endpoint="127.0.0.1:$MIHOMO_PORT" '$4 == endpoint { found=1 } END { exit !found }'
}

_muc_probe() (
  _muc_service_active || return 1
  _muc_listening || return 1
  _muc_load_credentials || return 2
  env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    http_proxy="$MIHOMO_HTTP_PROXY" \
    https_proxy="$MIHOMO_HTTPS_PROXY" \
    all_proxy= no_proxy= \
    curl --fail --silent --show-error --max-time 5 \
      --output /dev/null "$MIHOMO_READY_URL"
)

_muc_wait_ready() {
  local deadline=$((SECONDS + MIHOMO_READY_TIMEOUT)) rc
  while (( SECONDS <= deadline )); do
    _muc_probe && return 0
    rc=$?
    (( rc == 2 )) && return 2
    sleep 1
  done
  return 1
}

_muc_wait_stopped() {
  local ticks=$((MIHOMO_STOP_TIMEOUT * 4))
  while (( ticks-- > 0 )); do
    _muc_listening || return 0
    sleep 0.25
  done
  _muc_listening && return 1
  return 0
}
