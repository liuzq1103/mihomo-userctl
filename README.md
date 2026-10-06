# mihomo-userctl

**在 Linux 服务器上，让 Codex 按需走代理。**

[English](README.en.md) · [快速开始](#快速开始) · [中文文档](docs/zh-CN/README.md)

为共享服务器和远程开发提供用户级代理接入、服务管理与排错工具。
每个 Linux 用户管理自己的 Mihomo、配置、凭据和独立端口；普通 Shell 默认直连，
需要代理时，用 `mihomoctl codex` 或 `mihomoctl exec -- COMMAND` 启动指定程序。

## 为什么需要它

- 电脑上的代理能用，远程服务器上的 Codex 却连不上：远程进程需要自己的代理接入配置。
- 多人共用科研服务器，希望各自管理代理：使用个人配置和 `systemd --user`，不修改系统全局代理。
- 希望 Codex 走代理，普通下载任务保持原有网络方式：只为显式选择的子进程设置代理环境。
- Mihomo 已启动，应用仍然报连接错误：分别检查服务、监听、认证和进程环境，缩小排错范围。

启动 Mihomo 不会自动代理整个终端。已代理进程启动的下载程序仍可能继承代理变量；
需要清除子进程的代理变量时，使用 `mihomoctl direct -- COMMAND`。

### 已有 Mihomo 或 Mihoro，还需要它吗

**如果你的应用已经稳定联网，通常不需要迁移。**
[Mihomo](https://github.com/MetaCubeX/mihomo) 负责实际代理与路由；
[Mihoro](https://github.com/spencerwooo/mihoro) 已提供无 root、每用户实例和内核、订阅、服务管理。
本项目的价值在于把指定进程接入、Codex 排错和共享服务器部署流程整理成现成工具。
它依赖 Mihomo，不提高节点速度，提供节点查看、切换和面板入口，但不替你管理订阅或保证模型请求成功。
详细职责见[架构](docs/zh-CN/architecture.md)与[Mihoro 对比](docs/zh-CN/mihoro-inspiration.md)。

## 适合哪些环境

| 环境 | 使用方式 |
| --- | --- |
| 远程 Linux 开发服务器 | 通过 SSH 管理个人服务，为指定命令接入代理 |
| 多人共享的科研/计算服务器 | 每个 Linux 账户使用独立配置、认证和未占用的回环端口 |
| 本地 Linux 电脑 | 满足下列依赖时也可使用，适合按命令选择代理 |
| 原生 Windows / macOS | 不在本项目支持范围；已有桌面代理客户端通常即可满足本机需求 |

需要 Linux、Bash 5+、Python 3.8+、可用的 `systemd --user`、`curl`、`ss`、
`journalctl`，以及带认证、仅监听 `127.0.0.1` 的 Mihomo Mixed Listener。
账号、服务访问权限和可用代理节点由用户自行准备。

不需要 root，不使用 TUN 或透明代理。回环端口属于整台主机，认证并不等于严格的跨 UID 防火墙隔离；
安全边界见[安全模型](docs/zh-CN/security.md)。

## 快速开始

### 一条命令安装控制层

```bash
curl -fsSL https://raw.githubusercontent.com/liuzq1103/mihomo-userctl/main/bootstrap.py -o mihomo-userctl-bootstrap.py && python3 mihomo-userctl-bootstrap.py
```

自动解析最新正式发布版本，固定到 commit 后下载，选择空闲代理端口，再调用原有安装器。
需要 Linux、Python 3.8+ 和可用的 systemd 用户服务；**只安装控制层**，Mihomo、订阅和服务配置按下方完整指南准备。
可追加 `--version vX.Y.Z` 固定已发布版本，或 `--dry-run` 预览。详见[快速安装与信任边界](docs/zh-CN/quick-install.md)。
入口只安装正式发布版本，不安装未发布的开发快照。

选择适合目标机器的软件获取方式，把对应指南交给能访问该 Linux 账号终端和文件的 Coding Agent。
默认复用已有适用软件，缺失软件按已选范围安装到个人目录。

| 软件从哪里来 | 安装入口 |
| --- | --- |
| 目标机器能够访问官方来源 | [完整安装指南](docs/zh-CN/setup.md) · [在线安装 Prompt](docs/zh-CN/agent-install-prompt.md) |
| 已提前下载到个人或共享存包目录 | [软件包清单与安装流程](docs/zh-CN/offline-install.md) · [本地软件包安装 Prompt](docs/zh-CN/agent-local-install-prompt.md) |

“本地软件包”指已经备好的文件，也可以用于远程服务器。公共存包目录仅用于分发；
[管理员共享运行时](docs/zh-CN/shared-runtime.md)是另行明确选择的模式。

在线安装可复制：

```text
请阅读 https://github.com/liuzq1103/mihomo-userctl/blob/main/docs/zh-CN/agent-install-prompt.md，
按其中流程为当前 Linux 用户安装 mihomo-userctl。先确定精确已发布版本，
再使用该版本的文档、脚本和测试；遵循安装参数与授权约定，复用已有适用软件。
```

已有软件包可复制：

```text
请阅读 https://github.com/liuzq1103/mihomo-userctl/blob/main/docs/zh-CN/agent-local-install-prompt.md，
从我指定的存包目录为当前 Linux 用户安装。先确定精确已发布版本和软件选择，
使用包内同版本文档、脚本和测试；缺包时报告，不自动转为联网下载。
```

以上是引导语；按对应 Prompt 填写非敏感参数。订阅和凭据只在目标机器本地填写，不发到聊天。
完整安装流程可指导准备 Mihomo；仓库的 `install.sh` **只安装控制层**，不安装或升级 Mihomo 核心，
也不会自行启动或 enable 服务。手动安装按[完整指南](docs/zh-CN/setup.md)执行。

## 装好后怎么用

完成订阅配置后，在普通终端按需启动：

```bash
mihomoctl status
mihomoctl doctor --offline
mihomoctl start
mihomoctl codex preflight
mihomoctl codex
```

v0.7.0 的 `mihomoctl codex preflight` 检查代理配置、服务、认证、HTTP 出站和当前用户的 Codex 进程。
返回 `0 / SAFE_TO_LAUNCH` 才允许启动；`1 / BLOCKED` 或 `2 / UNVERIFIED` 都不启动。
`mihomoctl codex` 内部执行同一完整门禁，不需要先手动运行 preflight；单独运行用于查看报告，
支持 `--json`。旧进程 direct/inconsistent 会阻断，检查不完整会拒绝启动。
它不自动启动 Mihomo、不停止旧进程，也不替你登录。参数放在 `--` 后，例如 `mihomoctl codex -- resume`。
首次使用请继续阅读[首次使用指南](docs/zh-CN/first-run.md)。

```bash
# 通过代理运行其他命令
mihomoctl exec -- curl --head https://example.com/
# 清除指定子进程的代理变量
mihomoctl direct -- curl --head https://example.com/
# 排查 Codex 的现有进程与环境
mihomoctl diagnose codex
```

Bash 中也可用 `with_proxy COMMAND`。已验证的 Remote hook 和 VS Code Remote 各有接入路径，
按[首次使用指南](docs/zh-CN/first-run.md)与[VS Code 集成](docs/zh-CN/vscode-remote.md)操作。
仅写入 `.bashrc` 不代表普通终端运行裸 `codex` 会自动使用代理。

## 查看和切换节点

**远程服务器优先使用 TUI：SSH 登录后直接运行，无需端口映射。**
v0.7 提供全屏终端界面，浏览器面板为可选入口。控制器功能额外需要 PyYAML。

```bash
# 一次性配置，备份并校验，不自动重启
mihomoctl controller setup
# 确认可以中断当前代理连接后重启
mihomoctl restart
mihomoctl tui                # 默认推荐：终端内选节点
mihomoctl groups             # 脚本/只读查看
mihomoctl select "Proxy" "你的节点名称"
mihomoctl ui                 # 可选：浏览器面板
```

内置面板可查看当前选择、切换节点、测延迟和查看实际连接链路，也可安装经 SHA256 校验的 MetaCubeXD 静态包。
远程浏览器通过 SSH 转发访问，不开放公网控制端口。详见[节点管理与面板](docs/zh-CN/control-plane.md)。

## 常见问题

**HTTP 检查通过，为什么 Codex 还失败？**

HTTP proxy ready ≠ Codex runtime ready ≠ model E2E verified。
HTTP 检查只证明该次请求可用；真实客户端的远程传输和模型回复需要单独验证。
本地 Unix socket、localhost 连接应直连，不要把所有 WebSocket 错误都当成远程代理故障。

**改完代理，为什么仍然报旧错误？**

新环境变量不会改变旧 CLI、bridge、app-server 或 VS Code Extension Host。
新 CLI 拥有代理变量也不证明被复用的旧服务已代理。先运行 `mihomoctl diagnose codex`，
保存工作并正常退出、重连自己的客户端；不要批量杀进程或删除 socket、登录态和会话。
该诊断的整体结果为 `UNVERIFIED`、退出码为 `2`，并不等于模型请求失败。

**重启机器后怎么恢复？**

默认服务为 disabled，按需执行 `mihomoctl start`；启动服务仍不会修改当前 Shell。
更多问题见[故障排查](docs/zh-CN/troubleshooting.md)。

## 更新与卸载

当前版本为 v0.7.0；升级前先预览变更。

```bash
mihomoctl update --check
mihomoctl update --version v0.7.0 --dry-run
mihomoctl update --version v0.7.0
```

更新仅升级控制层，保留配置、凭据、端口、loader 和服务 active/enabled 状态；
不升级 Mihomo 核心。详见[更新与回滚](docs/zh-CN/update.md)。
在已审核的源码目录中，`./uninstall.sh --dry-run` 预览，`./uninstall.sh` 卸载控制层及受管 loader，
保留 Mihomo、服务、配置、订阅、缓存和备份。

## 命令与行为参考

<details>
<summary>展开完整命令、退出码、Shell 兼容入口和检查边界</summary>


```text
mihomoctl start
mihomoctl stop
mihomoctl restart

mihomoctl status [--json]
mihomoctl ready [--json]
mihomoctl doctor [--offline] [--json]

mihomoctl codex preflight [--json]
mihomoctl codex [-- ARGS...]
mihomoctl exec -- COMMAND [ARGS...]
mihomoctl direct -- COMMAND [ARGS...]

mihomoctl diagnose url URL [--json]
mihomoctl diagnose process PID [--json]
mihomoctl diagnose name NAME [--json]
mihomoctl diagnose codex [--json]

mihomoctl rules status [--json] [--home-dir PATH] [--config PATH]
mihomoctl rules check [--home-dir PATH] [--config PATH]

mihomoctl controller setup [--port PORT] [--home-dir PATH] [--archive ZIP --sha256 HASH]
mihomoctl controller status [--json]
mihomoctl controller token
mihomoctl tui [--plain]
mihomoctl nodes [--json]
mihomoctl groups [--json]
mihomoctl select GROUP NODE [--json]
mihomoctl latency NODE [--json]
mihomoctl connections [--json]
mihomoctl traffic [--json]
mihomoctl ui [--json]
mihomoctl dashboard [--json]

mihomoctl logs [--lines N] [--follow]
mihomoctl version
mihomoctl update --check | --version TAG [--dry-run]
```

`mihomoctl exec` 是脚本、IDE 启动器和非交互程序的统一入口。`direct` 只在子进程
清除大小写八个代理变量。两者都强制要求 `--`，按参数数组启动命令，不修改父
Shell，并在成功启动后透传目标命令退出码。

`diagnose url` 分别报告 direct、Listener、认证和目标请求。Listener readiness
不等于请求命中代理节点，该命令也不证明选择了哪个节点。

preflight 的退出码见上文；成功启动后的 `codex`/`exec`/`direct` 透传子进程退出码。
以下是其他常规诊断命令的约定：退出码 `0` 表示成功或检查通过，`1` 表示实际观察到运行状态、readiness 或目标
检查失败，`2` 表示参数、配置、权限、依赖或无法可靠验证的错误。`diagnose name`
没有匹配当前用户的精确进程名时返回 `1`。带版本号的 JSON 在成功和正常失败时都
只向 stdout 写入一个对象，人工说明写入 stderr。

### Shell 兼容入口

已经发布的 Shell 函数保持可用：

```text
proxy_on  proxy_off  proxy_status  with_proxy
mihomo_start  mihomo_stop  mihomo_restart  mihomo_status  mihomo_logs
```

`with_proxy` 是现有交互式 Shell 兼容入口；`proxy_on` 明确改变当前 Shell，
`proxy_off` 恢复直连。普通新 Shell 加载后默认直连。

v0.2.1 顶层 `test-url`、`inspect-process` 和 `inspect-name` 仍作为隐藏兼容别名
存在；新脚本统一使用 `diagnose`。

### 范围与证据

`status` 只报告 service active/enabled、Listener 和本地 endpoint；`ready` 只
通过认证路径检查固定 readiness URL；`doctor` 检查依赖、配置、权限与运行状态。
进程诊断只读取当前 UID 的 `/proc` 数据，只返回计数与分类，不返回环境变量值、
完整命令行或远端地址。

`rules status/check` 只是本文档三文件自定义规则契约的只读检查器。它不创建规则、
不改 `config.yaml`、不下载 provider、不调用 Controller，也不改变服务状态。
`rules check` 不等于完整路由行为验收；完整配置语义仍由用户自己的 `mihomo -t`
负责。详见[私有自定义规则](docs/zh-CN/rules.md)。

PASS、FAIL、UNVERIFIED 和 DEFERRED 的证据定义见[验收指南](docs/zh-CN/acceptance.md)；
所有权与安全边界见[架构](docs/zh-CN/architecture.md)和
[安全模型](docs/zh-CN/security.md)。

</details>

## 详细文档

- [完整安装](docs/zh-CN/setup.md)
- [可复制的 Coding Agent 安装 Prompt](docs/zh-CN/agent-install-prompt.md)
- [架构与责任矩阵](docs/zh-CN/architecture.md)
- [安全模型](docs/zh-CN/security.md)
- [验收与证据](docs/zh-CN/acceptance.md)
- [故障排查](docs/zh-CN/troubleshooting.md)
- [私有自定义规则](docs/zh-CN/rules.md)
- [VS Code Remote](docs/zh-CN/vscode-remote.md)
- [更新与回滚](docs/zh-CN/update.md)
- [可复制的 Coding Agent 更新 Prompt](docs/zh-CN/agent-update-prompt.md)

## 许可证

[MIT](LICENSE)。本项目是独立、非官方项目，与 MetaCubeX、Mihomo 和 Mihoro 均无隶属关系。
