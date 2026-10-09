# Install from a shared directory

Examples use the v0.7.0 release. Pin the version and verify the source before deployment.

[中文](../zh-CN/offline-install.md) · [Local installation prompt](agent-local-install-prompt.md) · [Public online setup](setup.md)

A public directory distributes a source ZIP and independent dependency archives. Install Mihomo
and the controller privately per user by default, reuse suitable existing tools, and select other
tools as needed. Archive storage does not imply shared mihomoctl or Node/Codex. Only explicitly
selected administrator-managed tools use [shared-runtime mode](shared-runtime.md).
The public repository also supports official online installation. Never commit binary packages.

## Downloads and preparation

Run `uname -m` and `ldd --version` on the target first. The pinned
[manifest](../../examples/offline-packages.json) contains direct official download URLs, SHA256,
archive layouts and checksum-source URLs for x86_64 and aarch64 (manifest name: arm64).
Download only the chosen architecture and tools. The
[download table](../zh-CN/offline-install.md) provides clickable links for both architectures.
Versions checked on 2026-09-24: Mihomo 1.19.31, Codex CLI 0.156.1, OpenCode 1.18.32,
Node.js 24.21.0 LTS including npm/npx. Node is optional, not required by the controller or
the selected standalone Codex/OpenCode archives. npm dependencies are not bundled automatically.

Digests come from official GitHub Release asset metadata and Node's versioned SHASUMS256.txt.
These are HTTPS metadata checks, not independent signature verification. Review and protect the
manifest itself: replacing both the manifest and an archive defeats a checksum-only check.

Also obtain a reviewed fixed [controller release](https://github.com/liuzq1103/mihomo-userctl/releases).
Obtain its tag, full commit, archive hash and review from trusted delivery records; no separate
SOURCE.txt file is required. Stop and report unknown provenance. Locally computing the source
archive hash proves transfer consistency, not publisher identity. Use the fixed
[v0.7.0 source ZIP](https://github.com/liuzq1103/mihomo-userctl/archive/refs/tags/v0.7.0.zip),
which includes the helper, manifest and bilingual documentation. Ubuntu 22.04 x86_64 servers
use the x86_64 entries regardless of the download computer's operating system. Target dependency
and runtime compatibility checks are still required.

## Public archives, private source workspace

Archives may sit directly in a flat directory, with original dependency filenames:

```text
/mnt/nas/public/software/
  mihomo-userctl-0.7.0.zip
  mihomo-linux-amd64-compatible-v1.19.31.gz
  ...other selected dependency archives for the target architecture
```

No pre-expanded source/, packages/, external scripts or documentation copies are required.
Audit directory/ancestor permissions and provenance without modifying public material. Clarify
ambiguous source versions; never pick latest automatically. Dependencies must match the source manifest.

Create a new private mode-700 workspace, copy the selected source ZIP there, compare SHA256 before
and after copying, and retain provenance records. Before extraction, reject absolute paths, parent
traversal, backslashes/drive paths, symlinks, duplicate members and file/directory collisions. Limit
the archive to 100000 members and 2 GiB total expanded bytes, enforcing the byte limit during writes.
Extract only into a new empty private directory without overwrites; require one project root.
Use existing archive tools or Python's standard library for these checks, not unreviewed package code.
Read the extracted release's documentation and repository constraints; verify release-manifest.json,
install.sh and src/common.bash agree with the selected version before running project scripts.
A ZIP filename alone does not prove release identity. Never run installation/tests in public storage.

## Per-user installation

Python 3.8+ with gzip/tarfile/lzma and the base tools/systemd user manager in [setup](setup.md)
are required. Report missing system dependencies for administrator preparation; never run apt or
download replacements. Run these commands from the reviewed private source directory:

```bash
PUBLIC='/mnt/nas/public/software'  # example; replace with the actual archive directory
python3 scripts/offline_install.py check \
  --bundle-dir "$PUBLIC" --manifest examples/offline-packages.json \
  --packages mihomo
python3 scripts/offline_install.py install \
  --bundle-dir "$PUBLIC" --manifest examples/offline-packages.json \
  --packages mihomo
export PATH="$HOME/.local/bin:$PATH"
```

Skip installing already suitable tools. Add only selected missing tools to `--packages`, for example
`mihomo codex`. `check` verifies bytes, not runtime compatibility, executes no archive code and writes
nothing. Missing files, digest mismatches and unsupported architectures fail with exit code 2;
there is no network fallback. `install` verifies private copies before bounded extraction,
then exclusively creates command links in `~/.local/bin`. All archives are staged before any
link is created. Failures remove this attempt's links and private staging directory.
Files and a provenance/link `receipt.json` live under
`~/.local/share/mihomo-userctl-offline/install-*/`. No package code is executed during installation.
Existing commands, including dangling links, are preserved and cause installation to stop.
Repeated installation therefore never silently replaces a tool. Check `type -a` for other PATH copies.

From the private source workspace, follow the normal configuration/service/credentials setup,
substituting local packages and source for all download/clone steps. Use the original
`install.sh --suggest-port`, confirm a per-user port, then `bash install.sh --port "$PORT"`
with the confirmed value. The original installer owns controller transactions and rollback.
Do not run write-producing tests or installation inside shared source.

Check only selected tools, including reused ones; missing unselected tools are not failures: `mihomo -v`, `node --version`, `npm --version`, `codex --version`,
`opencode --version`. Record real exit codes; run controller regression tests and acceptance.
CPU/libc/runtime compatibility must be checked on the actual host. Hash checks do not establish
compatibility; version output does not establish model or proxy connectivity.

## Updates, rollback and network boundaries

This helper does not perform in-place upgrades or stop processes. Before replacing an installed
tool, review its receipt and running processes, back up the existing links/files, and remove only
the reviewed personal links before installing a new bundle. To undo an installation, remove only
links still pointing to the targets recorded in that receipt, then remove that specific install
directory when no longer needed. Controller rollback uses its separate original installer backup.

`mihomoctl update`, including `--check`, remains an online GitHub operation and must not be used
in the local-only workflow. A reviewed new local source snapshot can be installed with the original
installer and its backup/rollback behavior; review source provenance separately. This does not
manage updates to Node, Codex or OpenCode.

The helper itself uses no network and never launches downloaded programs. Runtime authentication,
model APIs, subscriptions and rule/provider updates can require network access. For a managed lab,
merge `"autoupdate": false` into personal OpenCode configuration using the
[official guidance](https://opencode.ai/docs/config/#autoupdate), preserving existing settings.
Plugins, LSP, MCP, Geo data and other remotely referenced resources need separate preparation
when selected; private subscriptions belong only in personal directories. Report local checks
separately from network-dependent checks (UNVERIFIED without authorization; DEFERRED only when
explicitly postponed). Untested target runtime compatibility remains UNVERIFIED. Follow the
[deployment contract](deployment-contract.md) for reuse, startup authorization and Codex evidence.
<!-- Core compatibility: package integrity and runtime capabilities are independent. -->

The listed core version is a verified example, not an exact runtime restriction. Reuse an existing Mihomo core, or supply another version through a custom manifest with its file, architecture and trusted SHA256. Hash verification remains mandatory; runtime compatibility follows config validation and API capabilities.
