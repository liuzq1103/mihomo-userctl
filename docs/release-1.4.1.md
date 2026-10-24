# 1.4.1 release notes / 发布说明

The complete Linux x86_64 bundle retains pinned Python 3.12.15, Textual 8.2.8, all UI dependencies and Mihomo v1.19.32. Ubuntu 22.04/24.04 remain supported. Transfer the verified archive to a server and run `./mihomoctl` or `./install.sh --user`; no host Python or network installation is required.

完整离线包继续内置固定的 Python、Textual、界面依赖与 Mihomo 核心，支持 Ubuntu 22.04/24.04 x86_64。核验并传入服务器后，运行 `./mihomoctl` 或 `./install.sh --user`，无需系统 Python 或联网安装组件。

## Smaller runtime / 运行时瘦身

Remove two duplicate interpreter files, the duplicate development linker alias, headers, ensurepip, IDLE and obsolete wrappers. Keep the versioned shared Python library, standard library, Tcl/Tk, terminfo and component licenses. `runtime-trim.json` records removed paths, byte counts and hashes. The private interpreter supports the application; development tools and default pip-enabled `venv` creation are not included.

删除重复解释器和开发用库别名，以及 headers、ensurepip、IDLE 和相应脚本。保留版本化 Python 共享库、标准库、Tcl/Tk、terminfo 与许可证；包内 `runtime-trim.json` 记录删除项、字节数和摘要。私有解释器用于运行本产品，不包含开发工具或默认携带 pip 的 venv 创建能力。

The release gate requires archive size at most 65,000,000 bytes, expanded regular-file size at most 160,000,000 bytes, and at most 225,000,000 logical bytes after first installation and core initialization in the fixed acceptance fixture. Published measurements come from the accepted candidate, not development-package estimates. Upgrade peaks are recorded separately and are not subject to the first-install budget. Physical allocation depends on the filesystem. Peaks are observed samples at 50ms, including per-home temporary copies; external input archives and temporary storage outside the test home are reported separately.

发布门禁要求完整包不超过 65 MB、解压普通文件不超过 160 MB、固定验收场景首次安装并初始化核心后的逻辑占用不超过 225 MB，均为十进制。发布数据来自正式候选，开发包估算不作为验收结果。升级峰值另行记录，不适用首次安装门槛；实际磁盘分配取决于文件系统。峰值为每 50ms 采样的观测值，包含验收 home 内临时副本；外部输入包及 home 外临时存储单独报告。

## Upgrade and validation / 升级与验收

Close the account's consoles before updating; an active console still blocks replacement. The core may keep running. Both Ubuntu targets must pass a real v1.4.0 portable upgrade with unchanged core PID/start time, executable path/digest, controller authentication, selected node, configuration and credentials. Existing v1.0.x migration, offline installation, two-UID/SSH and recovery regressions remain mandatory.

升级前关闭本账号的控制台，核心可以继续运行。两个 Ubuntu 目标均需通过真实 v1.4.0 完整包升级验收，验证核心 PID、启动时间、二进制路径与摘要、控制接口认证、节点选择、配置和凭据保持一致；继续保留旧版 v1.0.x 迁移、离线安装、双用户与真实 SSH、失败恢复等验收。

Only the current software/core/configuration is retained. Temporary transaction recovery is preserved until completion; historical rollback remains disabled. Manager updates do not restart or replace an active core or edit shell startup files. Legacy source/wheelhouse assets remain available.

只保留当前软件、核心和配置；未完成事务保留必要恢复材料，不提供历史回滚。管理器更新不重启或替换活动核心，不修改 Shell 启动文件；继续提供源码和离线 wheelhouse 兼容资产。

Publication reuses the exact successful main CI artifacts. Draft assets are downloaded and verified before publication; public downloads, release acquisition and `update --latest` from v1.4.0 are verified afterwards. See [installation](../INSTALL.md), [English release operations](en/operations/release.md) and [中文发布验收](zh-CN/operations/release.md).

发布直接复用 main 上通过验收的原始 CI 产物；草稿阶段先下载核对，公开后再验证下载、发行获取和从 v1.4.0 执行 `update --latest`。
