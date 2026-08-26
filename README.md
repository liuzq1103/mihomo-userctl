# mihomo-userctl

`mihomo-userctl` is a small, security-focused control and Bash integration
layer for an existing per-user [Mihomo](https://github.com/MetaCubeX/mihomo)
service on Linux.

It is designed for shared research servers where normal shells and large data
downloads must remain direct, while selected commands may explicitly use an
authenticated, loopback-only Mihomo listener.

> This is an independent, unofficial project. It is not affiliated with
> MetaCubeX, Mihomo, or [Mihoro](https://github.com/spencerwooo/mihoro).

[简体中文](README.zh-CN.md)

## Why

Putting service management, credential parsing, readiness checks, and shell
functions directly in `.bashrc` is hard to audit and maintain. This project
keeps `.bashrc` as a short, fail-safe loader and moves the implementation into
versioned files:

```text
~/.local/bin/mihomoctl
~/.local/share/mihomo-userctl/{common.bash,shell.bash,completion.bash}
~/.config/mihomo/{mihomo-shell.conf,client.env}
```

The ordinary-shell invariant is simple: **direct by default**. Merely starting
Mihomo never changes the current shell's proxy environment.

## Requirements

- Linux with Bash 5+
- a working `systemd --user` manager
- an existing `mihomo.service`
- an authenticated Mixed listener bound only to `127.0.0.1`
- `curl`, `ss`, `journalctl`, `stat`, `awk`, `grep`

This v0.1 release does not download Mihomo, subscriptions, geodata, or a web
dashboard. See the [complete setup tutorial](docs/mihomo-setup.zh-CN.md) if the
Mihomo service is not installed yet.

It also does not generate Clash/Mihomo routing rules or desktop-client Merge
files. Keep those policy-generation tools in their own repository; this
project only controls the server user's existing service and shell environment.

## Install

Review the installer, clone the repository, then run:

```bash
./install.sh --dry-run --port 17890
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
```

The first install requires an explicit port. Re-running the installer is
idempotent. An update preserves `client.env` and refuses a conflicting port.
It never enables or starts the user service.

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

See [SECURITY.md](SECURITY.md) and the [Chinese security model](docs/security.zh-CN.md).

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
MIHOMO_PORT=17890
MIHOMO_READY_URL=https://example.com/
MIHOMO_READY_TIMEOUT=30
MIHOMO_STOP_TIMEOUT=5
```

`~/.config/mihomo/client.env` contains the authenticated local endpoints and
must be mode `600`. These files are parsed with a fixed key whitelist; they are
not Shell programs.

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
is documented in [docs/mihoro-inspiration.md](docs/mihoro-inspiration.md).

## License

MIT
