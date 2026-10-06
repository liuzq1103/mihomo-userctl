# 安装后第一次使用 Codex

[English](../en/first-run.md) · [安装](setup.md) · [故障排查](troubleshooting.md)

安装成功 ≠ HTTP proxy ready ≠ Codex runtime ready ≠ model E2E verified。
先完成个人订阅/配置，确认 Codex 已安装；登录由用户本人完成。
本页描述 v0.6.0。v0.5.0 的启动器只警告旧进程风险，升级后会拒绝不安全或无法验证的启动。
v0.4.0 没有 Codex 专用入口，不能把旧版 `with_proxy codex` 当作新的运行时门禁。

## 四层状态

| 层级 | 含义及证据 |
| --- | --- |
| `CONTROL_PLANE_INSTALLED` | 控制层可加载且配置/凭据校验通过；preflight 不代替安装 receipt 的完整哈希审计 |
| `PROXY_READY` | 用户服务 active、选定端口仅监听 loopback、无认证 HTTP/SOCKS 被拒、认证 HTTP 请求通过 |
| `CODEX_RUNTIME_CLEAN` | 可找到 Codex、待启动环境匹配配置、进程快照完整且已识别候选均匹配 |
| `CODEX_E2E_VERIFIED` | 用户授权后，真实使用入口发出最小模型请求并取得完整回复；自动 preflight 始终记为 UNVERIFIED |

这些是本次观察，不存储为永久认证。单次快照不能保证下一时刻不会出现新的旧环境进程。

## 普通终端的首次检查

```bash
mihomoctl doctor
# 仅当用户已选择启动且配置完成时：
mihomoctl start
mihomoctl codex preflight
mihomoctl codex preflight --json
# 只有 preflight 允许且用户授权真实验收后：
mihomoctl codex
```

服务已运行则无需再启动。`preflight` 会请求配置的公开 HTTPS READY URL（HEAD），检查
HTTP CONNECT 认证拒绝和 SOCKS 无认证拒绝；不发模型请求、不登录、不启动服务。
READY URL 不得含 userinfo、query、fragment 或本地主机，应支持 HEAD 并返回 2xx。
不能联网或尚未获准探测时不执行 preflight，把相关验收记为 UNVERIFIED。

| preflight 退出码 | 状态 | 后续动作 |
| --- | --- | --- |
| 0 | SAFE_TO_LAUNCH | 可以从实际入口进行已授权的 Codex 验收，不能宣称模型已通 |
| 1 | BLOCKED | 已发现服务/监听/认证/HTTP 失败、缺少 Codex 或旧进程环境不匹配；不运行 Codex、不发模型请求 |
| 2 | UNVERIFIED | 配置/依赖/权限/进程检查无法可靠完成；不运行 Codex，不宣称成功 |

检查错误优先于已知阻断：两者并存返回 2，但 `reasons` 保留所有已发现问题。
依赖上游失败而跳过的网络项标记 SKIPPED，不算额外检查错误。
`mihomoctl codex` 每次内部重新运行相同 preflight，只有退出 0 才 exec PATH 中的 Codex。
它不调用 alias/function，不安装程序、不停止旧进程，不提供跳过门禁开关。
启动成功后透传 Codex 自己的退出码；不要把子程序的退出码解释成 preflight 状态。
参数使用 `mihomoctl codex -- resume`；普通非 Bash 终端也可使用此入口。

普通 Shell 默认 direct 是正常状态。报告中的 `invoking_environment` 是调用方环境分类；
`codex.current_environment` 检查的是准备传给新 Codex 的八变量环境，父 Shell 不会被改写。
现有进程采用严格八变量匹配策略，包括 NO_PROXY；即使某个 VS Code 服务仅使用两个变量即可联网，
它也不满足此终端门禁，不能据此断言它的实际模型连接已失败。

## 旧进程阻断与安全恢复

```text
Overall
  BLOCKED
Reason: stale-direct-app-server
  PID=182034 role=app-server proxy_environment=direct
```

PID 仅为虚构示例。direct/inconsistent 的已识别 CLI、helper 或 app-server 均阻断；
没有关联证据时，宁可要求确认，也不猜哪个候选会被复用。
读取失败、PID 变化或活跃同 UID 进程无法分类时为 UNVERIFIED。

1. 保存工作，正常退出或断开自己的旧 Codex 客户端。
2. 运行 `mihomoctl diagnose codex` 查看只读快照，确认是否仍有活跃会话。
3. 再运行 preflight；清除原因后从正确入口重连。

工具不会 kill、pkill、删除 Unix socket、`.codex`、登录态或会话。不要为通过门禁破坏正在工作的会话。
修改 `.bashrc` 只改变磁盘状态，不能追溯修改 OpenCode、Claude Code、Codex 安装 Agent 的进程树，
也不能修改已有 app-server、Extension Host、tmux 或 Notebook。新 CLI 的 8/8 不是旧服务已代理的证据。

## 本地 transport 与远程 transport

```text
CLI → localhost / 127.0.0.1 / ::1 / Unix socket → app-server
    local_transport = DIRECT_EXPECTED

app-server → HTTPS / WSS / other remote transport → remote service
    remote_transport = UNVERIFIED
    model_request = UNVERIFIED
```

`NO_PROXY=localhost,127.0.0.1,::1` 是正确设计；Unix socket 本身不通过 HTTP 代理。
DIRECT_EXPECTED 是本地链路应直连的策略，不能当作本地连通 PASS。
HTTP readiness 不证明远程 WebSocket 或模型成功；看到 WebSocket 报错先识别出错层，不直接归因于 Mihomo。
诊断保留旧 JSON `websocket=UNVERIFIED` 兼容字段，并新增 local_transport/remote_transport/model_request。
不要关闭 TLS 校验或套用未经验证的传输配置。

## diagnosis 与 policy enforcement

`mihomoctl diagnose codex [--json]` 是离线深度排查入口，整体仍为 UNVERIFIED、退出 2；
它不发网络请求，也不决定启动。`mihomoctl codex preflight [--json]` 是启动策略判断，返回 0/1/2。
二者只报告当前 UID 候选的 PID、角色和环境分类，不打印完整 argv、环境、订阅或凭据。
preflight 复用 `mihomo-userctl.diagnostics/v1`，command 为 `codex-preflight`；
launch_safe 是布尔值，proxy/codex 是检查分类，checks 是实际探测证据，reasons 是稳定原因代码，
levels 是上述四层状态。配置/检查错误也返回相同核心字段；Python 或受信任模块不可用时，
返回只含 schema、command、overall、launch_safe、reasons、error 的最小错误对象。

匹配范围是名称或可执行文件为 codex，以及可识别的 node/bash/sh Codex 脚本入口。
任意改名二进制、自定义嵌入式服务可能无法识别。不能自动证明 Unix socket 对端因果关系、复用关系、
最终代理节点或真实远程请求。SAFE_TO_LAUNCH 只表示这次已实现检查全部通过。

## Remote、VS Code 与安装 Agent

已验证 Remote hook 可按既有方式连接；VS Code 使用[独立集成](vscode-remote.md)。
这些入口以及 `with_proxy`/`exec` 不会自动执行 Codex 门禁；安装后的 Codex 验收必须先运行 preflight，
不能用裸 `codex` 作为 post-install 验收捷径，也不能绕过阻断去试模型。
本版本不把门禁加到通用 `.bashrc` hook，以免影响非 Codex 命令和已有远程连接。

安装 Agent 自己能够联网不是目标 Codex 的验收证据。先登录，再在已授权范围内通过实际使用的客户端
发送最小消息，确认完整回复，另行记录真实路由证据。交付分别报告四层状态及待填订阅、登录、重连事项。

## v0.7 Control Plane

需要查看或切换节点时，按[节点管理与面板](control-plane.md)启用独立认证 loopback controller。
快速安装入口见[固定链接安装](quick-install.md)。这些功能不绕过 Codex preflight，也不改变普通 Shell 默认直连。
