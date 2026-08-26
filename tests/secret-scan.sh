#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
patterns='(subscribe|subscription|token)[=/?][A-Za-z0-9_-]{20,}|127\.0\.0\.1:17891|/home/liuzq|C:\\Users\\liuzq'
if grep -RInE --exclude-dir=.git --exclude='secret-scan.sh' "$patterns" "$root"; then
  printf 'possible secret or personal path found\n' >&2
  exit 1
fi
if find "$root" -type f -name client.env -print -quit | grep -q .; then
  printf 'active client.env must never be committed\n' >&2
  exit 1
fi
printf 'secret scan: clean\n'
