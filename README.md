# mihomo-userctl · CLI `mihomoctl`

面向多人共享 Linux 服务器的 Agent-first、用户级 Mihomo 管理器，使用 Python 实现。

[English](README.en.md) · [安装与升级](INSTALL.md) · [双语文档](docs/README.md)

<!-- stable-version: 1.5.0.dev0 -->
本源码版本：**1.5.0.dev0**，尚未发布。下列 PyPI 命令是正式发布后的安装入口，目前请使用本地源码或审核过的候选产物。不要寻找不存在的开发版 Release。

## 两种安装方式

已安装 uv 或 pipx 的程序员，可在正式发布后使用：

```bash
uv tool install mihomo-userctl
pipx install mihomo-userctl
```

需要 Textual 人机界面时，改装 `"mihomo-userctl[tui]"`。最小 CLI 只依赖必要的 PyYAML，不包含 Python 解释器或 Mihomo 核心。

```bash
python3 -m pip install --user mihomo-userctl
python3 -m pip install --no-index --find-links /absolute/wheelhouse mihomo-userctl
```

`pip --user` 仅适用于允许用户安装的解释器。Ubuntu 的 PEP 668 保护可能同时拒绝 `--user`；推荐 uv、pipx 或虚拟环境，不要绕过系统保护。离线 wheelhouse 必须同时准备匹配的依赖 wheel。[标准 Python 安装教程](docs/zh-CN/python-install.md) 包含源码、开发、升级和卸载命令。

完整离线包是并列的安装方式：包含固定 Python、Textual、所有依赖与固定 Mihomo 核心，继续支持 Ubuntu 22.04/24.04 x86_64。按 [INSTALL](INSTALL.md) 核验来源和摘要后，运行包内 `./mihomoctl`，或显式运行 `./install.sh --user`。安装器不下载 uv、不初始化 manager、不启动核心、不写 Shell 启动文件。

## Agent 使用入口

```bash
mihomoctl --help
mihomoctl status --json
mihomoctl doctor --json
mihomoctl groups --json
mihomoctl nodes --json
```

顶层帮助包含工作流、安全边界、退出码；子命令帮助说明参数和副作用。公开 JSON 始终为 `mihomoctl/v1`：PASS=0、FAIL=1、UNVERIFIED=2。`exec`/`direct` 启动子进程后保留子进程退出语义。

先记录受影响组的原选择，再按“地区组 → 入口组”调整，使用实际请求验证，最后显式切回并再次读取分组复核。`select` 已检查成员和 provider 同名歧义，并读回实际选择；聚合组默认拒绝直接选叶子，只有明确授权才可用 `--allow-cross-level`。选择与探测成功不证明某应用的请求经过了远端节点。保留 `store-selected` 当前选择，不增加选择历史或删缓存的复原方式。

## 初始化与通用接入

Python 安装需先准备可信核心。新 x86_64 环境需要下载时，显式选择已维护摘要的固定版本；已有 manager 不要重复初始化或替换核心：

```bash
mihomoctl core install --version v1.19.32
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl config validate
mihomoctl start
mihomoctl exec -- curl --head https://example.com
mihomoctl direct -- curl --head https://example.com
```

订阅通过私有文件、私有 URL 文件或标准输入导入，先 preview 再携摘要 apply；URL 和密钥不得放入命令参数。持久接入通过声明式 binding 和通用 `integration` 接口实现，不管理第三方应用生命周期。详见[初始化](docs/zh-CN/setup.md)、[订阅](docs/zh-CN/subscriptions.md)、[接入](docs/zh-CN/operations/integrations.md)。

TUI 是供人类使用的交互界面。Agent 不应启动 TUI，也不得自行执行 reset。重置必须先 `mihomoctl reset --dry-run --json`，经明确的人类授权后，携该预览的摘要执行 `--apply --plan-sha256 HASH`；状态变化会使摘要失效。摘要用于绑定审阅内容，不能替代授权。

## 隔离、维护和升级

每个 Linux 用户拥有独立私有 manager、凭据、核心进程和认证端口。默认 user/process、仅监听 127.0.0.1，无需 root；systemd --user 可选。不自行提权，不接管全局代理，不操作其他用户文件或进程。system 作用域和非本地监听必须明确授权。

安装、更新和卸载均不编辑 `.bashrc`、`.zshrc`、`.profile` 等 Shell 启动文件。

uv/pipx/pip 安装由原工具升级、卸载；内置 `update` 不接管外部 Python 安装。同一环境若曾安装旧 distribution `mihomoctl`，先用原工具卸载旧包再装新包，避免同名 CLI 冲突。完整安装继续使用事务式更新。旧版自动更新器不认识新资产名；1.4.x 用户核验新完整包后运行新版安装器完成一次迁移，保留配置、凭据和活动核心。

成功操作只保留当前受管版本。未完成操作仍有私有事务日志用于失败/中断恢复，成功后清理；不提供历史回滚。包管理器自身缓存不由 mihomoctl 擅自清理。[安全说明](docs/zh-CN/security.md) · [升级](docs/zh-CN/update.md) · [发行验收](docs/zh-CN/operations/release.md)

## 相关项目与许可

可参考 [mihomo-ctrl](https://github.com/wonder-missing/mihomo-ctrl) 的 Agent CLI 工作流，或 [mihoro](https://github.com/spencerwooo/mihoro) 的 Linux 用户实例管理。本项目重点是多人服务器隔离、通用 CLI/integration、配置事务和完整离线交付；这些推荐不表示依赖或隶属关系。

管理器采用 [MIT](LICENSE)。完整包包含按各自许可分发的 Python、依赖和 Mihomo（GPL-3.0）；组件许可及核心源码链接见包内 `licenses.json`、`core/LICENSE` 和 `core/SOURCE.txt`。[CHANGELOG](CHANGELOG.md) · [仓库架构](docs/architecture-v1.md)
