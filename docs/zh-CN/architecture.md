# 架构与数据流

## v0.6 Codex 运行时门禁

`mihomoctl codex preflight` 按 [first-run.md](first-run.md) 的四层状态决定是否允许启动，
`mihomoctl codex` 内部执行同一门禁。旧候选进程环境不匹配为 BLOCKED；检查不完整为 UNVERIFIED，
均不启动、不停止任何旧进程。安装 Agent 联网、磁盘 loader 更新或新 CLI 的变量不证明旧服务已代理。
本地 transport 应直连，远程 transport/模型请求仍需独立实测。

公共目录只存放安装材料，默认安装到各用户私有目录；管理员共享运行时仅为明确选择的可选模式。

普通 Shell、显式终端代理和经验证的 CODEX_REMOTE_PAYLOAD hook 是不同入口；规则仅决定
进入 Mihomo 后的出站。CLI 可在某些版本/启动方式下复用长期服务，应按
[共享运行时规范](shared-runtime.md)追踪 Unix socket 与实际请求进程，不能只看新 CLI 的环境。

多用户部署可采用[共享运行时规范](shared-runtime.md)：管理员维护公共 Node/npm/Codex，
每个用户独立维护身份状态与 Mihomo。程序安装位置不决定请求使用哪个用户的代理；
当前用户选择的子进程环境及 Mihomo 路由共同决定网络路径。

## 问题模型

```text
共享服务器普通用户
  ├─ 普通 Shell 与大型下载继续服务器直连
  └─ 明确选择的工具进入该用户本地代理
```

本项目不透明截获流量：

```text
普通进程 -> 服务器直连网络
选择代理的进程 -> 127.0.0.1:<端口> -> 用户 Mihomo -> 路由策略
```

## 责任矩阵

| 主体 | 责任 |
| --- | --- |
| `mihomo-userctl` | 用户服务的安全入口；service、Listener 和认证 readiness；当前 Shell 与单个子进程的环境边界；当前 UID 的脱敏进程诊断；自身文件的确定性更新与回滚；文档约定自定义规则布局的只读检查；安装和更新后的证据化检查 |
| Mihomo | 代理协议、节点连接、DNS、路由匹配、provider 加载、策略组与节点选择、完整 `config.yaml` 语义、Controller API 和运行时流量 |
| systemd | 用户服务生命周期、active/enabled 状态、日志和进程监督 |
| 用户 | Mihomo 核心版本；订阅、节点、provider 与私有规则；是否启动或 enable 服务；是否重开终端或重连长期客户端；是否修改或应用 `config.yaml` |

### 已实现与仍不实现

自 v0.7 起，控制器**已经实现**独立认证的 loopback Controller 客户端与浏览器面板：
`controller setup`、`controller status`、`controller token`、`nodes`、`groups`、
`select`、`latency`、`connections`、`traffic`、`tui`、`ui`/`dashboard`，
以及 `manual`（自动组转手动组）与 `override`（本地 JavaScript 策略覆写）两条入口。
详见[节点管理与面板](control-plane.md)与[TUI 与覆写](tui-overrides.md)。
这些能力都需显式启用，不改变普通 Shell 默认直连，也不绕过 Codex preflight。

仍然**不实现**的部分属于明确的范围边界，不是待办项：

- 完整配置订阅导入与自动订阅/provider 更新（v0.9 增加显式节点导入与 Provider 刷新）；
- 通用 YAML 编辑器；
- TUN、透明代理与系统代理，不修改系统路由；
- UID 级防火墙隔离；认证是凭据边界，不是网络隔离；
- system service 与 `loginctl enable-linger`；
- cron 或任何自动更新调度；更新是显式触发的 `mihomoctl update`；
- sudo 与任何提权路径；
- 自动核心升级；`install.sh` 与 `mihomoctl update` 只升级控制层，不升级 Mihomo 核心；
- 进程终止，包括为了腾出端口而清理无法确认归属的进程；
- 私有规则生成；`rules status/check` 只是只读检查器。

`mihomoctl init`、`mihomoctl adopt`、`mihomoctl core`、
`mihomoctl geodata`、`mihomoctl run`、`mihomoctl trace` **当前不存在**。
运行时安装与 adoption 仍不属于本版本范围。

### v0.9 控制台分层

原 Controller 保留兼容 facade，分离 `controller_config`、`controller_api`、`controller_service`、`controller_policy`、`controller_transaction`、`controller_dashboard`、`controller_runtime`、`controller_state`、`controller_subscriptions`、`controller_legacy`、`controller_textual` 和 `controller_deps`。UI 调用共享服务，State 只持有安全投影与有界任务；Bash 保留 Shell/子进程环境边界，不增加 daemon/RPC。先冻结历史运行时收据集合，再新增 generation 模块。已实现范围见[控制台指南](console.md)，真实主机验收见[验收文档](console-acceptance.md)。

## 组件职责

```text
.bashrc managed loader
  └─ 校验所有者和权限后 source shell.bash
       ├─ proxy_on / proxy_off / proxy_status / with_proxy
       └─ common.bash
            ├─ 白名单解析 mihomo-shell.conf
            ├─ 白名单解析 client.env
            ├─ 权限与 endpoint 校验
            └─ service/listener/readiness 公共检查

mihomoctl
  └─ common.bash
       ├─ systemctl --user mihomo
       ├─ ss 检查 127.0.0.1:<port>
       ├─ curl 认证 readiness
       └─ journalctl --user
```

`.bashrc` 只负责建立可信边界，不包含服务管理实现。即使 Shell 集成损坏，用户
仍可直接运行 `~/.local/bin/mihomoctl doctor`，从而避免“排错工具本身依赖损坏
的 `.bashrc`”这一循环依赖。

## 两套独立状态

服务状态：

```text
down ── mihomoctl start ──> up
 up  ── mihomoctl stop  ──> down
```

当前 Shell 状态：

```text
direct ── proxy_on  ──> proxied
proxied ─ proxy_off ──> direct
```

`mihomoctl exec -- ...` 复用 `proxy_on` 的同一个校验与导出函数，随后用目标命令替换
控制器进程；`mihomoctl direct -- ...` 在替换前清除同一组八变量。两者都无法修改父进程环境。

已安装的 `reporting.py` 集中序列化机器输出，`diagnostics.py` 提供报告数据与同 UID
`/proc` 检查，只关联环境变量数量与
socket inode，不返回环境值、命令行或远端地址。`acceptance.py` 同时提供完整验收和较窄的
`diagnose url` 探针路径，使 HTTP/SOCKS 探针只有一套实现。

两者不会隐式联动，唯一例外是兼容包装器 `mihomo_stop` 会先 `proxy_off`，防止
当前 Shell 留下指向已停止端口的无效环境变量。

## 一条普通下载的路径

```text
axel → 服务器网络接口 → 目标站点
```

只要 Shell 为 direct，Mihomo 即使正在监听也不会自动截获流量，因为本项目不
使用 TUN、透明代理或路由修改。

## 一条 with_proxy 命令的路径

```text
父 Shell（direct）
  └─ 子 Shell：加载经过校验的本地凭据
       └─ command → 127.0.0.1:<port> → Mihomo → 规则决定 DIRECT 或代理节点
  └─ 子 Shell退出，父 Shell仍为 direct
```

默认路径（`proxy_on`、`mihomoctl exec`、`mihomoctl direct`）不生成任何策略。
自 v0.8 起，显式启用的 `mihomoctl override --script` 会生成
`proxy-groups` / `rules` / `rule-providers` 候选，`--flclash-compat` 用于适配用户
自己审阅过的 FlClash-rules 脚本；两者都要求显式指定可信本地脚本，并在保存前校验。
本项目只决定程序是否进入 Mihomo。任何数据集或科研站点的
专属规则都应留在用户自己的 Mihomo 配置中，而不是进入公共控制层。

## 三种 Codex 启动路径

```text
终端：with_proxy codex → 继承八个代理变量 → Mihomo
Codex Remote：远程启动器提供 CODEX_REMOTE_PAYLOAD → .bashrc hook → Mihomo
VS Code Remote：Machine http.proxy → Extension Host 启动 Codex app-server → Mihomo
```

三条路径彼此独立。Ubuntu 的 `.bashrc` 常在非交互 Shell 中提前 `return`，所以
managed loader 必须位于该 guard 之前。VS Code Remote 不执行 Shell 函数，也
不应假定它会提供 `CODEX_REMOTE_PAYLOAD`；需要单独配置 Machine `http.proxy`。
当前同版扩展的实机行为是把 `HTTP_PROXY`、`HTTPS_PROXY` 传给 Codex 子进程，
而不是导出终端使用的全部八个变量。

环境变量只在创建进程时继承。旧 Codex App Server 或 Extension Host 即使在
配置修复后仍可能保持 direct，必须重启当前用户自己的客户端连接，再以新进程
的环境、到 Listener 的 socket 和 Mihomo 日志完成验收。

## 文件信任模型

- `.bashrc` loader 在 source 前检查 `shell.bash` 和父目录；
- `shell.bash` 在 source 前再次检查 `common.bash`；
- 控制器独立检查 `common.bash`；
- 配置和凭据只作为文本解析；
- 未知字段、重复字段、非法引号、非法 URL 或权限均导致 fail closed。

## 安装版本

固定启动器每次调用只解析一次 `current`，加载完整的 `generations/<id>` 版本目录。
安装器统一负责操作锁、事务备份、原子发布及回滚；元数据记录原 XDG/启动路径和文件哈希，
更新器调用同一安装器。详见[更新机制](update.md)。

## v0.7 Control Plane

需要查看或切换节点时，按[节点管理与面板](control-plane.md)启用独立认证 loopback controller。
快速安装入口见[固定链接安装](quick-install.md)。这些功能不绕过 Codex preflight，也不改变普通 Shell 默认直连。
