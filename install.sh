#!/usr/bin/env bash
# mihomoctl V1 installer bootstrap (installation protocol 2).
#
# This script only finds a Python 3.10+ interpreter and hands over to
# scripts/bootstrap.py.  It never writes shell startup files (.bashrc,
# .zshrc, profile), never starts or stops services or third-party daemons,
# never requires a proxy, and never touches an existing Mihomo core.
# Old 0.9.x updater flags are rejected before any write.
set -euo pipefail
# Release identity, checked statically alongside the manifest before installation.
# shellcheck disable=SC2034
VERSION="1.0.2"

die() { printf 'install.sh: %s\n' "$*" >&2; exit 2; }

usage() {
  cat <<'EOF'
Usage: ./install.sh [OPTIONS]
       ./install.sh --rollback BACKUP

Install or update the mihomoctl CLI from a local, reviewed source
(default: the tree containing this script).  Offline only.

Options are passed to scripts/bootstrap.py; common ones:
  --source PATH          source tree, release .tar.gz/.zip, or wheel directory
  --wheelhouse DIR       directory with dependency wheels (e.g. PyYAML)
  --system               system-wide install (root only; default: user)
  --python BIN           interpreter for the installed launcher
  --dry-run              validate only; change nothing
  --rollback BACKUP      restore the state saved by a previous operation
  -h, --help             full option reference

No shell startup files are modified; no services are started; a proxy is
not required.  An existing Mihomo core is never adopted or replaced.
EOF
}

[[ $(uname -s) == Linux ]] || die 'Linux is required'
[[ -n ${BASH_VERSION:-} ]] || die 'run this installer with Bash'
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

if [[ ${1:-} == "--rollback" ]]; then
  [[ $# -ge 2 ]] || die '--rollback requires a backup directory'
  exec "$python_bin" -I "$bootstrap" rollback "$2" "${@:3}"
fi
if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
  usage
  exec "$python_bin" -I "$bootstrap" install --help
fi
exec "$python_bin" -I "$bootstrap" install "$@"
