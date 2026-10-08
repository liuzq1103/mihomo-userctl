# Architecture and data flow

## v0.6 Codex runtime gate

`mihomoctl codex preflight` uses the four levels in [first-run.md](first-run.md) to decide launch;
`mihomoctl codex` runs the same gate. Mismatched candidates are BLOCKED; incomplete inspection is UNVERIFIED.
Neither launches Codex nor stops existing processes. Installer connectivity, disk loader changes or new CLI
variables cannot prove an old service's route. Local transport should bypass the proxy; remote/model traffic needs real verification.

Public directories hold installation material; private per-user installation is the default, and administrator-shared runtime is an explicitly selected option.

Ordinary shells, explicit terminal proxy entry and a verified CODEX_REMOTE_PAYLOAD hook are distinct
paths; rules select egress after traffic enters Mihomo. Some versions/launch modes reuse persistent
servers: follow [shared-runtime guidance](shared-runtime.md) for Unix sockets and the actual request
process instead of inferring routing from the new CLI environment alone.

The [shared-runtime mode](shared-runtime.md) separates administrator-managed Node/npm/Codex from
per-user identity and Mihomo. Program installation location does not select a user's proxy;
the opted-in process environment and Mihomo routing determine the network path.

## Problem model

```text
ordinary user on a shared server
  -> normal downloads remain on the server direct connection
  -> selected tools explicitly enter the user's local proxy
```

The boundary keeps the proxy endpoint inside the server user account and does
not transparently capture traffic:

```text
ordinary process -> server direct network
opted-in process -> 127.0.0.1:<port> -> user Mihomo -> routing policy
```

## Responsibility matrix

| Owner | Responsibility |
| --- | --- |
| `mihomo-userctl` | Safe entry to the user service; service/listener/authenticated readiness checks; current-Shell and single-child environment boundaries; redacted current-UID process diagnostics; deterministic updates and rollback of its own files; read-only verification of the documented custom-rule layout; evidence-oriented post-install/update checks |
| Mihomo | Proxy protocols, node connections, DNS, routing matches, provider loading, groups and node selection, complete `config.yaml` semantics, Controller API, and runtime traffic |
| systemd | User-service lifecycle, active/enabled state, logs, and process supervision |
| User | Mihomo core version; subscriptions, nodes, providers and private rules; whether to start/enable the service; whether to reopen a terminal or reconnect a long-lived client; whether to edit or apply `config.yaml` |

### Implemented and still not implemented

Since v0.7 the controller **does implement** an independently authenticated loopback
Controller client and a browser dashboard: `controller setup`, `controller status`,
`controller token`, `nodes`, `groups`, `select`, `latency`, `connections`,
`traffic`, `tui`, `ui`/`dashboard`, plus `manual` (convert an automatic group to
manual) and `override` (local JavaScript policy override). See
[nodes and dashboards](control-plane.md) and [TUI and overrides](tui-overrides.md).
All of these require explicit opt-in, do not change direct-by-default shells, and do
not bypass Codex preflight.

The following remain **not implemented**. They are scope boundaries, not backlog items:

- Full configuration subscription import and automatic provider/subscription updates (v0.9 adds explicit node-only import and provider refresh);
- A general YAML editor;
- TUN, transparent proxying and system proxying; system routes are never modified;
- UID-level firewall isolation; authentication is a credential boundary, not network isolation;
- System services and `loginctl enable-linger`;
- Cron or any scheduled auto-update; updates are the explicit `mihomoctl update` command;
- sudo or any privilege-escalation path;
- Automatic core upgrades; `install.sh` and `mihomoctl update` upgrade the control layer only;
- Process termination, including clearing a port held by a process whose ownership cannot be confirmed;
- Private rule generation; `rules status/check` is a read-only checker only.

`mihomoctl init`, `mihomoctl adopt`, `mihomoctl core`,
`mihomoctl geodata`, `mihomoctl run` and `mihomoctl trace` **do not exist today**.
Runtime installation and adoption remain outside this release.

### v0.9 console components

The existing controller is now a compatibility facade over `controller_config`, `controller_api`, `controller_service`, `controller_policy`, `controller_transaction`, `controller_dashboard`, `controller_runtime`, `controller_state`, `controller_subscriptions`, `controller_legacy`, `controller_textual` and `controller_deps`. UI code calls shared services; state holds safe projections and bounded jobs. Bash retains shell/process environment semantics. There is no new daemon or RPC boundary. Historical runtime receipt sets remain frozen before new modules are added. See the [console guide](console.md) for the implemented subset and [acceptance](console-acceptance.md) for outstanding host validation.

## Components

```text
.bashrc managed loader
  -> owner/permission checks
  -> shell.bash: proxy_on/off/status, with_proxy
     -> common.bash: strict config and credential parser

mihomoctl
  -> common.bash
  -> systemctl --user, ss, authenticated curl, journalctl --user

Mihomo
  -> authenticated loopback Mixed listener
  -> user-owned providers, groups, and rules
```

Service state and current-Shell state are independent. `mihomoctl start` moves
the service from down to up; `proxy_on` moves only the current Shell from direct
to proxied. `with_proxy` changes a child process and then disappears.

`mihomoctl exec -- ...` uses the same validated activation function as
`proxy_on`, then replaces the controller process with the requested command.
`mihomoctl direct -- ...` clears the same eight variables before replacement.
Neither command can mutate its parent process environment.

Machine-readable output is serialized by the installed `reporting.py` module;
`diagnostics.py` supplies report data and process inspection. Process inspection correlates only same-user `/proc` environment counts
and socket inodes; it never returns environment values, command lines, or remote
addresses. `acceptance.py` supplies both full acceptance and the narrower
`diagnose url` probe path, so HTTP/SOCKS checks have one implementation.

The control layer ships no desktop Clash/FlClash rules, and the default paths
(`proxy_on`, `mihomoctl exec`, `mihomoctl direct`) generate no Mihomo policy at all.
Since v0.8 the opt-in `mihomoctl override --script` entry point does generate a
`proxy-groups` / `rules` / `rule-providers` candidate, and `--flclash-compat`
adapts a user's own reviewed FlClash-rules script to it; both require an explicit
trusted local script and both validate before saving. That separation prevents
server lifecycle code and PC rule generation from becoming one coupled deployment.

## Three Codex launch paths

```text
terminal: with_proxy codex -> eight proxy variables -> Mihomo
Codex Remote: launcher supplies CODEX_REMOTE_PAYLOAD -> .bashrc hook -> Mihomo
VS Code Remote: Machine http.proxy -> Extension Host starts app-server -> Mihomo
```

These paths are independent. The managed loader must precede Ubuntu's common
non-interactive `.bashrc` return guard. VS Code Remote does not run Shell
functions and must not be assumed to provide `CODEX_REMOTE_PAYLOAD`; it needs
an explicit Machine `http.proxy` when proxying is desired. In the tested
same-version extension, the Codex child received `HTTP_PROXY` and `HTTPS_PROXY`,
not all eight variables managed by the terminal integration.

Environment changes are inherited only at process creation. A stale Codex App
Server or Extension Host can remain direct after configuration is fixed. Restart
only the current user's client connection, then verify the new process
environment, listener socket, and Mihomo logs.

## Trust boundary

The loader validates module ownership and permissions before sourcing code.
Configuration and credentials are parsed as non-executable data with fixed key
whitelists. Unknown or duplicate keys, invalid quoting, wrong endpoints, and
unsafe permissions fail closed.

## Installed versions

Stable launchers resolve `current` once per invocation and load a complete immutable
`generations/<id>` directory. The installer owns the operation lock, transaction
backup, atomic publication and rollback. Metadata records original XDG/startup
paths and file hashes; the updater invokes this same installer. See [updates](update.md).

## v0.7 Control Plane

Use [nodes and dashboards](control-plane.md) to opt into an independently authenticated loopback controller.
See [fixed-link installation](quick-install.md) for bootstrap. These features do not bypass Codex preflight or change direct-by-default shells.
