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

Machine-readable diagnostics are encoded by the installed `diagnostics.py`
module. Process inspection correlates only same-user `/proc` environment counts
and socket inodes; it never returns environment values, command lines, or remote
addresses. `acceptance.py` supplies both full acceptance and the narrower
`test-url` probe profile, so HTTP/SOCKS checks have one implementation.

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
