#!/usr/bin/env bash

_muc_shell_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P) || return 2
_muc_shell_common="$_muc_shell_dir/common.bash"
_muc_common_mode=$(stat -c '%a' -- "$_muc_shell_common" 2>/dev/null || true)
_muc_dir_mode=$(stat -c '%a' -- "$_muc_shell_dir" 2>/dev/null || true)
if [[ ! -r $_muc_shell_common || ! -O $_muc_shell_common || ! -O $_muc_shell_dir ]]; then
  printf 'mihomo-userctl: unsafe or missing common module: %s\n' "$_muc_shell_common" >&2
  return 2
fi
if [[ ! $_muc_common_mode =~ ^[0-7]{3,4}$ || ! $_muc_dir_mode =~ ^[0-7]{3,4}$ ]]; then
  printf 'mihomo-userctl: could not validate common module permissions\n' >&2
  return 2
fi
if (( (8#$_muc_common_mode & 022) != 0 || (8#$_muc_dir_mode & 022) != 0 )); then
  printf 'mihomo-userctl: common modules must not be writable by group or others\n' >&2
  return 2
fi
# shellcheck source=common.bash
source "$_muc_shell_common"
unset _muc_common_mode _muc_dir_mode

_muc_completion="$_muc_shell_dir/completion.bash"
if [[ $- == *i* ]] && _muc_require_safe_module "$_muc_completion"; then
  # shellcheck source=/dev/null
  source "$_muc_completion"
fi
unset _muc_completion

proxy_off() {
  _muc_clear_proxy_environment
}

proxy_on() {
  local proxy_http proxy_https proxy_socks
  proxy_off
  _muc_load_config || return 2
  _muc_service_active || {
    _muc_err "Mihomo user service is not running; run: mihomoctl start"
    return 1
  }
  _muc_listening || {
    _muc_err "Mihomo is not listening on 127.0.0.1:$MIHOMO_PORT"
    return 1
  }
  _muc_load_credentials || return 2
  proxy_http=$MIHOMO_HTTP_PROXY
  proxy_https=$MIHOMO_HTTPS_PROXY
  proxy_socks=$MIHOMO_ALL_PROXY
  unset MIHOMO_HTTP_PROXY MIHOMO_HTTPS_PROXY MIHOMO_ALL_PROXY
  if ! env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY -u NO_PROXY \
    http_proxy="$proxy_http" https_proxy="$proxy_https" all_proxy= no_proxy= \
    curl --fail --silent --show-error --max-time 5 --output /dev/null "$MIHOMO_READY_URL"; then
    _muc_err "authenticated Mihomo readiness check failed"
    return 1
  fi
  export http_proxy=$proxy_http https_proxy=$proxy_https
  export HTTP_PROXY=$proxy_http HTTPS_PROXY=$proxy_https
  export all_proxy=$proxy_socks ALL_PROXY=$proxy_socks
  export no_proxy='localhost,127.0.0.1,::1'
  export NO_PROXY=$no_proxy
}

_muc_environment_matches() {
  local actual_http=${http_proxy-} actual_https=${https_proxy-}
  local actual_HTTP=${HTTP_PROXY-} actual_HTTPS=${HTTPS_PROXY-}
  local actual_all=${all_proxy-} actual_ALL=${ALL_PROXY-}
  local actual_no=${no_proxy-} actual_NO=${NO_PROXY-}
  local expected_http expected_https expected_socks
  _muc_load_credentials || return 2
  expected_http=$MIHOMO_HTTP_PROXY
  expected_https=$MIHOMO_HTTPS_PROXY
  expected_socks=$MIHOMO_ALL_PROXY
  unset MIHOMO_HTTP_PROXY MIHOMO_HTTPS_PROXY MIHOMO_ALL_PROXY
  [[ $actual_http == "$expected_http" &&
     $actual_https == "$expected_https" &&
     $actual_HTTP == "$expected_http" &&
     $actual_HTTPS == "$expected_https" &&
     $actual_all == "$expected_socks" &&
     $actual_ALL == "$expected_socks" &&
     $actual_no == 'localhost,127.0.0.1,::1' &&
     $actual_NO == 'localhost,127.0.0.1,::1' ]]
}

proxy_status() {
  local service=down state=direct count=0 name
  _muc_load_config || return 2
  _muc_service_active && service=up
  for name in http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY; do
    [[ -n ${!name:-} ]] && count=$((count + 1))
  done
  if (( count == 0 )); then
    state=direct
  elif (( count == 8 )) && [[ $service == up ]] && _muc_listening && _muc_environment_matches; then
    state=proxied
  else
    state=inconsistent
  fi
  printf 'shell=%s service=%s endpoint=127.0.0.1:%s\n' "$state" "$service" "$MIHOMO_PORT"
  [[ $state != inconsistent ]]
}

with_proxy() (
  if (( $# == 0 )); then
    printf 'Usage: with_proxy command [args ...]\n' >&2
    return 2
  fi
  proxy_on || return $?
  "$@"
)

_muc_controller() {
  local controller=${MIHOMO_USERCTL_BIN:-${HOME}/.local/bin/mihomoctl}
  [[ -x $controller ]] || {
    _muc_err "controller is missing or not executable: $controller"
    return 2
  }
  "$controller" "$@"
}

mihomo_start() { _muc_controller start; }
mihomo_stop() { proxy_off; _muc_controller stop; }
mihomo_restart() { proxy_off; _muc_controller restart; }
mihomo_status() { _muc_controller status; proxy_status; }
mihomo_logs() { _muc_controller logs "$@"; }

# A sourced ordinary shell always starts direct, even if its parent exported
# proxy variables. Codex's remote launcher is the only opt-in automatic hook.
proxy_off
if [[ -n ${CODEX_REMOTE_PAYLOAD:-} ]]; then
  proxy_on || exit 1
fi

unset _muc_shell_common _muc_shell_dir
