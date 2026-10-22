# Install mihomoctl 1.3.0

<!-- stable-version: 1.3.0 -->
Linux, Bash and Python 3.10+ are required. The controller needs PyYAML 6.0.1+. Mihomo itself is separate from the controller archive. Complete new setup includes the explicit core and initialization steps below, with no runtime start by default; the installer itself remains controller-only. Default scope is user; no sudo, shell startup file writes (.bashrc, .zshrc, profile) or service actions are performed. [中文初始化教程](docs/zh-CN/setup.md) · [English setup](docs/en/setup.md).

## Verify and install the release

Before installation writes, inspect existing manager/core paths and decide network access. Preserve an existing manager. For complete new setup, reuse a trusted local core or allow the explicit fixed-version download below. Strict offline use requires a verified compatible core and dependencies in advance; report missing materials before installing only the controller. Copy shared/NAS packages and the entire required wheelhouse into an owned private directory before using them.

Obtain mihomoctl-1.3.0.tar.gz (or .zip), SHA256SUMS and build-receipt.json from [v1.3.0](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.3.0). Check that the receipt identifies the tagged commit and the release gate is verified: true. Compare the downloaded digest against a checksum obtained through a trusted independent channel; a colocated checksum alone is not publisher authentication.

In a private working directory containing the downloaded archive and SHA256SUMS:

```bash
umask 077
sha256sum --ignore-missing --check --strict SHA256SUMS
tar -xzf mihomoctl-1.3.0.tar.gz
cd mihomoctl-1.3.0
python3 -m venv "$HOME/.local/share/mihomoctl-python"
"$HOME/.local/share/mihomoctl-python/bin/python" -m pip install --require-hashes --only-binary=:all: -r requirements-lock.txt
bash install.sh --user --source "$PWD" --python "$HOME/.local/share/mihomoctl-python/bin/python"
export PATH="$HOME/.local/bin:$PATH"
mihomoctl version
python3 scripts/bootstrap.py verify --user
```

The dependency installation is the explicit online step. Reuse an existing trusted Python environment if appropriate; do not recreate an existing venv without review. For offline use, download the complete target-specific kit and verify its .sha256 and inner SHA256SUMS; read [offline installation](docs/en/offline-install.md). Alternatively pass an independently verified dependency directory through install.sh --wheelhouse and an explicit --python.

All extracted code and parent directories must be owned by you/root and not group/other writable. Do not use shared writable checkouts. The installer verifies the precise source/runtime inventory and dependency versions. A wheel installation still requires its matching release-manifest.json and complete dependencies; follow the delivered kit README rather than assembling an incomplete wheel directory.

## Upgrade existing v1.0.x installations

Use the verified **v1.3.0 installer above**, not the old installed updater: the old version expects retired Bash version markers. The new installer preserves configuration, credentials, subscriptions, caches and cores, reports a private backup path and does not restart anything. Verify version and installation after upgrading. Keep the backup for self-contained rollback:

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

Do not bypass version/trust gates or add legacy version shims. See [upgrade and rollback](docs/en/update.md).

## Complete new setup: core and initialization

Inspect existing managers and trusted cores before installation. Preserve an existing manager without reinitializing or proactively installing a replacement core. Without a manager, reuse a trusted core; if none exists and networking is allowed, default on Linux x86_64 to the project's fixed tested version (not an upstream latest claim):

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl core install --version v1.19.32
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
mihomoctl config validate
```

Run this branch only for a new manager with no trusted existing core. For a supplied core, instead run init once with its absolute trusted path, followed by config validate. The built-in core digest covers only x86_64/amd64-compatible; arm64/armv7 need a checked corresponding asset SHA256 or trusted local core. Strict offline use requires the core beforehand: neither source nor offline dependency kits include it. Local packages allow an explicit subsequent core download unless strict offline use was requested. Report missing materials before writes. Initial download needs direct access or an already working trusted proxy, not this installation's uninitialized/stopped exec.

Verify controller installation, core version and initialized configuration separately. Leave runtime health and remote routing UNVERIFIED while stopped. When ready to start explicitly:

```bash
mihomoctl start
mihomoctl profile list
mihomoctl health check
```

Already initialized managers do not need init again. On an existing manager, core install activates the replacement and may stop/restart a running core; it is not a harmless preparation step. See [setup](docs/en/setup.md) and the [copyable local agent prompt](docs/en/agent-local-install-prompt.md) ([中文](docs/zh-CN/agent-local-install-prompt.md)). Follow [subscriptions](docs/en/subscriptions.md), [rules](docs/en/rules.md) and [client verification](docs/en/first-run.md). Default MATCH,DIRECT does not establish remote routing. For third-party installers, proxy the entire installation shell and subsequent downloads; follow [download, review and execute](docs/en/first-run.md#install-a-third-party-cli-through-the-proxy).

System installation requires an administrator's explicit leading --system selection; it is never inferred from UID 0. TUN is system-only. User installs work without systemd. Third-party service restarts remain operator actions.

## Uninstall code only

From the verified release tree, `bash uninstall.sh --user` removes managed code/launcher with a recovery backup. It does not delete user data or the Mihomo core, and does not stop running processes. Explicitly stop your managed runtime first when appropriate. [安全边界](docs/zh-CN/security.md) · [Safety boundaries](docs/en/security.md).

## Acquisition from an installed 1.2.0 or newer CLI

`mihomoctl release check` explicitly observes the official stable release.
`mihomoctl update --latest` obtains and verifies a fixed release before invoking
the same offline installer. It retains private backups, version/trust/dependency
gates and self-contained rollback; no runtime is restarted. Explicit network
failures return 2 (UNVERIFIED). Local `mihomoctl update SOURCE` never uses the network.

Use `mihomoctl release fetch --output-dir DIR --target ubuntu22.04-x86_64-py310`
on a connected Linux/WSL machine to obtain a complete portable kit. The other
target is `ubuntu24.04-x86_64-py312`. Transfer the whole directory to the target;
the acquisition record contains relative paths. Follow [offline installation](docs/en/offline-install.md).
Without `--target`, fetch obtains the normal release and does not fetch dependencies.

The downloader trusts official HTTPS and checks tag/receipt/gate/source consistency;
colocated hashes and receipts are not independent publisher signatures. Existing
v1.0.0–v1.1.1 installations still need the verified new installer above. A passive
notification is an additional discovery channel, never a prerequisite for upgrading.
