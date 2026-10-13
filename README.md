# mihomoctl

mihomoctl 为 Linux 上的 Mihomo 提供用户级运行管理、认证代理环境注入及声明式应用接入。

[English](README.en.md)

## 适用场景和不适用场景

适合在服务器、开发机和 CI 中，让指定命令或应用显式使用已配置的 Mihomo 代理。支持无 systemd 的用户进程，以及可选的 systemd 管理。

它不提供订阅服务，也不保证客户端遵守代理变量；不管理 Codex/Paseo 等第三方应用的生命周期。需要全机透明代理时，须由管理员明确配置 system 作用域及 TUN。

## 系统要求和当前稳定版本

<!-- stable-version: 1.1.0 -->
当前稳定版本：**1.1.0**。要求 Linux、Python 3.10+、PyYAML 6.0.1+；安装入口需要 Bash。Mihomo 核心另行提供或显式安装。Textual 界面是可选依赖；默认可用纯终端菜单。Windows 请在 Linux/WSL 中运行。

## 最短 Quick Start

先按 [INSTALL.md](INSTALL.md) 核验发布包、安装控制层和依赖。已有可信 Mihomo 二进制时：

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl start
mihomoctl health check
mihomoctl exec -- curl --fail --head https://example.com
```

初始化的默认规则是 `MATCH,DIRECT`：以上验证本地代理通路，不等于使用了远端节点。继续配置订阅与规则。

## 如何初始化并启动 Mihomo

`init` 创建私有配置和带认证的 loopback listener，不下载核心、不启动服务。已有配置可通过 `init --config` 导入。随后显式 `start`；改配置后显式 `restart`。固定版本核心的安装和 XDG 路径见 [安装与初始化教程](docs/zh-CN/setup.md)。

## 如何配置订阅

将订阅保存为仅本人可读的文件，通过 preview 审阅候选，再用 preview ID 和候选 SHA256 apply，最后显式 restart。URL 也通过私有文件传入，禁止把订阅凭据放在参数里。

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

- [安装与升级](INSTALL.md) · [教程目录](docs/zh-CN/README.md)
- [命令参考](docs/zh-CN/reference/cli.md) · [配置契约](docs/zh-CN/reference/configuration.md)
- [接入运维](docs/zh-CN/operations/integrations.md) · [发布验收](docs/zh-CN/operations/release.md)
- [仓库结构](docs/architecture-v1.md) · [变更记录](CHANGELOG.md) · [历史归档](docs/archive/README.md)

## 许可证和非官方声明

采用 [MIT License](LICENSE)。这是独立、非官方的 Mihomo 管理工具，与 Mihomo、OpenAI/Codex 或 Paseo 项目无隶属关系。
