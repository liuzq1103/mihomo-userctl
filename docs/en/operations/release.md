# Release operations and acceptance

Work on a dedicated branch. Keep private local files out of Git and the exact source inventory. Current implementation is in mihomoctl/; legacy/v0.9/ is source-only history. Release tools live in scripts/release/ and checks in scripts/ci/.

pyproject.toml is the version authority. Edit it, run `python scripts/release/version.py --sync`, update the latest Changelog and stable-version markers in README.md, README.en.md and INSTALL.md, then run `python scripts/release/version.py --check`. Historical versions are not rewritten. Generated interfaces must pass `python scripts/ci/generate_interfaces.py --check`.

CI requires Ubuntu 22.04/Python 3.10 and Ubuntu 24.04/Python 3.12. Mandatory gates include full unit/controller/UI regression, readonly docs/secret gates, pinned real core, real users/systemd/isolated TUN, exact-commit source and wheel installation/update/self-contained rollback, and both target-specific offline kits with networking disabled. No skipped mandatory suite establishes success.

`python scripts/release/build_release.py` reads version from the selected Git commit, cross-checks runtime/manifest/docs, enforces explicit file inventories and wheel metadata, and writes source archives, wheel, SHA256SUMS and a commit-bound receipt. --worktree output is development-only and never publishable. `python scripts/release/verify_release.py --help` documents the evidence inputs. The gate must report verified: true for the final commit.

Merge through a PR; require the full gate on main's final commit before tagging v1.1.1. Check the tag resolves to that commit, require its full CI evidence, and upload only artifacts built from it: tar.gz/zip sources, wheel, both offline kits, checksums, receipt and gate evidence. Release notes must state that v1.0.x upgrades use the verified v1.1 installer. A real Codex network request is UNVERIFIED until separately observed; do not infer it from CI proxy probes.
