# 安装后第一次使用

[English](../en/first-run.md) · [安装](setup.md) · [V1 命令与配置契约](v1.md) · [排错](troubleshooting.md)

> **v1.0.1：** 自动 Shell hook 已移除。安装器不写 `.bashrc`，不存在 loader，
> 也不存在 `CODEX_REMOTE_PAYLOAD`。代理接入全部是显式调用。

## 四层状态

| 层级 | 需要的证据 |
| --- | --- |
| `CONTROL_PLANE_INSTALLED` | 控制层可执行、`manager.yaml` 与凭据存在且属主/权限正确 |
| `RUNTIME_LISTENING` | 受管运行时处于目标后端且监听 `127.0.0.1` 的已认证端口 |
| `PROXY_READY` | 带认证的 HTTP 探针成功 |
| `E2E_VERIFIED` | 真实客户端完成一次真实请求 —— **未实测时保持 UNVERIFIED** |

这些是**观测层级**，不是验收结论。它们不能互相推断。特别是：
**就绪通过不等于模型端到端成功。**

## 第一次使用（用户作用域，默认）

不需要 root，不需要 systemd，不需要改任何 Shell 启动文件。

```bash
# 1. 确认控制层可用
mihomoctl version

# 2. 初始化：默认 user 作用域、默认 process 后端
mihomoctl init --core /absolute/path/to/mihomo

# 3. 启动运行时（默认 process 后端）
mihomoctl start

# 4. 七项运行时事实
mihomoctl status

# 5. 代理档案（脱敏）
mihomoctl profile list

# 6. 通用健康检查
mihomoctl health

# 7. 启动一次命令并透传退出码
mihomoctl exec -- curl --head https://example.com/
```

`exec` 在 `execve` 之前会确认本地健康；不通过就**不执行**目标命令。
它只清除八个继承来的代理变量，不修改父 Shell。

## 让后台服务走代理

先在 `manager.yaml` 定义 `bindings.worker`，指定 `adapter: systemd`、
`profile: default` 和既有消费者服务的 `target`。

```bash
mihomoctl integration show worker
mihomoctl integration install worker
```

只写私有 `proxy.env` 与带标记的受管 drop-in，并 reload 自己的 manager。
**绝不** enable / start / stop / restart 第三方单元。
单元是否重启、何时重启，由你自己安排维护窗口。

## 让容器走代理

```bash
# 先在 manager.yaml 定义这些 binding 名称及其 adapter/profile/connect_host。
mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"
mihomoctl integration export cluster-worker --output-dir "$HOME/.config/mihomoctl/export-cluster"
```

**容器内的 `127.0.0.1` 是容器自己的回环，不是宿主机回环。**
必须显式给出可达地址；通配地址永不作为客户端地址输出。
导出产物不会自动部署。

## 终端界面

```bash
mihomoctl tui
mihomoctl tui --plain
```

见[控制台](console.md)。界面的**服务**页就是上面那七项事实的呈现，
**接入**页是代理档案与绑定声明。

## 从 0.9.x 迁移

旧安装必须显式迁移一次：

```bash
mihomoctl migrate --dry-run    # 只读预览
mihomoctl migrate --apply
```

迁移导入旧配置与凭据，**只移除能确证属于本项目的 loader**，保留文件其余字节，
并备份所有被修改的文件。形态自定义或含糊的 loader 一律拒绝，不猜测。
已存在的第三方单元只报告，不停止或删除。

## 常见误解

**"代理起来了，为什么客户端还是连不上？"**

就绪通过 ≠ 运行时正确 ≠ 端到端成功。认证探针只证明那次请求可用。
真实客户端的远端传输和实际回复需要单独验证。本地 Unix socket 与 localhost
连接应直连，不要把所有连接错误都当成远端代理故障。

**"我改了代理，为什么还是旧错误？"**

新的环境变量不会改变已经运行的 CLI、bridge、app-server 或扩展宿主进程。
新 CLI 拥有代理变量，也不证明被复用的旧服务已经代理。
保存工作、正常退出并重连你自己的客户端；不要批量杀进程或删除 socket、登录态和会话。
先看 `mihomoctl status` 的七项，再看 `mihomoctl diagnose process PID`。

**"重启机器后怎么恢复？"**

默认不自动启动，也不设置 linger。需要时执行 `mihomoctl start`。
安装器从不禁用或启用服务。

## English summary

First use needs no root, no systemd and no shell startup file. `mihomoctl init`
creates the managed configuration, credentials, a default profile and one
loopback-only authenticated named mixed listener. `mihomoctl status` reports seven
facts, `mihomoctl health` runs the generic checks, and `mihomoctl exec` injects the
eight proxy variables for one process after confirming local health.

Background services use `mihomoctl integration install NAME`, which writes a private
`proxy.env` and a marked drop-in and reloads only its own manager; restarting the
unit stays your decision. Containers use `mihomoctl integration export`, and a
container's `127.0.0.1` is not the host loopback, so an explicit reachable address
is required.

Migrating from 0.9.x is explicit: `mihomoctl migrate --dry-run` then `mihomoctl migrate --apply`, which
removes only a positively identified project loader and backs up everything it
touches.
