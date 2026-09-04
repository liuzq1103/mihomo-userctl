#!/usr/bin/env bash
# Run from a reviewed checkout. This script never changes service state.
set +x
set -euo pipefail
umask 077

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
if ! command -v python3 >/dev/null 2>&1; then
  printf 'UNVERIFIED\tdependencies\tpython3-required\n' >&2
  exit 2
fi
if [[ ${1:-} == --help || ${1:-} == -h ]]; then
  exec python3 "$root/scripts/acceptance.py" --help
fi

# shellcheck source=../src/common.bash
source "$root/src/common.bash"
_muc_clear_proxy_variables
_muc_clear_credentials
if ! _muc_load_config 2>/dev/null || ! _muc_load_credentials 2>/dev/null; then
  printf 'FAIL\tconfiguration\towner-mode-or-content-invalid\n' >&2
  exit 1
fi
# Export in this child shell; never put credential values in env's argv.
export MIHOMO_SERVICE MIHOMO_PORT MIHOMO_READY_URL
export MIHOMO_HTTP_PROXY MIHOMO_HTTPS_PROXY MIHOMO_ALL_PROXY
exec python3 "$root/scripts/acceptance.py" "$@"
