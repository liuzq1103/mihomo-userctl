# Architecture and data flow

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

The controller does not implement a Controller client, dashboard, subscription
manager, provider downloader, general YAML editor, TUN, transparent/system
proxying, UID firewall isolation, system service, linger, cron, sudo, automatic
core upgrades, process termination, or private-rule generation.

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

The controller does not generate Mihomo policy and does not contain desktop
Clash/FlClash rules. That separation prevents server lifecycle code and PC rule
generation from becoming one coupled deployment.

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
