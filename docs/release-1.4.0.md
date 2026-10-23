# 1.4.0 release notes / 发布说明

## SSH terminal setup / SSH 终端配置

Download `mihomoctl-1.4.0-portable-linux-x86_64.tar.gz` and its `.sha256` from the [release](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.4.0). Verify, extract into private storage and run `./mihomoctl`, or install with `./install.sh --user`. The bundle includes pinned Python 3.12.15, Textual 8.2.8, all UI dependencies and Mihomo v1.19.32. Supported targets: Ubuntu 22.04/24.04 x86_64. No host Python, pip, venv, sudo, systemd, browser or port forwarding is needed.

从发布页下载完整包和摘要，核验后解压到本人私有目录，运行 `./mihomoctl`；也可执行 `./install.sh --user` 安装。包内包含固定的 Python、Textual、全部界面依赖及 Mihomo，面向 Ubuntu 22.04/24.04 x86_64，无需另装 Python、venv 或界面组件。

Each person uses a separate Linux account, private subscription and authenticated loopback proxy instance. The terminal wizard accepts a hidden HTTPS URL or a YAML file, previews imports and asks before saving and starting. New simple configurations create a manual Proxy group and default proxy route. Existing configuration is preserved until explicitly changed. Search nodes, run individual/batch delay tests and select nodes; selection survives restart. Exit the UI while keeping the core running. Use `mihomoctl exec -- COMMAND` for proxy environment injection. The plain numbered menu remains available with `mihomoctl tui --engine plain`.

每人独立账号、订阅、认证与核心实例；终端内完成订阅输入、预览、确认启动、节点搜索、测速与选择，重启保留选择。退出界面后核心继续运行。软件包可离线传入，远程订阅及引用资源仍需相应网络访问。

## Upgrade policy / 升级与清理

**Only the current managed software, core and configuration are retained. No historical backups or rollback are provided.** Operations temporarily retain the material needed to restore their starting state on failure. Interrupted operations recover before subsequent work; successful operations/recovery delete temporary material. Recovery failures or unrelated manual edits preserve necessary material and report an error. `mihomoctl rollback BACKUP` returns `historical-rollback-disabled`. A committed-cleanup-pending error means the change has already taken effect and cleanup will be retried.

**只保留当前软件、核心和配置，不保留历史备份或提供历史回滚。** 仅在操作未完成时临时保留失败恢复材料。成功或恢复完成后清理；恢复失败或检测到无关手动修改时保留必要材料并报告。已提交但清理待完成的错误表示新状态已生效，下次加锁操作重试清理。

Close all mihomoctl interfaces for the account before installing/updating/uninstalling; `installation-console-open` refuses a switch while a console is open. The core can keep running. To migrate an older Python installation, use this release's verified bundle installer, preserving the existing manager and active core. Manager updates do not replace an active core, restart it, edit shell startup files or manage third-party services. Source/wheelhouse assets remain advanced compatibility formats and need a trusted matching Python environment and separately prepared core.

升级前关闭本账号所有 mihomoctl 界面，核心可继续运行。旧版 Python 安装使用本次完整包中的安装器迁移，不要求旧 updater 识别新格式；已有 manager 和活动核心保留。管理器更新不自动换核心、重启服务或修改 Shell 启动文件。

## Validation and licenses / 验收与许可

Published candidates must pass the exact-commit release gate on both supported Ubuntu targets: unit and real-core regressions, legacy migration/offline installation, real users/systemd/isolated TUN, plus the complete bundle with networking disabled and two distinct UIDs. SSH/PTY coverage includes Chinese input, search, resize, authenticated API isolation, restart persistence, open-console update refusal and removal of historical copies. Download `release-gate.json`, `build-receipt.json` and `validation-evidence.json` for the published commit and measurements. Worktree builds marked `publishable:false` are development outputs.

正式产物需通过两个 Ubuntu 目标的精确提交门禁；证据包括业务回归、真实核心、旧格式迁移、无网络完整包、双用户隔离及真实 SSH。实际包大小、安装占用、启动耗时和界面内存记录在发布验收证据中。

The manager is MIT-licensed. The bundle's `licenses.json` lists components and notice files, including Mihomo's GPL-3.0 notice at `core/LICENSE` and upstream source links at `core/SOURCE.txt`. See [installation](../INSTALL.md), [中文界面指南](zh-CN/console.md), [English console guide](en/console.md) and [release operations](en/operations/release.md).
