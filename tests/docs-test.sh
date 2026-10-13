#!/usr/bin/env bash
# V1 documentation gate. Kept as a thin wrapper so the historical entry point
# still works; the assertions themselves live in scripts/ci/check_docs_v1.py, which
# is what .github/workflows/test.yml actually runs.
#
# The pre-V1 shell assertions that used to live below this exec line were removed
# in v1.0.1. They had never executed -- the exec above them was already in place
# -- and several of them pinned a retired product:
#
#   * docs/{en,zh-CN}/paseo.md and paseo-production.md daemon-lifecycle markers;
#   * first-use handoff markers that V1's rewritten first-run.md no longer uses;
#   * scripts/offline_install.py and --bundle-dir in the local installation
#     prompt, and the retired ./install.sh --suggest-port in the generic prompt;
#   * a 90-line budget for the generic installation prompt;
#   * the presence of the CODEX_REMOTE_PAYLOAD fail-closed hook in src/shell.bash,
#     which V1 removed on purpose.
#
# Every assertion that still describes the V1 product was migrated into
# scripts/ci/check_docs_v1.py, which additionally rejects any `install.sh --<flag>`
# in docs/**/*.md that scripts/bootstrap.py does not accept.
_v1_test_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
exec python3 "$_v1_test_root/scripts/ci/check_docs_v1.py" "$@"