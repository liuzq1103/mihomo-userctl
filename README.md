# mihomoctl

**Mihomo 生命周期与代理配置管理 CLI，支持个人用户和服务器管理员，
提供显式的代理接入与验证。**

[English](README.en.md) · [安装](INSTALL.md) · [V1 命令与配置契约](docs/zh-CN/v1.md) ·
[中文文档](docs/zh-CN/README.md)

v1.0.0 的领域模型是四层：**Proxy Profile + Environment Injection + Runtime
Integration + Health Check**。核心不含任何具体工具的专属代码。

## 先记住这三件事

1. **安装器不写任何 Shell 启动文件。** 不修改 `.bashrc` / `.zshrc` / `profile`，
   不注册别名或函数。首次使用与登录态无关。
2. **环境变量在进程创建时继承，不是持续策略。** 已运行的进程不会因为配置变化而
   更新；本工具也不会替你重启任何第三方进程。
3. **本工具不管理第三方应用生命周期。** systemd drop-in、env-file、容器与 CI
   配置只导出或只写入，绝不代你启停别人的单元。

## 为什么需要它

- 远程服务器上的程序连不上：远程进程需要自己的、显式的代理接入。
- 多人共用服务器：每个 Linux 账户管理自己的配置、凭据和端口，不动系统全局代理。
- 只想让部分命令走代理：用 `mihomoctl exec` 为那一个进程设置变量。
- 后台服务要走代理：用 `mihomoctl integration install` 写配置，重启由你自己安排。
- 代理明明起来了却仍报错：按 core、controller、listener、config、mode、TUN
  七项分别定位，而不是笼统地说"代理坏了"。

## non-goals

- **不管理第三方 daemon 生命周期**；旧的应用专属命令已退役，见[退役映射](docs/zh-CN/v1.md#13-旧命令退役)。
- **不做桌面 GUI**；浏览器面板只是本地可选入口。
- **不做通用 YAML editor**。
- **不做无 root 的强 UID 网络隔离**；认证是凭据边界，不等于跨 UID 防火墙隔离。
- **环境变量不是网络强制策略**。
- **就绪通过不等于模型端到端成功**。
- **不接管用户 crontab**，不做覆盖式自动更新。
- **不终止无法确认归属的进程**，包括为了腾出端口。

## 快速开始

```bash
# 1. 安装控制层（见 INSTALL.md）
mihomoctl version

# 2. 首次初始化：默认 user 作用域，默认 process 后端，不需要 root
mihomoctl init --core /absolute/path/to/mihomo

# 3. 启动运行时（默认 process 后端）
mihomoctl start

# 4. 看状态：固定七项事实
mihomoctl status

# 5. 看代理档案（脱敏）
mihomoctl profile list

# 6. 让一个命令走代理
mihomoctl exec -- curl --head https://example.com/
```

完整步骤见 [INSTALL.md](INSTALL.md) 与[安装指南](docs/zh-CN/setup.md)。

## 作用域

| | 用户（默认） | 系统 |
| --- | --- | --- |
| 选择 | 缺省 | 必须显式 `--system` |
| 后端 | 默认 `process` | 必须 `systemd` |
| root | 不需要 | 需要 UID 0 |
| TUN | **不可用** | 仅 `sudo mihomoctl --system tun enable` |

`--user` 与 `--system` 互斥。UID 0 **不会**被自动提升：root 不加 `--system`
可读取用户路径，但变更操作会被拒绝。工具**不自行提权、不使用 sudo**。

## 常用命令

```text
mihomoctl init --core PATH [--config FILE] [--port PORT] [--allow-non-loopback ADDRESS]
mihomoctl [--user|--system] start | stop | restart
mihomoctl [--user|--system] status [--json]
mihomoctl logs [--lines N] [--follow]
mihomoctl doctor [--json]
mihomoctl config validate [--file FILE] [--profile NAME] | check

mihomoctl service install | start | stop | restart | status
mihomoctl service uninstall [--dry-run]
mihomoctl profile list | show NAME | validate NAME | set-default NAME
mihomoctl exec [--profile NAME | --binding NAME] -- COMMAND [ARGS...]
mihomoctl direct -- COMMAND [ARGS...]
mihomoctl env show [--profile NAME | --binding NAME] [--reveal] [--json]
mihomoctl env export [--profile NAME | --binding NAME] (--output PATH | --reveal)

mihomoctl integration list | show NAME | check NAME
mihomoctl integration export NAME | install NAME | remove NAME
mihomoctl health check [--profile NAME | --binding NAME] [--egress-url URL] [--json]
mihomoctl tun status | enable | disable        # enable/disable 仅 --system

mihomoctl core install --version VERSION [--sha256 DIGEST]
mihomoctl core update --version VERSION [--sha256 DIGEST] [--dry-run]
mihomoctl version
mihomoctl migrate [--dry-run] [--apply] [--core PATH] [--remove-loader] [--no-import]
mihomoctl rollback BACKUP
mihomoctl update

# 保留的控制面能力
mihomoctl controller status | tui | nodes | groups | select GROUP NODE
mihomoctl connections | traffic | latency NODE | subscription preview | apply
mihomoctl rules status | check
```

完整参数以 [docs/zh-CN/v1.md](docs/zh-CN/v1.md) 为准。

## `status` 固定报告什么

core、controller、**每一个** listener、生效配置、proxy layer、Mihomo 路由模式、
TUN、错误。缺任何一项都显示为 `unknown` / `UNVERIFIED`；数据不完整**不会**
被渲染成正常。

## 健康检查与证据

`mihomoctl health` 只针对运行时，不针对任何工作负载。检查项是
`PASS` / `FAIL` / `UNVERIFIED` / `SKIPPED`，并同时标注证据等级
`confirmed` / `inferred` / `unavailable`。

每次输出都附带固定边界声明，其中包括：

- 就绪通过**不等于**模型端到端成功；
- 观察到监听**不等于**证明监听归属；
- 认证探针通过**不等于**证明流量经远端节点；
- 节点选择**不等于**证明某一次请求；
- 未观察到 socket **不等于**直连。

外部出口检查须显式指定 `health check --egress-url URL`；其结果只针对该次目标探测，不能证明应用实际使用代理，也不作为本地启动成功门禁。

## 后台服务与容器

先在 `manager.yaml` 的 `bindings` 中定义下例名称及其 `adapter`、`profile`，
容器接入还需声明可达的 `connect_host`；名称不代表 adapter 类型。

```bash
# 只写配置，不重启
mihomoctl integration install worker
mihomoctl integration show worker

# 只导出，永不自动部署
# 可达地址在 manager.yaml 的 connect_host 里声明，不在命令行上传
mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"
mihomoctl integration export cluster-worker --output-dir "$HOME/.config/mihomoctl/export-cluster"
```

**容器内的 `127.0.0.1` 是容器自己的回环，不是宿主机回环。**
导出必须显式给出可达地址，通配地址永不作为客户端地址输出。

## 终端界面

```bash
mihomoctl tui
mihomoctl tui --plain          # 无 Textual 时的编号菜单
```

页面：首页、节点、订阅、接入、更多（连接 / 规则 / 日志 / 提供商 / 诊断 / 服务）。
**接入**页展示代理档案、绑定声明与环境注入的固定边界；**服务**页展示上面那七项
运行时事实。界面只渲染已计算的状态，不自建 readiness。详见
[控制台](docs/zh-CN/console.md)。

## 详细文档

- [安装 · Installation](INSTALL.md)
- [V1 命令与配置契约](docs/zh-CN/v1.md) · [English](docs/en/v1.md)
- [V1 架构与实现契约](docs/architecture-v1.md)
- [ADR 0002：V1 通用运行时与退役第三方生命周期](docs/adr/0002-v1-generic-runtime.md)
- [设计参考与边界推导](docs/design-reference.md)
- [代码审计](docs/code-audit.md)
- [安全模型](docs/zh-CN/security.md)
- [安装指南](docs/zh-CN/setup.md)
- [首次使用](docs/zh-CN/first-run.md)
- [验收与证据](docs/zh-CN/acceptance.md)
- [故障排查](docs/zh-CN/troubleshooting.md)
- [节点管理与面板](docs/zh-CN/control-plane.md)
- [私有自定义规则](docs/zh-CN/rules.md)
- [更新与回滚](docs/zh-CN/update.md)
- [已归档：Paseo 后台注入](docs/zh-CN/paseo.md)

## 许可证

[MIT](LICENSE)。本项目是独立、非官方项目，与 MetaCubeX、Mihomo 和 Mihoro 均无隶属关系。
