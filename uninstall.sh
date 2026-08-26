#!/usr/bin/env bash
set -euo pipefail

BEGIN_MARKER='# >>> mihomo-userctl managed loader >>>'
END_MARKER='# <<< mihomo-userctl managed loader <<<'
dry_run=0
bashrc=$HOME/.bashrc

die() { printf 'uninstall.sh: %s\n' "$*" >&2; exit 2; }
while (( $# )); do
  case $1 in
    --dry-run) dry_run=1; shift ;;
    --bashrc) [[ $# -ge 2 ]] || die '--bashrc requires a path'; bashrc=$2; shift 2 ;;
    -h|--help) printf 'Usage: ./uninstall.sh [--dry-run] [--bashrc PATH]\n'; exit 0 ;;
    *) die "unknown option: $1" ;;
  esac
done
[[ $bashrc == "$HOME"/* || $bashrc == "$HOME/.bashrc" ]] || die '--bashrc must be inside the current HOME'

data_home=${XDG_DATA_HOME:-$HOME/.local/share}
lib_dir=$data_home/mihomo-userctl
bin_file=$HOME/.local/bin/mihomoctl
targets=("$bin_file" "$lib_dir/common.bash" "$lib_dir/shell.bash" "$lib_dir/completion.bash")

if (( dry_run )); then
  printf 'would remove the managed loader from %s\n' "$bashrc"
  printf 'would remove %s\n' "${targets[@]}"
  printf 'would preserve ~/.config/mihomo, Mihomo, the user service, subscriptions, and caches\n'
  exit 0
fi

if [[ -f $bashrc ]]; then
  count=$(grep -Fxc "$BEGIN_MARKER" "$bashrc" || true)
  (( count <= 1 )) || die 'multiple managed loader blocks found; refusing rewrite'
  if (( count == 1 )); then
    grep -Fqx "$END_MARKER" "$bashrc" || die 'managed loader end marker is missing'
    timestamp=$(date +%Y%m%d-%H%M%S)
    backup=${bashrc}.mihomo-userctl-uninstall-backup.${timestamp}
    cp -p -- "$bashrc" "$backup"
    chmod 600 -- "$backup"
    tmp=$(mktemp "${bashrc}.tmp.XXXXXX")
    awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
      $0 == begin { skipping=1; next }
      skipping && $0 == end { skipping=0; next }
      !skipping { print }
      END { if (skipping) exit 3 }
    ' "$bashrc" > "$tmp" || die 'failed to remove loader'
    bash -n "$tmp" || die 'generated .bashrc failed bash -n'
    chmod --reference="$bashrc" "$tmp"
    mv -f -- "$tmp" "$bashrc"
    printf 'backup=%s\n' "$backup"
  fi
fi

for target in "${targets[@]}"; do
  case $target in
    "$HOME"/.local/bin/mihomoctl|"$lib_dir"/*) [[ -e $target ]] && rm -f -- "$target" ;;
    *) die "unsafe uninstall target: $target" ;;
  esac
done
printf 'removed project-owned code and loader; Mihomo configuration and credentials were preserved\n'
