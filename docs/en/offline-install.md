# Install from a shared directory

[中文](../zh-CN/offline-install.md) · [Local installation prompt](agent-local-install-prompt.md) · [Public online setup](setup.md)

This optional deployment is for a lab that downloads packages once and shares them read-only.
The public repository keeps official online installation as its default. No lab path is hardcoded,
and binary packages must not be committed to Git. Each account installs its own tools and keeps
its own ports, credentials, subscriptions and services.

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
Record its tag, full commit, archive hash and review in SOURCE.txt. Locally computing the source
archive hash proves transfer consistency, not publisher identity. Use the fixed
[v0.3.0 source ZIP](https://github.com/liuzq1103/mihomo-userctl/archive/refs/tags/v0.3.0.zip),
which includes the helper, manifest and bilingual documentation. Ubuntu 22.04 x86_64 servers
use the x86_64 entries regardless of the download computer's operating system. Target dependency
and runtime compatibility checks are still required.

Prepare this directory manually on the shared volume:

```text
PUBLIC/mihomo-offline/
  offline_install.py       # scripts/offline_install.py from this project
  offline-packages.json    # examples/offline-packages.json
  docs/                   # reviewed bilingual deployment documentation
  source/                 # complete reviewed controller source
  SOURCE.txt              # source provenance and review
  packages/               # archives with original filenames
```

The maintainer controls this directory and its ancestors; other users have read access only.
Do not use world-writable permissions. Publish new bundle directories for updates instead of
changing packages in use. Keep licenses and provenance, never credentials, in this directory.

## Per-user installation

Python 3.8+ with gzip/tarfile/lzma is required. Full controller setup still requires the base
tools and systemd user manager in [setup](setup.md). Missing system dependencies must be
prepared separately by the administrator for the target Ubuntu version; this helper never runs apt.

```bash
PUBLIC='/replace/with/shared/public'
BUNDLE="$PUBLIC/mihomo-offline"
python3 "$BUNDLE/offline_install.py" check \
  --bundle-dir "$BUNDLE/packages" --manifest "$BUNDLE/offline-packages.json" \
  --packages mihomo node codex opencode
python3 "$BUNDLE/offline_install.py" install \
  --bundle-dir "$BUNDLE/packages" --manifest "$BUNDLE/offline-packages.json" \
  --packages mihomo node codex opencode
export PATH="$HOME/.local/bin:$PATH"
```

Select only requested tools, e.g. `--packages mihomo`. `check` verifies bytes only and writes
nothing. Missing files, digest mismatches and unsupported architectures fail with exit code 2;
there is no network fallback. `install` verifies private copies before bounded extraction,
then exclusively creates command links in `~/.local/bin`. All archives are staged before any
link is created. Failures remove this attempt's links and private staging directory.
Files and a provenance/link `receipt.json` live under
`~/.local/share/mihomo-userctl-offline/install-*/`. No package code is executed during installation.
Existing commands, including dangling links, are preserved and cause installation to stop.
Repeated installation therefore never silently replaces a tool. Check `type -a` for other PATH copies.

Copy `source/` to a private workspace. Follow the normal configuration/service/credentials setup,
substituting local packages and source for all download/clone steps. Use the original
`install.sh --suggest-port`, confirm a per-user port, then `bash install.sh --port "$PORT"`
with the confirmed value. The original installer owns controller transactions and rollback.
Do not run write-producing tests or installation inside shared source.

Check only selected tools: `mihomo -v`, `node --version`, `npm --version`, `codex --version`,
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
separately from network-dependent checks (DEFERRED without authorization); untested target
runtime compatibility remains UNVERIFIED.
