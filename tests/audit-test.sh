#!/usr/bin/env bash
# Inject tool failures without modifying the real checkout or active service.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
temp_base=$(cd -- "${TMPDIR:-/tmp}" && pwd -P)
scratch=$(mktemp -d "$temp_base/mihomo-userctl-audit.XXXXXX")
[[ $scratch == "$temp_base"/mihomo-userctl-audit.* && -d $scratch && ! -L $scratch ]] || exit 2
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/fixture/tests"
cp "$root/tests/secret-scan.sh" "$scratch/fixture/tests/secret-scan.sh"
passed=0

check_failure() {
  local script=$1 expected=$2 rc=0
  PATH="$scratch/bin:$PATH" bash "$script" > "$scratch/output" 2>&1 || rc=$?
  [[ $rc == "$expected" ]] || { printf 'wrong audit exit: expected=%s actual=%s\n' "$expected" "$rc" >&2; exit 1; }
  if grep -Eq 'relative links are complete|secret scan: clean|secret scan: no matches' "$scratch/output"; then
    printf 'failed audit printed a success report\n' >&2
    exit 1
  fi
  passed=$((passed + 1))
}

for tool in find grep; do
  printf '#!/usr/bin/env bash\nexit 2\n' > "$scratch/bin/$tool"
  chmod 755 "$scratch/bin/$tool"
  check_failure "$root/tests/docs-test.sh" 2
  check_failure "$scratch/fixture/tests/secret-scan.sh" 2
  rm -- "$scratch/bin/$tool"
done

# Generated fake match, not real credentials; the detector must not echo it.
printf '%s=%032d\n' token 0 > "$scratch/fixture/private-fixture"
check_failure "$scratch/fixture/tests/secret-scan.sh" 1
if grep -Fq -f "$scratch/fixture/private-fixture" "$scratch/output"; then
  printf 'secret detector disclosed the matching value\n' >&2
  exit 1
fi
rm -- "$scratch/fixture/private-fixture"
touch "$scratch/fixture/client.env"
check_failure "$scratch/fixture/tests/secret-scan.sh" 1
printf 'audit regressions: pass=%s fail=0\n' "$passed"
