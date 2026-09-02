# mihomo-userctl

`mihomo-userctl` is a small, security-focused control and Bash integration
layer for an existing per-user [Mihomo](https://github.com/MetaCubeX/mihomo)
service on Linux.

It is designed for shared research servers where normal shells and large data
downloads must remain direct, while selected commands may explicitly use an
authenticated, loopback-only Mihomo listener.

> This is an independent, unofficial project. It is not affiliated with
> MetaCubeX, Mihomo, or [Mihoro](https://github.com/spencerwooo/mihoro).

[简体中文](README.zh-CN.md) · [Documentation languages](docs/README.md)

## Problem solved

On a multi-user server, one ordinary user may need a personal proxy for Codex
Remote, VS Code Remote, Git, or a few selected commands. That must not silently
proxy the user's large downloads, affect another account, or require a server
administrator. Global proxy exports and transparent proxying are too broad for
this use case.

`mihomo-userctl` makes the boundary explicit:

```text
normal shell / axel / S3 / large dataset
  -> server direct connection

with_proxy / proxy_on / selected remote tooling
  -> authenticated 127.0.0.1:<per-user-port>
  -> user-level Mihomo
  -> routing policy decides DIRECT or a proxy node
```

The implementation is kept outside `.bashrc` so it can be tested and audited:

```text
~/.local/bin/mihomoctl
~/.local/share/mihomo-userctl/{common.bash,shell.bash,completion.bash}
~/.config/mihomo/{mihomo-shell.conf,client.env}
```

The ordinary-shell invariant is simple: **direct by default**. Merely starting
Mihomo never changes the current shell's proxy environment.

## Project boundary

This repository contains only the server-side user controller and Shell
integration. It does not contain PC Clash/FlClash Merge rules or rule-generation
scripts. Keep desktop rule generation in a separate repository so the two
deployment surfaces cannot be confused.

## Who it is for

The primary use case is one ordinary account on a multi-user Linux server. For
example, a researcher wants their own Codex Remote, VS Code Remote, Git, or a
few selected commands to use a personal subscription, without changing another
user's environment and without sending their own `axel`, S3, or large dataset
downloads through that subscription.

It also fits a single-user server when opt-in proxying and direct-by-default
Shells are desired. It is not a solution for:

- a server-wide transparent proxy or organization-wide gateway;
- strict access isolation between Linux UIDs (that also requires administrator
  firewall policy);
- machines without Bash and a working systemd user manager;
- desktop Clash/FlClash Merge, TUN, system proxy, or route management;
- unattended startup, automatic Mihomo upgrades, or subscription lifecycle.

Only the installing account's home files and `systemctl --user` service are in
scope. Other accounts, unknown listeners, and unrelated SSH sessions are not.

## How it works

1. Mihomo runs as the current user and exposes one authenticated Mixed listener
   on `127.0.0.1:<per-user-port>`.
2. `mihomoctl` validates non-executable configuration, controls only the named
   user service, checks the listener, performs authenticated readiness, and
   reads only that user unit's journal.
3. `shell.bash` clears eight standard proxy variables on load. `proxy_on` sets
   them only after permission, endpoint, service, listener, and authentication
   checks; `with_proxy` performs the same work in a child Shell.
4. A short managed `.bashrc` loader verifies module ownership and permissions.
   Ordinary-load failure stays direct; the configured Codex compatibility path
   fails closed.
5. Once a process reaches Mihomo, the user's own rules decide between `DIRECT`
   and proxy nodes. The controller never rewrites those rules.

See [architecture and data flow](docs/en/architecture.md) for the trust boundary.

## Requirements

- Linux with Bash 5+
- a working `systemd --user` manager
- an existing `mihomo.service`
- an authenticated Mixed listener bound only to `127.0.0.1`
- `curl`, `ss`, `journalctl`, `stat`, `awk`, `grep`

The v0.1 series does not download Mihomo, subscriptions, geodata, or a web
dashboard. Start with the [complete Mihomo setup tutorial](docs/en/setup.md) if the
Mihomo service is not installed yet.

It also does not generate Clash/Mihomo routing rules or desktop-client Merge
files. Keep those policy-generation tools in their own repository; this
project only controls the server user's existing service and shell environment.

## Install

### Lowest-effort guided setup

For a fresh server, copy the
[generic coding-agent installation prompt](docs/en/agent-install-prompt.md) into
an agent that can read files, run terminal commands, use SSH when needed, and
pause for your approval. A chat-only model cannot execute the installation; it
can only explain the manual steps. The prompt requires a read-only audit and a
complete plan before any modification, while sensitive values remain on the
target machine and outside the conversation. Making the installer agent-neutral
does not change the installation task: the prompt still configures and validates
the Codex Remote compatibility hook described below.

### Auditable command-line setup

There is no default port. Before configuring Mihomo, ask the installer for a
currently unused candidate and review it:

```bash
PROXY_PORT=$(./install.sh --suggest-port)
printf 'candidate=%s\n' "$PROXY_PORT"
ss -lnt "sport = :$PROXY_PORT"
```

The helper searches `20000-29999`, starting from a UID-derived position. It
does not reserve the result. Users on the same server share one loopback
namespace, so each user must select a different port, coordinate locally, and
recheck immediately before binding. Listener authentication prevents casual
use; it does not make duplicate port bindings possible.

After the same port is configured in Mihomo and `client.env`, install the
control layer explicitly:

```bash
./install.sh --dry-run --port "$PROXY_PORT"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
```

Re-running is idempotent. An update preserves `client.env` and refuses a
conflicting port. Before writing, it records every managed file in a mode-700
transaction backup; a failed final `doctor` restores the previous active files
automatically. It never enables or starts the user service.

## Daily use

```bash
mihomoctl start       # start service; current shell remains direct
mihomoctl status
mihomoctl doctor

with_proxy curl https://github.com
with_proxy git clone https://github.com/example/project.git

proxy_on              # proxy the current shell explicitly
proxy_status
proxy_off

mihomoctl stop        # service lifecycle only
```

Large downloads remain direct when run normally:

```bash
axel -n 10 'https://example.org/large-dataset'
```

## Security properties

- clears upper- and lower-case proxy variables when a shell module loads;
- never sources or evaluates user configuration or credential files;
- requires `mihomo-shell.conf` and `client.env` to be owner-only mode `600`;
- validates HTTP and SOCKS5H URLs against the configured loopback port;
- passes proxy credentials through a child environment, not command arguments;
- rejects group/other-writable modules and module directories;
- does not use TUN, a controller, system proxy settings, routing changes, root,
  linger, cron, or a system-level service;
- stops only the named user service and never kills a port owner.

See [SECURITY.md](SECURITY.md) and the [security model](docs/en/security.md).

## Commands

```text
mihomoctl start
mihomoctl stop
mihomoctl restart
mihomoctl status
mihomoctl ready
mihomoctl doctor
mihomoctl logs [--lines N] [--follow]
mihomoctl version
```

Shell functions:

```text
proxy_on  proxy_off  proxy_status  with_proxy
```

The legacy `mihomo_start`, `mihomo_stop`, `mihomo_restart`, `mihomo_status`, and
`mihomo_logs` wrappers remain available throughout the 0.x series.

Exit status is stable: `0` success/healthy, `1` runtime or readiness failure,
and `2` usage, configuration, permission, or dependency failure.

## Configuration

`~/.config/mihomo/mihomo-shell.conf` contains no secret:

```ini
MIHOMO_SERVICE=mihomo
MIHOMO_PORT=PORT_SELECTED_BY_USER
MIHOMO_READY_URL=https://example.com/
MIHOMO_READY_TIMEOUT=30
MIHOMO_STOP_TIMEOUT=5
```

`~/.config/mihomo/client.env` contains the authenticated local endpoints and
must be mode `600`. These files are parsed with a fixed key whitelist; they are
not Shell programs.

## Codex Remote and VS Code Remote

The locally verified `CODEX_REMOTE_PAYLOAD` compatibility hook remains the
fail-closed opt-in path for Codex Remote launchers that actually supply it. The
installer now places the managed loader before Ubuntu's common non-interactive
`.bashrc` return guard and relocates an older managed block when upgrading.
Because a running process cannot acquire environment changes retroactively,
reconnect only the current user's Codex client after installation instead of
reusing an older App Server.

VS Code Remote is a separate launch path: its Extension Host does not execute
`with_proxy`, and callers must not assume it supplies `CODEX_REMOTE_PAYLOAD`.
When the remote Codex extension needs the proxy, configure the server-side VS
Code Machine `http.proxy` explicitly and protect the authenticated setting with
mode `600`. This can affect other remote extensions that honor the same VS Code
setting, but ordinary SSH shells, `axel`, and S3 downloads remain direct. See
the [recommended VS Code Remote configuration](docs/en/vscode-remote.md).

## Uninstall

```bash
./uninstall.sh --dry-run
./uninstall.sh
```

Uninstall removes only project-owned code and the managed `.bashrc` loader. It
preserves Mihomo, its service, configuration, credentials, subscription cache,
provider cache, and documentation.

## Design inspiration

Mihoro demonstrated the value of a configuration-driven, rootless, per-user
CLI that presents consistent `systemctl --user` commands. `mihomo-userctl`
adopts those interface ideas but deliberately keeps a narrower scope and a
different security model. It does not copy Mihoro's Rust implementation and
does not use its `eval $(... proxy export)` integration. The detailed boundary
is documented in [the Mihoro inspiration note](docs/en/mihoro-inspiration.md).

## Documentation

- [Install Mihomo and configure the complete stack](docs/en/setup.md)
- [Copyable coding-agent installation prompt](docs/en/agent-install-prompt.md)
- [Recommended VS Code Remote configuration](docs/en/vscode-remote.md)
- [Architecture and data flow](docs/en/architecture.md)
- [Security model](docs/en/security.md)
- [Troubleshooting](docs/en/troubleshooting.md)

## License

MIT
