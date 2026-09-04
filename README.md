# mihomo-userctl

`mihomo-userctl` is a small control, process-entry, and acceptance layer for an
existing per-user [Mihomo](https://github.com/MetaCubeX/mihomo) service on Linux.
It is built for shared servers, remote development, and research computing:
ordinary shells stay direct, while a user explicitly opts selected commands or
processes into an authenticated loopback listener.

It is not another Mihomo client. It does not manage subscriptions, nodes, DNS,
general routing configuration, or runtime traffic. It uses no root privileges
and changes neither other users nor system-wide networking.

> This is an independent, unofficial project. It is not affiliated with
> MetaCubeX, Mihomo, or [Mihoro](https://github.com/spencerwooo/mihoro).

[简体中文](README.zh-CN.md) · [Documentation languages](docs/README.md)

## Boundary

```text
ordinary shell / large download ───────────────> direct network

mihomoctl exec -- COMMAND / with_proxy COMMAND
        │
        └─ validated 8-variable child environment
             └─ authenticated 127.0.0.1:<per-user-port>
                  └─ Mihomo ──> user-owned routing policy
```

Starting Mihomo does not proxy the current shell. Environment changes are not
retroactive: a running Codex, VS Code Remote, Notebook, tmux, or other long-lived
process may require a user-initiated reconnect or restart.

Each Linux account has independent XDG paths, service settings, credentials,
and a unique port. The listener is authenticated and configuration files are
parsed as data with fixed key allowlists.

## Requirements and installation

Requirements are Linux, Bash 5+, Python 3.8+, a working `systemd --user`
manager, `curl`, `ss`, `journalctl`, and an existing user-owned Mihomo service
with an authenticated Mixed listener bound only to `127.0.0.1`.

The project does not install or upgrade the Mihomo core. Follow the
[complete setup guide](docs/en/setup.md) first when needed.

Choose and confirm a currently unused per-user port, configure the same port in
Mihomo and `client.env`, then install the control layer:

```bash
PROXY_PORT=$(./install.sh --suggest-port)
ss -lnt "sport = :$PROXY_PORT"
./install.sh --dry-run --port "$PROXY_PORT"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
```

Installation is transactional, records immutable runtime hashes and provenance,
preserves credentials and Mihomo data, and never starts or enables the service.

## Update

```bash
mihomoctl update --check
mihomoctl update --version v0.2.2 --dry-run
mihomoctl update --version v0.2.2
```

An update changes only `mihomo-userctl`; it is not a Mihomo core upgrade. It
uses the same transactional installer, preserves configuration, credentials,
port, loader and active/enabled state, and records an exact release commit.
See [update and rollback](docs/en/update.md) for exit codes and recovery.

## Daily commands

```text
mihomoctl start
mihomoctl stop
mihomoctl restart

mihomoctl status [--json]
mihomoctl ready [--json]
mihomoctl doctor [--offline] [--json]

mihomoctl exec -- COMMAND [ARGS...]
mihomoctl direct -- COMMAND [ARGS...]

mihomoctl diagnose url URL [--json]
mihomoctl diagnose process PID [--json]
mihomoctl diagnose name NAME [--json]

mihomoctl rules status [--json] [--home-dir PATH] [--config PATH]
mihomoctl rules check [--home-dir PATH] [--config PATH]

mihomoctl logs [--lines N] [--follow]
mihomoctl version
mihomoctl update --check | --version TAG [--dry-run]
```

`mihomoctl exec` is the uniform entry point for scripts, IDE launchers, and
non-interactive programs. `direct` removes only the eight upper/lower-case proxy
variables in the child. Both require `--`, preserve arguments as an array, do
not modify the parent shell, and pass through a launched command's exit status.

`diagnose url` reports direct access, listener state, authentication, and target
requests separately. Listener readiness is not evidence that a request used a
proxy node, and this command never claims which node was selected.

Exit `0` means success or a passed check, `1` means an observed runtime,
readiness, or target-check failure, and `2` means an argument, configuration,
permission, dependency, or unverifiable error. `diagnose name` returns `1` when
no exact current-user process matches. Versioned JSON writes one object to
stdout on success and ordinary failure; human diagnostics go to stderr.

## Shell compatibility

The released Shell functions remain available:

```text
proxy_on  proxy_off  proxy_status  with_proxy
mihomo_start  mihomo_stop  mihomo_restart  mihomo_status  mihomo_logs
```

`with_proxy` is the existing interactive-Shell compatibility entry point.
`proxy_on` explicitly changes the current shell; `proxy_off` returns it to
direct mode. A newly loaded ordinary shell starts direct.

The v0.2.1 top-level `test-url`, `inspect-process`, and `inspect-name` commands
remain hidden compatibility aliases. New automation should use `diagnose`.

## Scope and evidence

`status` reports only service active/enabled state, listener state, and the local
endpoint. `ready` checks only the fixed configured readiness URL through the
authenticated path. `doctor` checks dependencies, configuration, permissions,
and runtime state. Process diagnostics read only current-UID `/proc` data and
return counts and categories—not environment values, full command lines, or
remote addresses.

`rules status/check` is a read-only verifier for the documented three-file
custom-rule contract. It never creates rules, edits `config.yaml`, downloads
providers, calls a Controller, or changes service state. `rules check` is not a
complete routing-behavior acceptance; full configuration semantics remain with
the user's own `mihomo -t`. See [private custom rules](docs/en/rules.md).

PASS, FAIL, UNVERIFIED, and DEFERRED evidence are defined in the
[acceptance guide](docs/en/acceptance.md). Security and ownership boundaries are
in the [architecture](docs/en/architecture.md) and
[security model](docs/en/security.md).

## Documentation

- [Complete setup](docs/en/setup.md)
- [Copyable coding-agent installation prompt](docs/en/agent-install-prompt.md)
- [Architecture and responsibility matrix](docs/en/architecture.md)
- [Security model](docs/en/security.md)
- [Acceptance and evidence](docs/en/acceptance.md)
- [Troubleshooting](docs/en/troubleshooting.md)
- [Private custom rules](docs/en/rules.md)
- [VS Code Remote](docs/en/vscode-remote.md)
- [Update and rollback](docs/en/update.md)
- [Copyable coding-agent update prompt](docs/en/agent-update-prompt.md)

## Uninstall and license

`./uninstall.sh --dry-run` previews removal; `./uninstall.sh` removes only
project-owned code and the managed loader. Mihomo, its service, configuration,
credentials, subscriptions, providers, caches, and backups remain. The project
is licensed under the [MIT License](LICENSE).
