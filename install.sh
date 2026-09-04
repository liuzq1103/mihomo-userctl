#!/usr/bin/env bash
set -euo pipefail

VERSION=0.2.1
BEGIN_MARKER='# >>> mihomo-userctl managed loader >>>'
END_MARKER='# <<< mihomo-userctl managed loader <<<'

die() { printf 'install.sh: %s\n' "$*" >&2; exit 2; }
note() { printf '%s\n' "$*"; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [--port PORT] [--bashrc PATH] [--dry-run]
       ./install.sh --rollback BACKUP
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
source_record=
rollback_path=
preserve_service_state=0
original_args=("$@")
while (( $# )); do
  case $1 in
    --port) [[ $# -ge 2 ]] || die '--port requires a value'; port=$2; shift 2 ;;
    --bashrc) [[ $# -ge 2 ]] || die '--bashrc requires a path'; bashrc=$2; bashrc_set=1; shift 2 ;;
    --dry-run) dry_run=1; shift ;;
    --source-record) [[ $# -ge 2 ]] || die "missing source record"; source_record=$2; shift 2 ;;
    --preserve-service-state) preserve_service_state=1; shift ;;
    --rollback) [[ $# -ge 2 ]] || die "missing backup path"; rollback_path=$2; shift 2 ;;
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
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
support=$script_dir/scripts/install_support.py
if [[ -n $rollback_path ]]; then
  exec python3 "$support" rollback "$rollback_path"
fi
for command in python3 bash systemctl curl ss journalctl stat awk grep id mktemp cp chmod mv mkdir date rm rmdir dirname; do
  command -v "$command" >/dev/null 2>&1 || die "missing command: $command"
done
python3 -c 'import sys; sys.exit(sys.version_info < (3, 8))' || die 'Python 3.8+ is required'
systemctl --user show-environment >/dev/null 2>&1 || die 'the systemd user manager is unavailable'

config_home=${XDG_CONFIG_HOME:-$HOME/.config}
data_home=${XDG_DATA_HOME:-$HOME/.local/share}
bin_home=${HOME}/.local/bin
lib_dir=$data_home/mihomo-userctl
config_dir=$config_home/mihomo
config_file=$config_dir/mihomo-shell.conf
bin_file=$bin_home/mihomoctl

bashrc=$(python3 "$support" bashrc "$lib_dir" "$bashrc" "$bashrc_set") || die 'cannot determine original startup path; use explicit --bashrc for migration'
python3 "$support" preflight "$bashrc" || die 'unsafe installation paths; no active files changed'
if (( ! dry_run )) && [[ -z ${MIHOMO_INSTALL_LOCK_FD:-} ]]; then
  exec python3 "$support" locked bash "$script_dir/install.sh" "${original_args[@]}"
fi
[[ ! -e $lib_dir/pending-install.json ]] || die 'interrupted transaction: restore the backup recorded in pending-install.json first'

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
note "backup=$backup_root"

backup_names=(common.bash shell.bash completion.bash mihomoctl mihomo-shell.conf bashrc)
for index in "${!managed_targets[@]}"; do
  target=${managed_targets[$index]}
  backup_file=$backup_root/${backup_names[$index]}
  if [[ -e $target ]]; then
    cp -p -- "$target" "$backup_file"
    printf 'file\tpresent\t%s\t%s\n' "${backup_names[$index]}" "$target" >> "$backup_manifest"
  else
    printf 'file\tabsent\t%s\t%s\n' "${backup_names[$index]}" "$target" >> "$backup_manifest"
  fi
done

managed_dirs=("$bin_home" "$lib_dir" "$config_dir")
dir_modes=()
for target_dir in "${managed_dirs[@]}"; do
  if [[ -d $target_dir ]]; then
    dir_modes+=("$(stat -c '%a' -- "$target_dir")")
    printf 'directory\tpresent:%s\t-\t%s\n' "${dir_modes[-1]}" "$target_dir" >> "$backup_manifest"
  else
    dir_modes+=(none)
    printf 'directory\tabsent\t-\t%s\n' "$target_dir" >> "$backup_manifest"
  fi
done

transaction_active=1
transaction_temps=()
rollback_install() {
  local rc=$? tmp rollback_failed=0
  trap - EXIT
  if (( transaction_active )); then
    set +e
    for tmp in "${transaction_temps[@]}"; do
      rm -f -- "$tmp"
    done
    if [[ -f $backup_root/transaction.json ]]; then
      python3 "$support" rollback "$backup_root" || rollback_failed=1
    fi
    if (( rollback_failed == 0 )); then
      printf 'install.sh: failed; prior active files preserved/restored; backup=%s\n' "$backup_root" >&2
    else
      printf 'install.sh: rollback incomplete; inspect backup=%s\n' "$backup_root" >&2
    fi
  fi
  exit "$rc"
}
trap rollback_install EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
prepare_args=(prepare "$script_dir" "$bashrc" "$backup_root")
[[ -z $source_record ]] || prepare_args+=("$source_record")
generation=$(python3 "$support" "${prepare_args[@]}") || die 'generation preparation failed'

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

atomic_install "$generation/bootstrap/common.bash" "$lib_dir/common.bash" 644
atomic_install "$generation/bootstrap/shell.bash" "$lib_dir/shell.bash" 644
atomic_install "$generation/bootstrap/completion.bash" "$lib_dir/completion.bash" 644
atomic_install "$generation/bootstrap/mihomoctl" "$bin_file" 755

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

loader_file=$generation/bootstrap/loader.bash
[[ -f $bashrc ]] || : > "$bashrc"
bashrc_tmp=$(mktemp "${bashrc}.tmp.XXXXXX")
transaction_temps+=("$bashrc_tmp")

# Ubuntu's default .bashrc returns before doing any work in a non-interactive
# shell. Codex Remote uses such a shell, so a loader placed after that guard is
# present on disk but never runs. Detect the standard case guard and keep the
# managed loader before it. Custom startup files without this guard retain the
# historical append/in-place behavior.
guard_line=$(awk '
  /^[[:space:]]*case[[:space:]]+\$-[[:space:]]+in[[:space:]]*$/ {
    candidate=NR
    in_guard=1
    has_return=0
    next
  }
  in_guard {
    if ($0 ~ /(^|[;[:space:]])return([;[:space:]]|$)/) has_return=1
    if ($0 ~ /^[[:space:]]*esac([[:space:]]*#.*)?$/) {
      if (has_return) {
        print candidate
        exit
      }
      in_guard=0
    }
  }
' "$bashrc")
managed_line=
if (( managed_count == 1 )); then
  managed_line=$(grep -Fnm1 "$BEGIN_MARKER" "$bashrc" | cut -d: -f1)
fi

if (( managed_count == 1 )) &&
   [[ -n $guard_line && $managed_line -gt $guard_line ]]; then
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" \
      -v loader="$loader_file" -v insert_before="$guard_line" '
    NR == insert_before {
      while ((getline line < loader) > 0) print line
      close(loader)
    }
    $0 == begin { skipping=1; next }
    skipping && $0 == end { skipping=0; next }
    !skipping { print }
    END { if (skipping) exit 3 }
  ' "$bashrc" > "$bashrc_tmp" || die 'failed to relocate .bashrc loader'
elif (( managed_count == 1 )); then
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
elif [[ -n $guard_line ]]; then
  awk -v loader="$loader_file" -v insert_before="$guard_line" '
    NR == insert_before {
      while ((getline line < loader) > 0) print line
      close(loader)
    }
    { print }
  ' "$bashrc" > "$bashrc_tmp" || die 'failed to place .bashrc loader before the non-interactive guard'
else
  cp -- "$bashrc" "$bashrc_tmp"
  printf '\n' >> "$bashrc_tmp"
  awk '{ print }' "$loader_file" >> "$bashrc_tmp"
fi

bash -n "$bashrc_tmp" || die 'generated .bashrc failed bash -n'
chmod --reference="$bashrc" "$bashrc_tmp"
mv -f -- "$bashrc_tmp" "$bashrc"

doctor_args=(doctor)
(( ! preserve_service_state )) || doctor_args+=(--offline)
MIHOMO_USERCTL_CONFIG=$config_file MIHOMO_USERCTL_LIB_DIR=$generation "$generation/mihomoctl" "${doctor_args[@]}" || {
  die 'doctor failed'
}
python3 "$support" publish "$backup_root" || die 'final generation validation failed'
python3 "$support" finish "$backup_root" || die 'transaction finalization failed'
transaction_active=0
trap - EXIT INT TERM
note "installed mihomo-userctl $VERSION"
note "backup=$backup_root"
note 'the Mihomo service was not enabled or started'
