#!/usr/bin/env bash
# Fail-closed regression for the documentation and secret-scan gates.
#
# tests/docs-test.sh and tests/secret-scan.sh are thin wrappers that exec a
# Python gate, so injecting a broken shell tool no longer exercises anything --
# that is why this test used to pass for the wrong reason. It now injects a
# failing interpreter instead and asserts that neither wrapper can turn a broken
# toolchain into a success report. CI runs it next to the other static checks.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
temp_base=$(cd -- "${TMPDIR:-/tmp}" && pwd -P)
scratch=$(mktemp -d "$temp_base/mihomo-userctl-audit.XXXXXX")
[[ $scratch == "$temp_base"/mihomo-userctl-audit.* && -d $scratch && ! -L $scratch ]] || exit 2
trap 'rm -rf -- "$scratch"' EXIT
mkdir -p "$scratch/bin" "$scratch/fixture/tests" "$scratch/fixture/scripts/ci"
cp "$root/tests/secret-scan.sh" "$scratch/fixture/tests/secret-scan.sh"
cp "$root/scripts/ci/secret_scan.py" "$scratch/fixture/scripts/ci/secret_scan.py"
passed=0

check_failure() {
  local script=$1 expected=$2 rc=0
  shift 2
  PATH="$scratch/bin:$PATH" bash "$script" "$@" > "$scratch/output" 2>&1 || rc=$?
  [[ $rc == "$expected" ]] || { printf 'wrong audit exit: expected=%s actual=%s\n' "$expected" "$rc" >&2; exit 1; }
  if grep -Eq 'required V1 documents|secret scan: reviewed content passed' "$scratch/output"; then
    printf 'failed audit printed a success report\n' >&2
    exit 1
  fi
  passed=$((passed + 1))
}

# The same wrapper must succeed once the interpreter works again; otherwise the
# check above would pass for a permanently broken gate.
check_success() {
  local script=$1
  shift
  bash "$script" "$@" > "$scratch/output" 2>&1 || {
    printf 'audit gate did not succeed: rc=%s\n' "$?" >&2
    cat "$scratch/output" >&2
    exit 1
  }
  passed=$((passed + 1))
}

printf '#!/usr/bin/env bash\nexit 2\n' > "$scratch/bin/python3"
chmod 755 "$scratch/bin/python3"
check_failure "$root/tests/docs-test.sh" 2
check_failure "$scratch/fixture/tests/secret-scan.sh" 2 --directory "$scratch/fixture"
rm -- "$scratch/bin/python3"
check_success "$root/tests/docs-test.sh"

# Generated fake match, not real credentials; the detector must not echo it.
printf '%s=%032d\n' token 0 > "$scratch/fixture/private-fixture"
check_failure "$scratch/fixture/tests/secret-scan.sh" 1 --directory "$scratch/fixture"
if grep -Fq -f "$scratch/fixture/private-fixture" "$scratch/output"; then
  printf 'secret detector disclosed the matching value\n' >&2
  exit 1
fi
rm -- "$scratch/fixture/private-fixture"
touch "$scratch/fixture/client.env"
check_failure "$scratch/fixture/tests/secret-scan.sh" 1 --directory "$scratch/fixture"
printf 'audit regressions: pass=%s fail=0\n' "$passed"