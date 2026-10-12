# First use after installation

[English](first-run.md) · [Setup](setup.md) · [V1 contract](v1.md) · [Troubleshooting](troubleshooting.md)

> **v1.0.1:** the automatic shell hook has been removed. The installer writes no
> `.bashrc`, there is no loader, and there is no `CODEX_REMOTE_PAYLOAD`. All proxy
> access is an explicit invocation.

## Four layers of observation

| Layer | Evidence required |
| --- | --- |
| `CONTROL_PLANE_INSTALLED` | the control layer runs, and `manager.yaml` plus credentials exist with the right owner and mode |
| `RUNTIME_LISTENING` | the managed runtime is on its target backend and listening on an authenticated `127.0.0.1` port |
| `PROXY_READY` | an authenticated HTTP probe succeeds |
| `E2E_VERIFIED` | a real client completed a real request — **stays UNVERIFIED until actually measured** |

These are observation layers, not acceptance conclusions, and they do not imply
one another. In particular: **readiness passing is not model end-to-end success.**

## First use (user scope, default)

No root, no systemd, no shell startup file to change.

```bash
# 1. Confirm the control layer
mihomoctl version

# 2. Initialize: default user scope, default process backend
mihomoctl init --core /absolute/path/to/mihomo

# 3. Start the runtime (default process backend)
mihomoctl start

# 4. The seven runtime facts
mihomoctl status

# 5. Proxy profiles (redacted)
mihomoctl profile list

# 6. Generic health check
mihomoctl health

# 7. Run one command and pass its exit code through
mihomoctl exec -- curl --head https://example.com/
```

`exec` confirms local health before `execve`; if the gate fails, the target command
is **not executed**. It clears only the eight inherited proxy variables and never
changes the parent shell.

## Background services

Define `bindings.worker` in `manager.yaml` first, with `adapter: systemd`,
`profile: default` and the existing consumer unit's `target`.

```bash
mihomoctl integration show worker
mihomoctl integration install worker
```

Only a private `proxy.env` and a marked drop-in are written, followed by a reload
of its own manager. It **never** enables, starts, stops or restarts a third-party
unit. When and whether to restart it is your decision and your maintenance window.

## Containers

```bash
# Define these binding names and their adapter/profile/connect_host in manager.yaml first.
mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"
mihomoctl integration export cluster-worker --output-dir "$HOME/.config/mihomoctl/export-cluster"
```

**`127.0.0.1` inside a container is the container's own loopback, not the host's.**
An explicitly reachable address is required, and a wildcard address is never
emitted as a client address. Exports are not deployed automatically.

## Terminal console

```bash
mihomoctl tui
mihomoctl tui --plain
```

See [console](console.md). The **service** page is the presentation of those seven
runtime facts; the **access** page shows proxy profiles and binding declarations.

## Migrating from 0.9.x

Existing installations need one explicit migration:

```bash
mihomoctl migrate --dry-run    # read-only preview
mihomoctl migrate --apply
```

Migration imports the old configuration and credentials, **removes only a
positively identified project loader**, preserves every other byte, and backs up
every file it modifies. A customized or ambiguously shaped loader is refused
rather than guessed. Existing third-party units are reported, never stopped or
removed.

## Common misunderstandings

**"The proxy is up, so why does my client still fail?"**

Readiness ≠ runtime correctness ≠ end-to-end success. An authenticated probe only
proves that one request worked. Real client transport and an actual reply need
separate verification. Local Unix sockets and localhost connections should be
direct; do not read every connection error as a remote proxy failure.

**"I changed the proxy, so why is the error still the old one?"**

New environment variables do not change an already-running CLI, bridge,
app-server or extension host. A new CLI owning the proxy variables does not prove
that a reused old service is proxied. Save your work, exit normally and reconnect
your own client; do not mass-kill processes or delete sockets, sessions or logins.
Start with the seven facts in `mihomoctl status`, then
`mihomoctl diagnose process PID`.

**"How do I recover after a reboot?"**

Nothing starts automatically and linger is never set. Run `mihomoctl start` when
you need it. The installer never enables or disables the service.

## 中文摘要

首次使用不需要 root、不需要 systemd，也不需要修改任何 Shell 启动文件。
`mihomoctl init` 创建受管配置、凭据、默认 profile 和一个仅回环、已认证的命名
mixed listener；`mihomoctl status` 报告七项运行时事实，`mihomoctl health` 执行通用
检查，`mihomoctl exec` 在确认本地健康后为一个进程注入八个代理变量。

后台服务用 `mihomoctl integration install NAME`，只写私有 `proxy.env` 与带标记的
drop-in 并 reload 自己的管理器，是否重启由你决定。容器用 `mihomoctl integration export`；
容器内的 `127.0.0.1` 不是宿主机回环，必须显式给出可达地址。

从 0.9.x 迁移是显式的：`mihomoctl migrate --dry-run` 再 `mihomoctl migrate --apply`，只移除能确证属于
本项目的 loader，并备份所有被修改的文件。
