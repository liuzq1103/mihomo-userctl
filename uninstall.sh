#!/usr/bin/env bash
# mihomoctl V1 uninstaller bootstrap (installation protocol 2).
#
# Removes only mihomoctl's own installed code and launcher link.  It never
# edits shell startup files, never stops services or third-party daemons,
# and preserves configuration, credentials, subscriptions, cores and caches.
# The previous installation is kept as a self-contained backup; restore it
# with: ./install.sh --rollback <backup>
set -euo pipefail

die() { printf 'uninstall.sh: %s\n' "$*" >&2; exit 2; }

usage() {
  cat <<'EOF'
Usage: ./uninstall.sh [--user|--system] [--dry-run]

Removes the mihomoctl CLI code and its launcher link only.
Options are passed to scripts/bootstrap.py uninstall.

Preserved: manager configuration, credentials, subscriptions, Mihomo cores
and caches.  Never touched: shell startup files, services, third-party
daemons, a legacy 0.9.x installation (use mihomoctl migrate for that).
EOF
}

[[ $(uname -s) == Linux ]] || die 'Linux is required'
[[ -n ${BASH_VERSION:-} ]] || die 'run this uninstaller with Bash'
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
bootstrap=$script_dir/scripts/bootstrap.py
[[ -f $bootstrap ]] || die 'scripts/bootstrap.py not found; run from a complete release tree'

python_bin=
if [[ $EUID == 0 ]]; then
  [[ -x /usr/bin/python3 ]] || die "trusted system Python is required"
  python_bin=/usr/bin/python3
fi
for candidate in python3.12 python3.11 python3.10 python3; do
  [[ -z $python_bin ]] || break
  command -v "$candidate" >/dev/null 2>&1 || continue
  if "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    python_bin=$(command -v "$candidate")
    break
  fi
done
[[ -n $python_bin ]] || die 'Python 3.10+ is required (not found on PATH)'

args=("$@")
for arg in "$@"; do
  if [[ $arg == "-h" || $arg == "--help" ]]; then
    usage
    exec "$python_bin" -I "$bootstrap" uninstall --help
  fi
done
exec "$python_bin" -I "$bootstrap" uninstall "${args[@]}"
