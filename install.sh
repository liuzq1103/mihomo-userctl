#!/usr/bin/env bash
set -euo pipefail

VERSION=0.1.3
BEGIN_MARKER='# >>> mihomo-userctl managed loader >>>'
END_MARKER='# <<< mihomo-userctl managed loader <<<'

die() { printf 'install.sh: %s\n' "$*" >&2; exit 2; }
note() { printf '%s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [--port PORT] [--bashrc PATH] [--dry-run]
       ./install.sh --suggest-port

The first installation requires --port. Existing installations may omit it;
an explicitly requested port must match the existing configuration.

--suggest-port prints one currently unused candidate from 20000-29999 and
changes nothing. It is not a reservation; confirm it before installation.
EOF
}

port=
bashrc=${HOME}/.bashrc
dry_run=0
suggest_only=0
bashrc_set=0
while (( $# )); do
  case $1 in
    --port) [[ $# -ge 2 ]] || die '--port requires a value'; port=$2; shift 2 ;;
    --bashrc) [[ $# -ge 2 ]] || die '--bashrc requires a path'; bashrc=$2; bashrc_set=1; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --suggest-port) suggest_only=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done

[[ $(uname -s) == Linux ]] || die 'Linux is required'
[[ -n ${BASH_VERSION:-} ]] || die 'run this installer with Bash'
if ((suggest_only)); then
  [[ -z $port && $dry_run -eq 0 && $bashrc_set -eq 0 ]] ||
    die '--suggest-port cannot be combined with installation options'
  for command in ss id; do
    command -v "$command" >/dev/null 2>&1 || die "missing command: $command"
  done
  uid=$(id -u) || die 'cannot determine the current UID'
  start=$((20000 + uid % 10000))
  for ((offset=0; offset<10000; offset++)); do
    candidate=$((20000 + (start - 20000 + offset) % 10000))
    if ! listeners=$(ss -H -ltn "sport = :$candidate" 2>/dev/null); then
      die 'ss failed while checking candidate ports'
    fi
    if [[ -z $listeners ]]; then
      printf '%s\n' "$candidate"
      exit 0
    fi
  done
  die 'no unused candidate was found in 20000-29999'
fi
for command in bash systemctl curl ss journalctl stat awk grep id mktemp cp chmod mv mkdir date rm rmdir dirname; do
  command -v "$command" >/dev/null 2>&1 || die "missing command: $command"
done
systemctl --user show-environment >/dev/null 2>&1 || die 'the systemd user manager is unavailable'

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
config_home=${XDG_CONFIG_HOME:-$HOME/.config}
data_home=${XDG_DATA_HOME:-$HOME/.local/share}
bin_home=${HOME}/.local/bin
lib_dir=$data_home/mihomo-userctl
config_dir=$config_home/mihomo
config_file=$config_dir/mihomo-shell.conf
bin_file=$bin_home/mihomoctl

[[ $bashrc == "$HOME"/* || $bashrc == "$HOME/.bashrc" ]] || die '--bashrc must be inside the current HOME'
[[ ! -L $bashrc ]] || die '--bashrc must not be a symbolic link'

managed_targets=(
  "$lib_dir/common.bash"
  "$lib_dir/shell.bash"
  "$lib_dir/completion.bash"
  "$bin_file"
  "$config_file"
  "$bashrc"
)
for target in "${managed_targets[@]}"; do
  [[ ! -L $target ]] || die "managed target must not be a symbolic link: $target"
  [[ ! -e $target || -f $target ]] || die "managed target is not a regular file: $target"
done

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
if [[ -f $bashrc ]]; then
  managed_count=$(grep -Fxc "$BEGIN_MARKER" "$bashrc" || true)
fi
(( managed_count <= 1 )) || die 'multiple managed loader blocks found in .bashrc'

if (( dry_run )); then
  note "would install mihomo-userctl $VERSION to $bin_file and $lib_dir"
  [[ -f $config_file ]] || note "would create $config_file with port $port"
  if (( managed_count == 1 )); then
    note "would refresh the managed loader in $bashrc"
  else
    note "would append the managed loader to $bashrc"
  fi
  note 'would preserve client.env, Mihomo, systemd service, subscriptions, and caches'
  exit 0
fi

timestamp=$(date +%Y%m%d-%H%M%S)
backup_parent=$data_home/mihomo-userctl-backups
mkdir -p -- "$backup_parent"
chmod 700 -- "$backup_parent"
backup_root=$(mktemp -d "$backup_parent/install-$timestamp.XXXXXX")
chmod 700 -- "$backup_root"
backup_manifest=$backup_root/manifest.tsv
: > "$backup_manifest"
chmod 600 -- "$backup_manifest"

backup_names=(common.bash shell.bash completion.bash mihomoctl mihomo-shell.conf bashrc)
backup_states=()
for index in "${!managed_targets[@]}"; do
  target=${managed_targets[$index]}
  backup_file=$backup_root/${backup_names[$index]}
  if [[ -e $target ]]; then
    cp -p -- "$target" "$backup_file"
    backup_states+=(present)
    printf 'file\tpresent\t%s\t%s\n' "${backup_names[$index]}" "$target" >> "$backup_manifest"
  else
    backup_states+=(absent)
    printf 'file\tabsent\t%s\t%s\n' "${backup_names[$index]}" "$target" >> "$backup_manifest"
  fi
done

managed_dirs=("$bin_home" "$lib_dir" "$config_dir")
dir_states=()
dir_modes=()
for target_dir in "${managed_dirs[@]}"; do
  if [[ -d $target_dir ]]; then
    dir_states+=(present)
    dir_modes+=("$(stat -c '%a' -- "$target_dir")")
    printf 'directory\tpresent:%s\t-\t%s\n' "${dir_modes[-1]}" "$target_dir" >> "$backup_manifest"
  else
    dir_states+=(absent)
    dir_modes+=(none)
    printf 'directory\tabsent\t-\t%s\n' "$target_dir" >> "$backup_manifest"
  fi
done

transaction_active=1
transaction_temps=()
rollback_install() {
  local rc=$? index target backup_file target_dir tmp rollback_failed=0
  trap - EXIT
  if (( transaction_active )); then
    set +e
    for tmp in "${transaction_temps[@]}"; do
      rm -f -- "$tmp"
    done
    for index in "${!managed_targets[@]}"; do
      target=${managed_targets[$index]}
      backup_file=$backup_root/${backup_names[$index]}
      if [[ ${backup_states[$index]} == present ]]; then
        mkdir -p -- "$(dirname -- "$target")" || { rollback_failed=1; continue; }
        tmp=$(mktemp "${target}.rollback.XXXXXX") || { rollback_failed=1; continue; }
        cp -p -- "$backup_file" "$tmp" || { rm -f -- "$tmp"; rollback_failed=1; continue; }
        mv -f -- "$tmp" "$target" || { rm -f -- "$tmp"; rollback_failed=1; }
      else
        rm -f -- "$target" || rollback_failed=1
      fi
    done
    for index in "${!managed_dirs[@]}"; do
      target_dir=${managed_dirs[$index]}
      if [[ ${dir_states[$index]} == present ]]; then
        chmod "${dir_modes[$index]}" -- "$target_dir" || rollback_failed=1
      else
        rmdir -- "$target_dir" 2>/dev/null || true
      fi
    done
    printf 'install.sh: installation failed; active files were restored from %s\n' "$backup_root" >&2
    (( rollback_failed == 0 )) || printf 'install.sh: warning: automatic rollback was incomplete; inspect the backup above\n' >&2
  fi
  exit "$rc"
}
trap rollback_install EXIT

mkdir -p -- "$bin_home" "$lib_dir" "$config_dir"
chmod 700 -- "$lib_dir" "$config_dir"

atomic_install() {
  local source=$1 target=$2 mode=$3 tmp
  tmp=$(mktemp "${target}.tmp.XXXXXX")
  transaction_temps+=("$tmp")
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
  transaction_temps+=("$config_tmp")
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
bashrc_tmp=$(mktemp "${bashrc}.tmp.XXXXXX")
transaction_temps+=("$bashrc_tmp")

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
  ' "$bashrc" > "$bashrc_tmp" || die 'failed to refresh .bashrc loader'
else
  cp -- "$bashrc" "$bashrc_tmp"
  printf '\n' >> "$bashrc_tmp"
  awk '{ print }' "$loader_file" >> "$bashrc_tmp"
fi

bash -n "$bashrc_tmp" || die 'generated .bashrc failed bash -n'
chmod --reference="$bashrc" "$bashrc_tmp"
mv -f -- "$bashrc_tmp" "$bashrc"

MIHOMO_USERCTL_LIB_DIR=$lib_dir "$bin_file" doctor || {
  die 'doctor failed'
}
transaction_active=0
trap - EXIT
note "installed mihomo-userctl $VERSION"
note "backup=$backup_root"
note 'the Mihomo service was not enabled or started'
