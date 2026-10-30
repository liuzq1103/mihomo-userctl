# Install mihomoctl 1.5.0.dev0

<!-- stable-version: 1.5.0.dev0 -->

These instructions target source version 1.5.0.dev0. Its download links become available only after the required reviews, CI gates and formal publication; check GitHub Releases before downloading. A candidate build is not a published release.

The complete SSH bundle supports Ubuntu 22.04/24.04 x86_64 and includes Python, Textual, all dependencies and the pinned Mihomo core. No system Python, virtual environment, pip, sudo or port forwarding is required. Each Linux account owns a separate proxy instance.

Use the complete bundle from the [v1.5.0.dev0 release](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.5.0.dev0). Source archives and legacy wheelhouse kits do not include an interpreter. Development builds marked `publishable: false` are not release artifacts.

## Complete offline bundle: verify and run

Obtain `mihomo-userctl-1.5.0.dev0-portable-linux-x86_64.tar.gz` and its `.sha256` sidecar through a trusted release channel. Verify the digest against an independently trusted release record before running code. A colocated checksum alone does not authenticate a publisher. Transfer the whole archive to the server if it cannot access GitHub.

```bash
umask 077
curl --fail --location --remote-name https://github.com/liuzq1103/mihomo-userctl/releases/download/v1.5.0.dev0/mihomo-userctl-1.5.0.dev0-portable-linux-x86_64.tar.gz
curl --fail --location --remote-name https://github.com/liuzq1103/mihomo-userctl/releases/download/v1.5.0.dev0/mihomo-userctl-1.5.0.dev0-portable-linux-x86_64.tar.gz.sha256
sha256sum --check --strict mihomo-userctl-1.5.0.dev0-portable-linux-x86_64.tar.gz.sha256
tar -xzf mihomo-userctl-1.5.0.dev0-portable-linux-x86_64.tar.gz
cd mihomo-userctl-1.5.0.dev0-portable-linux-x86_64
./mihomoctl
```

Keep the extracted directory intact while running from it. The relative launcher uses its own interpreter; moving the complete directory is supported. Use the first-run terminal form to paste an HTTPS subscription URL or select a private YAML file, preview the import, then confirm saving and starting. Select a group and node from the node page. Subscription access still requires connectivity to the subscription endpoint and any referenced providers.

## Optional user installation

```bash
./install.sh --user
export PATH="$HOME/.local/bin:$PATH"
mihomoctl
```

The installer copies the complete program into private user storage, after which the original extraction can be removed. It never downloads dependencies, initializes a manager, starts a service, or writes shell startup files. First-run setup and starting happen explicitly in the terminal UI. Existing managers are preserved. The core is only prepared for a new manager; a manager update never replaces an active core.

## Terminal compatibility and proxy use

```bash
mihomoctl tui --engine plain
mihomoctl --help
mihomoctl exec -- curl --head https://example.com
```

The complete bundle defaults to Textual. The plain menu is available for limited terminals. Interactive invocation without a command opens the UI; JSON and noninteractive invocation never open it. Exiting the UI leaves the user's process backend running. No systemd installation is required.

## Update and recovery policy

```bash
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz --dry-run
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz
```

An existing Python installation can migrate using the new bundle's `./install.sh`; it does not need to understand the new archive format. Use `--allow-same-version` only for an intentional reinstall. Standard Python installation is a supported parallel path; see the Python installation guides linked below. It needs Python 3.10+, dependencies and a separately prepared core.

Close all mihomoctl interfaces for this account before installing, updating or uninstalling; an open interface causes `installation-console-open` before the program is switched. The core can keep running.

Only the current program, core and configuration are kept. Successful operations delete old managed versions, temporary recovery data and completed historical backups. There is no historical rollback; `mihomoctl rollback BACKUP` reports `historical-rollback-disabled`.

Temporary journals exist only while an operation is unfinished. Failure restores the previous files and affected runtime before cleanup. An interrupted transaction is recovered under the user lock on the next operation or UI launch. If recovery fails or an unrelated manual edit is detected, necessary temporary material remains for diagnosis; it is not offered as a history feature. Foreign files and manually supplied interpreters are outside automatic cleanup.

## Package formats and licenses

| Asset | Intended use | Target preparation |
| --- | --- | --- |
| `*-portable-linux-x86_64.tar.gz` | Recommended SSH installation; Ubuntu 22.04/24.04 x86_64 | No Python or package installation |
| `*-offline-ubuntu*-py*.tar.gz` | Legacy offline installation with a wheelhouse | Matching trusted system Python; separately prepared core |
| Source `.tar.gz` / `.zip`, wheel `.whl` | Advanced source/Python installation | Python 3.10+, dependencies and core |

The complete bundle's `licenses.json` lists components and notice files, including Mihomo's GPL-3.0 notice at `core/LICENSE` and upstream source links at `core/SOURCE.txt`. The manager's MIT license does not replace component licenses. Untested distributions and other architectures need separate validation and artifacts.

## Isolation

Configuration, subscription URLs, credentials, caches and logs live in each account's private XDG directories. The generated proxy and controller listen on authenticated loopback ports. Automatically assigned ports are retried on conflict; other users' processes are never stopped. Install/update/uninstall do not edit `.bashrc`, `.zshrc` or `profile`, nor manage third-party applications.

See [中文终端教程](docs/zh-CN/console.md), [English console guide](docs/en/console.md), [subscription configuration](docs/en/subscriptions.md), and [release operations](docs/en/operations/release.md).

## Standard Python installation / 标准 Python 安装

This source is an unreleased development candidate. Public index commands become usable after separate publication. The complete bundle installation above remains supported.

```bash
uv tool install mihomo-userctl
pipx install mihomo-userctl
python3 -m pip install --user mihomo-userctl
python3 -m pip install --no-index --find-links /absolute/wheelhouse mihomo-userctl
```

Ubuntu PEP 668 may reject even `pip --user`. Prefer uv/pipx or a venv; do not bypass system protection. Python packages do not contain an interpreter or core. `tui` is optional. Use the original package manager for upgrades and uninstall, and remove an old `mihomoctl` distribution in that environment first.

Ubuntu 的 PEP 668 可能拒绝 `pip --user`，推荐 uv/pipx 或 venv；完整包无需这些工具。Python 包不包含解释器和核心，Textual 为可选依赖。升级、卸载使用原包管理器。

[English Python guide](docs/en/python-install.md) · [中文 Python 安装](docs/zh-CN/python-install.md)

For 1.4.x complete installations, verify the new bundle and run its new installer once. Old release discovery cannot understand renamed assets. This preserves manager/configuration/credentials and active-core identity. Do not reinstall Python tools over an existing complete installation launcher.
