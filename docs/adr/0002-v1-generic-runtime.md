# ADR 0002 — V1 scope, lifecycle and explicit proxy integration

- Status: accepted for v1.0.0.
- Date: 2026-10-11.
- Contract: [architecture-v1.md](../architecture-v1.md).
- Evidence: [design-reference.md](../design-reference.md), [code-audit.md](../code-audit.md).

This decision supersedes conflicting proposals in [architecture-vnext.md](../architecture-vnext.md)
and [ADR 0001](0001-vnext-foundation.md), including exclusion of explicit administrator-managed
TUN and application-specific daemon lifecycle management. Historical evidence in those documents
remains a record of the old architecture.

## Decision

Mihomoctl manages Mihomo lifecycle and proxy configuration. Its shared model is Proxy Profile,
Environment Injection, Runtime Integration and Health Check. The CLI and TUI call one Python
application layer. Workload names belong in examples and declarative bindings.

Default scope is user. System mutations require explicit `--system` and administrator permission;
UID 0 never silently promotes the scope. User configuration follows XDG paths; system configuration
is `/etc/mihomoctl`. The managed system core runs under a dedicated service account.

Authenticated loopback HTTP, SOCKS and Mixed listeners are the default. Profiles reference listener
names and derive ports from the core configuration. TUN is disabled by default and requires explicit
`mihomoctl --system tun enable`; its configuration, capabilities, activation and verification form
one rollbackable transaction. Kernel capability requirements do not by themselves require UID 0;
V1 deliberately authorizes TUN changes only through the administrator-controlled system scope.

Install, update and uninstall do not edit `.bashrc`, `.zshrc`, `.profile`, aliases or functions.
The `CODEX_REMOTE_PAYLOAD` hook is retired. An explicit `migrate --dry-run` / `migrate --apply`
may remove a positively identified project loader, with exact backups and rollback. Ambiguous
or customized blocks are refused. Other startup-file bytes are preserved.

`exec` injects proxy variables into a new child only. Systemd integration installs a private
EnvironmentFile and a marked drop-in; it can reload definitions but never enables, starts, stops
or restarts a consuming third-party unit. Other platforms receive export-only configuration.
Retired Paseo lifecycle commands provide migration guidance and never operate on its daemon.

Authenticated proxy URLs contain secrets. They may be exported to owner-only files and inherited
by the selected process, but environment variables provide no secret isolation. Unit bodies contain
file references, not credential literals. The control-plane secret remains in the generated core
configuration. Documentation must not claim that every EnvironmentFile value is publicly exposed
through D-Bus without evidence for that specific property and read path.

## Consequences

Users explicitly attach each command or service to a profile. Existing processes keep their old
environment until their owner restarts them. The tool reports configuration drift and cannot infer
that a particular application actually used its inherited proxy variables.

All mutations use locks and transactions. Unknown process ownership, unsafe files, invalid
configuration and incomplete health evidence block execution. Only the managed Mihomo runtime
may be stopped. Network cleanup is limited to proven tool-owned state.

Release requires actual Ubuntu 22.04/24.04 systemd, real multiple-UID and isolated TUN acceptance,
independent review, and successful CI on the published commit. Skips and mocks cannot satisfy
these gates. Maintenance SHA256 pins are not upstream signatures.

## 中文摘要

V1 将代理基础设施与 Shell 行为解耦。默认用户作用域；系统变更和 TUN 必须由管理员
显式授权。CLI/TUI 共享 Python 应用层，Profile 引用 Listener 名称，端口只由核心配置
提供。安装、更新和卸载不改启动文件；历史 loader 仅通过显式迁移清理并可回滚。
第三方应用只接收环境或导出配置，其生命周期始终由用户或所属平台管理。带认证的
代理环境文件包含秘密，必须限制权限；环境继承不构成秘密隔离或实际流量代理的证据。
