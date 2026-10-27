# mihomoctl

mihomoctl 为 Linux 上的 Mihomo 提供用户级运行管理、认证代理环境注入及声明式应用接入。

[English](README.en.md)

## 适用场景和不适用场景

适合在服务器、开发机和 CI 中，让指定命令或应用显式使用已配置的 Mihomo 代理。支持无 systemd 的用户进程，以及可选的 systemd 管理。

它不提供订阅服务，也不保证客户端遵守代理变量；不管理 Codex/Paseo 等第三方应用的生命周期。需要全机透明代理时，须由管理员明确配置 system 作用域及 TUN。

## 系统要求和本源码版本

<!-- stable-version: 1.4.2 -->
本源码版本：**1.4.2**。面向多人共享服务器，每人使用独立 Linux 账号。新增完整发行包内置 Python、Textual、依赖与固定核心，面向 Ubuntu 22.04/24.04 x86_64；无需创建虚拟环境、单独安装界面或使用端口转发。仅在[发布流程](docs/zh-CN/operations/release.md)要求的审核、CI 门禁及正式发布完成后，从 [v1.4.2 发布页](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.4.2) 下载完整包及摘要；公开最新版本以 GitHub Releases 为准。源码和旧式 wheelhouse 套件仍需自行准备运行环境。

## 最短 Quick Start

按 [INSTALL.md](INSTALL.md) 核验并解压完整包，然后运行：

```bash
./mihomoctl
```

在终端向导中粘贴订阅 URL，预览后确认保存并启动，再搜索、测速并选择节点。已有配置不会自动重置。可执行 `./install.sh --user` 安装，之后直接运行 `mihomoctl`；无需 Python、venv 或 pip。

完整界面不依赖 Web；终端能力有限时使用 `mihomoctl tui --engine plain`。使用所选代理启动命令：

```bash
mihomoctl exec -- codex
```

软件准备可离线完成，订阅及其引用资源仍需网络可达。成功操作后不保留旧版本或配置备份，历史回滚已停用。

## 如何初始化并启动 Mihomo

高级 CLI 的 `init` 创建私有配置和带认证的 loopback listener，不下载核心、不启动服务。已有配置可通过 `init --config` 导入。随后显式 `start`；改配置后显式 `restart`。想推回出厂状态就用显式的 `mihomoctl reset --dry-run` 预览、再 `--apply` 执行，它保留核心二进制和订阅缓存，只重置配置与凭据。固定版本核心的安装和 XDG 路径见 [安装与初始化教程](docs/zh-CN/setup.md)。

## 如何配置订阅

普通用户直接在终端界面粘贴订阅 URL，由程序私有保存。脚本调用仍使用私有文件或标准输入，通过 preview/apply 审阅候选；订阅凭据不能放在命令参数里。

```bash
mihomoctl subscription preview --source-file "$HOME/private/subscription.yaml" --policy nodes
```

继续阅读 [订阅教程](docs/zh-CN/subscriptions.md)，了解 auto/nodes/provider 及摘要校验。

## 如何配置自定义规则

先导入订阅，再建立三个私有规则文件，在活动配置中引用对应 provider，并把规则放在 fallback 前。当前检查契约需要名为 `Proxy` 的组。

```bash
mihomoctl rules check --json
```

[完整规则实例](docs/zh-CN/rules.md) 包含目录、权限及可复制配置；检查器只读，保存和 restart 都是显式操作。

## 如何通过代理启动 Codex

先独立安装 Codex，确认 `codex` 在 PATH 中。以下命令只为新子进程注入代理环境：

```bash
mihomoctl exec -- codex
mihomoctl exec -- codex --help
mihomoctl exec -- codex "检查当前项目"
mihomoctl direct -- codex
```

安装第三方 CLI 时，整个安装 Shell 及其后续下载都需要继承代理，见 [代理安装教程](docs/zh-CN/first-run.md#通过代理安装第三方-cli)。

`exec` 的本地健康检查失败时拒绝启动；`direct` 清除八个代理变量。Codex 是否走远端节点还取决于客户端行为、NO_PROXY 和目标路由，见 [首次运行与验证](docs/zh-CN/first-run.md)。

## 如何配置 systemd、容器和 CI 接入

在 manager.yaml 中声明 binding，再使用 `integration check/export/install`。systemd 使用私有环境文件；容器必须指定可达地址；CI 只导出配置。[接入教程](docs/zh-CN/operations/integrations.md) 提供完整实例。第三方服务的重启由操作者完成。

## 如何查看状态和排查问题

```bash
mihomoctl status
mihomoctl health check
mihomoctl doctor
mihomoctl logs --lines 50
```

Listener 可达、选中节点、外部探测成功都不能单独证明 Codex 使用了远端节点。先看运行态，再检查认证代理、目标规则和真实请求；见 [验证与排错](docs/zh-CN/first-run.md)。

## 安全边界

默认 user/process；不自行提权、不运行 sudo、不写 `.bashrc`、`.zshrc`、`profile` 等 Shell 启动文件、不自动操作第三方服务。凭据保存在私有文件，默认输出脱敏；不要把 `--reveal` 输出或导出的环境文件上传。TUN 仅允许明确的 `--system` 操作。更新和卸载保留用户配置、凭据、订阅、缓存与 Mihomo 核心。详见 [安全说明](docs/zh-CN/security.md)。

## 文档导航

- [本地安装 Agent prompt](docs/zh-CN/agent-local-install-prompt.md) · [离线安装](docs/zh-CN/offline-install.md)
- [安装与升级](INSTALL.md) · [教程目录](docs/zh-CN/README.md)
- [命令参考](docs/zh-CN/reference/cli.md) · [配置契约](docs/zh-CN/reference/configuration.md)
- [接入运维](docs/zh-CN/operations/integrations.md) · [发布验收](docs/zh-CN/operations/release.md)
- [仓库结构](docs/architecture-v1.md) · [变更记录](CHANGELOG.md) · [历史归档](docs/archive/README.md)

## 许可证和非官方声明

管理器采用 [MIT License](LICENSE)。完整包还包含按各自许可证分发的 Python、依赖与 Mihomo（GPL-3.0）。包内 `licenses.json` 列出组件及许可文件，核心许可和源码链接见 `core/LICENSE`、`core/SOURCE.txt`。这是独立、非官方的 Mihomo 管理工具，与 Mihomo、OpenAI/Codex 或 Paseo 项目无隶属关系。

## 发现和获取新版本

```bash
mihomoctl release check
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target linux-x86_64
mihomoctl update --latest
```

从 1.2.0 开始，交互式 status、version、doctor 和 TUI 会限频后台查询，后续入口对同一版本只提示一次；失败不影响原命令。JSON、管道和 exec 不触发查询。设置 `MIHOMOCTL_NO_UPDATE_CHECK=1` 可关闭自动检查。通知不会证明当前版本是最新。

v1.0.0–v1.1.1 用户请继续按 [INSTALL.md](INSTALL.md) 使用核验后的新版安装器升级；旧二进制不会自行获得通知功能。获取、跨机器离线安装和失败恢复见 [升级教程](docs/zh-CN/update.md)。
