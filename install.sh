#!/usr/bin/env bash
set -euo pipefail

VERSION=0.1.0
BEGIN_MARKER='# >>> mihomo-userctl managed loader >>>'
END_MARKER='# <<< mihomo-userctl managed loader <<<'

die() { printf 'install.sh: %s\n' "$*" >&2; exit 2; }
note() { printf '%s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [--port PORT] [--bashrc PATH] [--dry-run]

The first installation requires --port. Existing installations may omit it;
an explicitly requested port must match the existing configuration.
EOF
}

port=
bashrc=${HOME}/.bashrc
dry_run=0
while (( $# )); do
  case $1 in
    --port) [[ $# -ge 2 ]] || die '--port requires a value'; port=$2; shift 2 ;;
    --bashrc) [[ $# -ge 2 ]] || die '--bashrc requires a path'; bashrc=$2; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ $(uname -s) == Linux ]] || die 'Linux is required'
[[ -n ${BASH_VERSION:-} ]] || die 'run this installer with Bash'
for command in bash systemctl curl ss journalctl stat awk grep id mktemp cp chmod mv mkdir date; do
  command -v "$command" >/dev/null 2>&1 || die "missing command: $command"
done
systemctl --user show-environment >/dev/null 2>&1 || die 'the systemd user manager is unavailable'
current_user=$(id -un) || die 'cannot determine the current user'
LEGACY_MARKER="# Server shells are direct by default. The ${current_user} user-level Mihomo service is opt-in."

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
config_home=${XDG_CONFIG_HOME:-$HOME/.config}
data_home=${XDG_DATA_HOME:-$HOME/.local/share}
bin_home=${HOME}/.local/bin
lib_dir=$data_home/mihomo-userctl
config_dir=$config_home/mihomo
config_file=$config_dir/mihomo-shell.conf
bin_file=$bin_home/mihomoctl

[[ $bashrc == "$HOME"/* || $bashrc == "$HOME/.bashrc" ]] || die '--bashrc must be inside the current HOME'

existing_port=
if [[ -f $config_file ]]; then
  existing_port=$(awk -F= '$1 == "MIHOMO_PORT" { print $2 }' "$config_file")
  [[ $(grep -c '^MIHOMO_PORT=' "$config_file") -eq 1 ]] || die 'existing config has no unique MIHOMO_PORT'
fi
if [[ -z $port ]]; then
  [[ -n $existing_port ]] || die 'the first installation requires --port'
  port=$existing_port
fi
if [[ ! $port =~ ^[0-9]+$ ]] || (( port < 1024 || port > 65535 )); then
  die 'port must be between 1024 and 65535'
fi
[[ -z $existing_port || $existing_port == "$port" ]] || die "requested port conflicts with existing config ($existing_port)"

managed_count=0
legacy_count=0
if [[ -f $bashrc ]]; then
  managed_count=$(grep -Fxc "$BEGIN_MARKER" "$bashrc" || true)
  legacy_count=$(grep -Fxc "$LEGACY_MARKER" "$bashrc" || true)
fi
(( managed_count <= 1 )) || die 'multiple managed loader blocks found in .bashrc'
(( legacy_count <= 1 )) || die 'multiple legacy proxy blocks found in .bashrc'
if (( managed_count == 0 && legacy_count == 1 )); then
  grep -Fq 'if [ -n "${CODEX_REMOTE_PAYLOAD:-}" ]; then' "$bashrc" ||
    die 'legacy block end marker was not found; refusing an ambiguous rewrite'
fi

if (( dry_run )); then
  note "would install mihomo-userctl $VERSION to $bin_file and $lib_dir"
  [[ -f $config_file ]] || note "would create $config_file with port $port"
  if (( managed_count == 1 )); then
    note "would refresh the managed loader in $bashrc"
  elif (( legacy_count == 1 )); then
    note "would replace the recognized legacy proxy block in $bashrc"
  else
    note "would append the managed loader to $bashrc"
  fi
  note 'would preserve client.env, Mihomo, systemd service, subscriptions, and caches'
  exit 0
fi

timestamp=$(date +%Y%m%d-%H%M%S)
mkdir -p -- "$bin_home" "$lib_dir" "$config_dir"
chmod 700 -- "$lib_dir" "$config_dir"

atomic_install() {
  local source=$1 target=$2 mode=$3 tmp
  tmp=$(mktemp "${target}.tmp.XXXXXX")
  cp -- "$source" "$tmp"
  chmod "$mode" -- "$tmp"
  mv -f -- "$tmp" "$target"
}

atomic_install "$script_dir/src/common.bash" "$lib_dir/common.bash" 644
atomic_install "$script_dir/src/shell.bash" "$lib_dir/shell.bash" 644
atomic_install "$script_dir/completions/mihomoctl.bash" "$lib_dir/completion.bash" 644
atomic_install "$script_dir/src/mihomoctl" "$bin_file" 755

if [[ ! -f $config_file ]]; then
  config_tmp=$(mktemp "${config_file}.tmp.XXXXXX")
  {
    printf 'MIHOMO_SERVICE=mihomo\n'
    printf 'MIHOMO_PORT=%s\n' "$port"
    printf 'MIHOMO_READY_URL=https://example.com/\n'
    printf 'MIHOMO_READY_TIMEOUT=30\n'
    printf 'MIHOMO_STOP_TIMEOUT=5\n'
  } > "$config_tmp"
  chmod 600 "$config_tmp"
  mv -f -- "$config_tmp" "$config_file"
else
  chmod 600 -- "$config_file"
fi

loader_file=$script_dir/examples/bashrc-loader.bash
[[ -f $bashrc ]] || : > "$bashrc"
backup=${bashrc}.mihomo-userctl-backup.${timestamp}
cp -p -- "$bashrc" "$backup"
chmod 600 -- "$backup"
bashrc_tmp=$(mktemp "${bashrc}.tmp.XXXXXX")

if (( managed_count == 1 )); then
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" -v loader="$loader_file" '
    $0 == begin {
      while ((getline line < loader) > 0) print line
      close(loader)
      skipping=1
      next
    }
    skipping && $0 == end { skipping=0; next }
    !skipping { print }
    END { if (skipping) exit 3 }
  ' "$bashrc" > "$bashrc_tmp" || { cp -p -- "$backup" "$bashrc"; die 'failed to refresh .bashrc loader'; }
elif (( legacy_count == 1 )); then
  awk -v legacy="$LEGACY_MARKER" -v loader="$loader_file" '
    $0 == legacy { skipping=1; codex=0; next }
    skipping && index($0, "CODEX_REMOTE_PAYLOAD") { codex=1; next }
    skipping && codex && $0 == "fi" {
      while ((getline line < loader) > 0) print line
      close(loader)
      skipping=0
      next
    }
    !skipping { print }
    END { if (skipping) exit 3 }
  ' "$bashrc" > "$bashrc_tmp" || { cp -p -- "$backup" "$bashrc"; die 'failed to migrate legacy .bashrc block'; }
else
  cp -- "$bashrc" "$bashrc_tmp"
  printf '\n' >> "$bashrc_tmp"
  awk '{ print }' "$loader_file" >> "$bashrc_tmp"
fi

bash -n "$bashrc_tmp" || { cp -p -- "$backup" "$bashrc"; die 'generated .bashrc failed bash -n'; }
chmod --reference="$bashrc" "$bashrc_tmp"
mv -f -- "$bashrc_tmp" "$bashrc"

MIHOMO_USERCTL_LIB_DIR=$lib_dir "$bin_file" doctor || {
  cp -p -- "$backup" "$bashrc"
  die "doctor failed; .bashrc was restored from $backup"
}
note "installed mihomo-userctl $VERSION"
note "backup=$backup"
note 'the Mihomo service was not enabled or started'
