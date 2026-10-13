# V1 本地离线安装 Agent Prompt

[English](../en/agent-local-install-prompt.md) · [完整离线流程](offline-install.md) · [安装契约](../../INSTALL.md)

适用于 1.0.2 及之后采用相同交付格式的发布。填写参数后使用；授权和脱敏报告遵循
[安装参数与交付约定](deployment-contract.md)。

```text
请为当前普通 Ubuntu 用户安装本地 mihomoctl 控制层，完成已有授权内的工作并返回实际证据。
套件路径：<完整离线套件的绝对路径>
精确版本：<例如 1.0.2；有多个候选时不自行选择最新版>
可信预期 SHA256：<从不能与共享包一同被篡改的渠道取得>
可信完整 commit / 来源记录：<另行核对的发布记录>
目标环境：<Ubuntu 22.04 / CPython 3.10 / x86_64，或 Ubuntu 24.04 / CPython 3.12 / x86_64>
目标解释器：/usr/bin/python3
启动策略：只安装，保留已有运行状态；初始化/启动/迁移需明确选择。

先只读检查系统版本、架构/libc、解释器路径和版本、现有依赖、PATH、同名程序、服务状态、
配置指纹、Shell 文件和代理环境分类。不要输出凭据、订阅链接、原始环境或完整进程参数。
which python 指向 Anaconda 不代表应使用它。系统 Python 3.10.12 + PyYAML 5.4.1 不满足
PyYAML>=6.0.1，即使可以导入也不能豁免版本要求；使用匹配 wheelhouse，不升级系统或 Conda。

按同版本 offline-install.md，先用可信外部摘要验证套件，再用系统工具/Python 标准库安全解压
到新建权限 700 的个人目录。拒绝路径越界、链接、特殊文件、重复成员、多根目录和超限大小。
校验内部 SHA256SUMS 和 release/SHA256SUMS，核对 bundle-manifest.json、build-receipt.json
的版本、完整 commit、目标和来源记录。共享目录可写、复制摘要一致或包内 receipt 均不能独立
证明来源；来源不明写 UNVERIFIED 并停止，不改共享文件或权限。

安全解压源码；审阅 INSTALL.md、offline-install.md、security.md、acceptance.md、v1.md、
deployment-contract.md 和仓库约束后才能运行项目脚本。静态核对以下五处版本，缺失、重复
或不一致均停止：release-manifest.json、pyproject.toml project.version、mihomoctl/__init__.py
__version__、install.sh VERSION=、src/common.bash MIHOMO_USERCTL_VERSION。
项目 wheel 的版本、Requires-Dist、载荷须与同发布 manifest 一致；拒绝字节码及未审核文件。

从已审核私有源码目录执行（KIT 为已核验套件的绝对路径）：
  bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse" --dry-run
  bash install.sh --python /usr/bin/python3 --wheelhouse "$KIT/wheelhouse"
  "$HOME/.local/bin/mihomoctl" version
  /usr/bin/python3 -I scripts/bootstrap.py verify
缺包、摘要不符、依赖版本不满足或 wheel 的 Python/架构不匹配，报告具体缺项并停止。
仅当所选解释器的依赖版本和实际导入均满足声明时才可省略 wheelhouse。
禁止 GitHub/npm/apt/pip 联网补齐，不运行旧 scripts/offline_install.py 或旧 bootstrap.py。
遇到同名程序保留现状，先报告具体迁移/备份方案，不自行替换。

套件不含 Mihomo、OpenCode、Codex、Node，提醒用户自行安装或准备；不要自动安装这些工具、
插件、LSP、MCP 或扩展。控制层安装不接管或替换既有 Mihomo，不启动/停止服务，不改 .bashrc
或其他 Shell 启动文件，不注册 proxy_on/proxy_status/with_proxy 或 hook。默认 process 后端，
无需 systemd。端口以后由显式 init --port 和命名 listener profile 设置，没有安装器端口参数。
旧 0.x 迁移先做 mihomoctl migrate --dry-run，仅明确选择后 --apply。
代理接入使用显式 mihomoctl exec / env / integration；保留所有已有认证、会话、订阅和配置。
不使用 sudo、不改系统服务/TUN/系统代理，不为测试停止已有服务。已有授权内无需重复确认。

运行适用回归并保留真实退出码；未执行的平台/服务/外网/模型验收记 UNVERIFIED，只有用户明确
延后才写 DEFERRED。报告安装前后状态、版本/架构/摘要/来源、私有路径、receipt、备份及回滚
命令、实际测试结果和剩余项；不能宣称包内摘要提供独立官方签名验证。
依 deployment-contract.md 提醒订阅的实际私有配置路径和本地编辑方法，不索取聊天中的链接。
仅选择 Codex 交付时使用 first-run.md 状态机和授权模型验收；不直接运行裸 codex 绕过门禁。
```
