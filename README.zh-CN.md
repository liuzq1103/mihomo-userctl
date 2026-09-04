# mihomo-userctl

`mihomo-userctl` 是现有 Linux 用户级
[Mihomo](https://github.com/MetaCubeX/mihomo) 服务之上的轻量控制、进程接入和
验收层，面向共享服务器、远程开发与科研计算：普通 Shell 默认直连，只有用户
明确选择的命令或进程才进入带认证的本地 Listener。

它不是另一个 Mihomo 客户端，不管理订阅、节点、DNS、通用路由配置或运行时流量；
不需要 root 权限，也不修改其他用户或系统全局网络。

> 本项目是独立、非官方项目，与 MetaCubeX、Mihomo 和 Mihoro 均无隶属关系。

[English](README.md) · [文档语言导航](docs/README.md)

## 边界

```text
普通 Shell / 大型下载 ───────────────────────> 服务器直连

mihomoctl exec -- COMMAND / with_proxy COMMAND
        │
        └─ 经验证的八变量子进程环境
             └─ 带认证的 127.0.0.1:<每用户端口>
                  └─ Mihomo ──> 用户自有路由策略
```

启动 Mihomo 不会代理当前 Shell。环境变量也不会追溯修改已运行进程：Codex、
VS Code Remote、Notebook、tmux 等长期进程可能需要用户主动重连或重启。

每个 Linux 账户使用独立的 XDG 路径、服务设置、凭据和唯一端口。Listener 必须
认证；配置文件按数据解析，并采用固定键白名单。

## 条件与安装

需要 Linux、Bash 5+、Python 3.8+、可用的 `systemd --user` 管理器、`curl`、
`ss`、`journalctl`，以及用户已有的 Mihomo 服务；其 Mixed Listener 必须带认证，
且只绑定 `127.0.0.1`。

本项目不安装或升级 Mihomo 核心。需要时先阅读[完整安装指南](docs/zh-CN/setup.md)。

选择并确认当前未占用的每用户端口，在 Mihomo 与 `client.env` 中配置同一端口，
再安装控制层：

```bash
PROXY_PORT=$(./install.sh --suggest-port)
ss -lnt "sport = :$PROXY_PORT"
./install.sh --dry-run --port "$PROXY_PORT"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
```

安装过程使用事务、记录不可变运行模块摘要与来源、保留凭据和 Mihomo 数据，并且
不会启动或 enable 服务。

## 更新

```bash
mihomoctl update --check
mihomoctl update --version v0.2.2 --dry-run
mihomoctl update --version v0.2.2
```

更新只改变 `mihomo-userctl`，不等于 Mihomo 核心升级。它复用同一事务安装器，
保留配置、凭据、端口、loader 和 active/enabled 状态，并记录精确发布 commit。
退出码与恢复方式见[更新与回滚](docs/zh-CN/update.md)。

## 日常命令

```text
mihomoctl start
mihomoctl stop
mihomoctl restart

mihomoctl status [--json]
mihomoctl ready [--json]
mihomoctl doctor [--offline] [--json]

mihomoctl exec -- COMMAND [ARGS...]
mihomoctl direct -- COMMAND [ARGS...]

mihomoctl diagnose url URL [--json]
mihomoctl diagnose process PID [--json]
mihomoctl diagnose name NAME [--json]

mihomoctl rules status [--json] [--home-dir PATH] [--config PATH]
mihomoctl rules check [--home-dir PATH] [--config PATH]

mihomoctl logs [--lines N] [--follow]
mihomoctl version
mihomoctl update --check | --version TAG [--dry-run]
```

`mihomoctl exec` 是脚本、IDE 启动器和非交互程序的统一入口。`direct` 只在子进程
清除大小写八个代理变量。两者都强制要求 `--`，按参数数组启动命令，不修改父
Shell，并在成功启动后透传目标命令退出码。

`diagnose url` 分别报告 direct、Listener、认证和目标请求。Listener readiness
不等于请求命中代理节点，该命令也不证明选择了哪个节点。

退出码 `0` 表示成功或检查通过，`1` 表示实际观察到运行状态、readiness 或目标
检查失败，`2` 表示参数、配置、权限、依赖或无法可靠验证的错误。`diagnose name`
没有匹配当前用户的精确进程名时返回 `1`。带版本号的 JSON 在成功和正常失败时都
只向 stdout 写入一个对象，人工说明写入 stderr。

## Shell 兼容入口

已经发布的 Shell 函数保持可用：

```text
proxy_on  proxy_off  proxy_status  with_proxy
mihomo_start  mihomo_stop  mihomo_restart  mihomo_status  mihomo_logs
```

`with_proxy` 是现有交互式 Shell 兼容入口；`proxy_on` 明确改变当前 Shell，
`proxy_off` 恢复直连。普通新 Shell 加载后默认直连。

v0.2.1 顶层 `test-url`、`inspect-process` 和 `inspect-name` 仍作为隐藏兼容别名
存在；新脚本统一使用 `diagnose`。

## 范围与证据

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

## 文档

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

## 卸载与许可证

`./uninstall.sh --dry-run` 预览删除内容；`./uninstall.sh` 只删除项目自有代码与
managed loader，保留 Mihomo、用户服务、配置、凭据、订阅、provider、缓存和
备份。项目使用 [MIT License](LICENSE)。
