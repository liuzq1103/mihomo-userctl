#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
patterns='(subscribe|subscription|token)[=/?][A-Za-z0-9_-]{20,}|127\.0\.0\.1:17891|/home/[A-Za-z0-9._-]+|C:\\Users\\|(^|[^0-9A-Za-z])liuzq([^0-9A-Za-z]|$)'
# Do not print matching lines: a detector must not become a disclosure channel.
scan_rc=0
grep -RIE --exclude-dir=.git --exclude-dir=__pycache__ --exclude='secret-scan.sh' \
  "$patterns" "$root" >/dev/null 2>/dev/null || scan_rc=$?
if (( scan_rc == 0 )); then
  printf 'possible secret or personal path found; inspect locally without sharing values\n' >&2
  exit 1
elif (( scan_rc != 1 )); then
  printf 'secret scan: grep failed; result unverified\n' >&2
  exit 2
fi
inventory=$(mktemp)
trap 'rm -f -- "$inventory"' EXIT
if ! find "$root" -type f -name client.env -print -quit > "$inventory"; then
  printf 'secret scan: file enumeration failed; result unverified\n' >&2
  exit 2
fi
if [[ -s $inventory ]]; then
  printf 'active client.env must never be committed\n' >&2
  exit 1
fi
printf 'secret scan: no matches in configured repository patterns (not an exhaustive audit)\n'
