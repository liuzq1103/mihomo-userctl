# Install mihomoctl 1.1.1

<!-- stable-version: 1.1.1 -->
Linux, Bash and Python 3.10+ are required. The controller needs PyYAML 6.0.1+. Mihomo itself is separate. Default scope is user; no sudo, shell startup file writes (.bashrc, .zshrc, profile) or service actions are performed. [中文初始化教程](docs/zh-CN/setup.md) · [English setup](docs/en/setup.md).

## Verify and install the release

Obtain mihomoctl-1.1.1.tar.gz (or .zip), SHA256SUMS and build-receipt.json from [v1.1.1](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.1.1). Check that the receipt identifies the tagged commit and the release gate is verified: true. Compare the downloaded digest against a checksum obtained through a trusted independent channel; a colocated checksum alone is not publisher authentication.

In a private working directory containing the downloaded archive and SHA256SUMS:

```bash
umask 077
sha256sum --ignore-missing --check --strict SHA256SUMS
tar -xzf mihomoctl-1.1.1.tar.gz
cd mihomoctl-1.1.1
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

Use the verified **v1.1.1 installer above**, not the old installed updater: the old version expects retired Bash version markers. The new installer preserves configuration, credentials, subscriptions, caches and cores, reports a private backup path and does not restart anything. Verify version and installation after upgrading. Keep the backup for self-contained rollback:

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

Do not bypass version/trust gates or add legacy version shims. See [upgrade and rollback](docs/en/update.md).

## Initialize and operate

```bash
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl start
mihomoctl profile list
mihomoctl health check
```

Already initialized managers do not need init again. A fixed core may be explicitly installed with core install; see [setup](docs/en/setup.md). Follow [subscriptions](docs/en/subscriptions.md), [rules](docs/en/rules.md) and [client verification](docs/en/first-run.md). Default MATCH,DIRECT does not establish remote routing.

System installation requires an administrator's explicit leading --system selection; it is never inferred from UID 0. TUN is system-only. User installs work without systemd. Third-party service restarts remain operator actions.

## Uninstall code only

From the verified release tree, `bash uninstall.sh --user` removes managed code/launcher with a recovery backup. It does not delete user data or the Mihomo core, and does not stop running processes. Explicitly stop your managed runtime first when appropriate. [安全边界](docs/zh-CN/security.md) · [Safety boundaries](docs/en/security.md).
