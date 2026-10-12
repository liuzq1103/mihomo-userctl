# V1 local offline installation agent prompt

[中文](../zh-CN/agent-local-install-prompt.md) · [Complete offline flow](offline-install.md) · [Installation contract](../../INSTALL.md)

Use for 1.0.2 and later releases retaining the same kit format. Fill the parameters first.
Authorization and redacted reports follow the [delivery contract](deployment-contract.md).

```text
Install the local mihomoctl control plane for this ordinary Ubuntu user within existing authorization,
and return actual evidence.
Kit path: <absolute complete-offline-kit path>
Exact version: <for example 1.0.2; never choose latest among ambiguous candidates>
Trusted expected SHA256: <obtained through a channel independent of the writable shared archive>
Trusted full commit / provenance: <separately checked release record>
Target: <Ubuntu 22.04 / CPython 3.10 / x86_64, or Ubuntu 24.04 / CPython 3.12 / x86_64>
Interpreter: /usr/bin/python3
Startup: install only, preserving current state; initialization/start/migration require explicit selection.

First inspect OS, architecture/libc, interpreter path/version, dependencies, PATH, existing commands,
service state, configuration fingerprints, shell files and proxy-variable categories read-only.
Never disclose credentials, subscription URLs, raw environment or full process argv.
An Anaconda python on PATH is not an instruction to select it. System Python 3.10.12 + PyYAML 5.4.1
fails PyYAML>=6.0.1 even if imports succeed. Use matching wheels, without upgrading system or Conda.

Follow the same release's offline-install.md. Verify the kit against the trusted external digest before
running code. Safely extract with system tools/Python standard library into a new private mode-700 tree;
reject escapes, links, special files, duplicates, multiple roots and excessive size.
Check internal SHA256SUMS and release/SHA256SUMS, then compare bundle-manifest.json and build-receipt.json
version/full commit/target against the trusted record. Writable shared storage, matching copy hashes and
enclosed receipts do not independently authenticate provenance. Report UNVERIFIED and stop when unknown;
never modify shared files or permissions.

Safely extract and review INSTALL.md, offline-install.md, security.md, acceptance.md, v1.md,
deployment-contract.md and repository constraints before project scripts. Statically check five matching
versions: release-manifest.json, pyproject.toml project.version, mihomoctl/__init__.py __version__,
install.sh VERSION= and src/common.bash MIHOMO_USERCTL_VERSION. Missing, duplicate or inconsistent
markers stop installation. Project wheel version, Requires-Dist and payload must match the release
manifest. Reject bytecode and unreviewed payload files.

From reviewed private source, with KIT set to the verified kit's absolute path:
  bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse" --dry-run
  bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse"
  "$HOME/.local/bin/mihomoctl" version
  /usr/bin/python3 -I scripts/bootstrap.py verify
Report and stop for missing files, hash mismatches, dependency-version failures or incompatible wheels.
Omit wheelhouse only when both declared dependency versions and actual imports pass for selected Python.
Never download from GitHub/npm/apt/pip as a fallback, or use old scripts/offline_install.py/bootstrap.py.
Preserve conflicting existing commands; report a concrete backup/migration plan before replacement.

Mihomo, OpenCode, Codex and Node are not included. Remind the user to prepare/install them themselves;
do not automatically install these tools, plugins, LSPs, MCPs or extensions. Control-plane installation
never adopts/replaces an existing Mihomo core, starts/stops services, writes .bashrc/other startup files,
or registers proxy_on/proxy_status/with_proxy/hooks. Default backend is process, without systemd.
Set ports later using explicit init --port and named listener profiles, not installer port parameters.
For 0.x migration, inspect mihomoctl migrate --dry-run before explicitly choosing --apply.
Use explicit mihomoctl exec / env / integration; preserve authentication, sessions, subscriptions and
configuration. Never use sudo or alter system services, TUN or system proxy; do not stop existing services
for testing. Existing authorization does not require repeated confirmation.

Run applicable regressions and preserve exit codes. Unexecuted platform/service/external/model checks are
UNVERIFIED; use DEFERRED only when explicitly requested. Report before/after state, versions/architecture/
digests/provenance, private paths, receipts, backups/rollback, actual tests and remaining items.
Never claim enclosed checksums provide independent official signature verification.
Follow deployment-contract.md for private subscription configuration paths/local editing instructions;
never ask for subscription URLs in chat. Only if Codex delivery was selected, follow first-run.md's
state machine and authorized model acceptance; do not bypass the gate by invoking bare codex.
```
