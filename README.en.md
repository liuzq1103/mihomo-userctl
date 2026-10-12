# mihomoctl

**A Mihomo lifecycle and proxy configuration CLI for personal users and server
administrators, with explicit proxy integration and verification.**

[中文](README.md) · [Installation](INSTALL.md) · [V1 command and configuration contract](docs/en/v1.md) ·
[English docs](docs/en/README.md)

The V1 domain model has four layers: **Proxy Profile + Environment Injection +
Runtime Integration + Health Check**. The core carries no application-specific code.

## Three things to know first

1. **The installer writes no shell startup file.** No `.bashrc`, `.zshrc` or
   `profile` edit, no aliases, no functions. First use does not depend on a login shell.
2. **Environment variables are inherited at process creation; they are not a
   continuous policy.** A running process does not change because configuration
   changed, and this tool never restarts a third-party process for you.
3. **This tool does not manage third-party application lifecycles.** systemd
   drop-ins, env files, container and CI configuration are only exported or
   written; it never enables, starts, stops or restarts someone else's unit.

## Why it exists

- A program on a remote server cannot connect: it needs its own explicit proxy access.
- A shared server: each Linux account manages its own config, credentials and ports,
  without touching global proxy settings.
- Only some commands should use the proxy: `mihomoctl exec` sets the variables for
  that one process.
- A background service should use the proxy: `mihomoctl integration install`
  writes the configuration and you schedule the restart.
- The proxy is up but something still fails: separate core, controller, listener,
  config, mode and TUN instead of one vague verdict.

## Non-goals

- **No third-party daemon lifecycle management**; the old application-specific
  commands are retired — see the [retirement mapping](docs/en/v1.md#12-retired-commands).
- **No desktop GUI**; the browser panel is an optional local entry point.
- **No general YAML editor.**
- **No rootless strong UID network isolation**; authentication is a credential
  boundary, not a cross-UID firewall.
- **Environment variables are not a network enforcement policy.**
- **Readiness passing is not model end-to-end success.**
- **No takeover of your crontab**, no overwrite-style automatic updates.
- **No killing processes of unconfirmed ownership**, including to free a port.

## Quick start

```bash
# 1. Install the control layer (see INSTALL.md)
mihomoctl version

# 2. First run: default user scope, default process backend, no root needed
mihomoctl init --core /absolute/path/to/mihomo

# 3. Start the runtime (default process backend)
mihomoctl start

# 4. Status: always seven facts
mihomoctl status

# 5. Proxy profiles (redacted)
mihomoctl profile list

# 6. Run one command through the proxy
mihomoctl exec -- curl --head https://example.com/
```

Full procedure: [INSTALL.md](INSTALL.md) and the [setup guide](docs/en/setup.md).

## Scope

| | User (default) | System |
| --- | --- | --- |
| Selected by | omitted | explicit `--system` |
| Backend | `process` by default | `systemd` required |
| Root | not needed | UID 0 required |
| TUN | **unavailable** | `sudo mihomoctl --system tun enable` only |

`--user` and `--system` are mutually exclusive. UID 0 is **not** promoted
automatically: root without `--system` may inspect user paths; mutations
are refused. The tool **never self-escalates and never uses sudo**.

## Command surface

```text
mihomoctl init --core PATH [--config FILE]
mihomoctl [--user|--system] start | stop | restart
mihomoctl [--user|--system] status [--json]
mihomoctl logs [--lines N] [--follow]

mihomoctl service install | start | stop | restart | status | uninstall
mihomoctl profile list | show NAME | validate NAME | set-default NAME
mihomoctl exec [--profile NAME | --binding NAME] -- COMMAND [ARGS...]
mihomoctl env show [--profile NAME | --binding NAME] [--reveal] [--json]
mihomoctl env export [--profile NAME | --binding NAME] (--output PATH | --reveal)

mihomoctl integration list | show NAME | check NAME NAME
mihomoctl integration export NAME | install NAME | remove NAME
mihomoctl health check [--profile NAME | --binding NAME] [--egress-url URL] [--json]
mihomoctl tun status | enable | disable        # enable/disable require --system

mihomoctl core install --version VERSION [--sha256 DIGEST]
mihomoctl core update --version VERSION [--sha256 DIGEST] [--dry-run]
mihomoctl core version
mihomoctl migrate [--dry-run] [--apply]

# retained control plane
mihomoctl controller status | tui | nodes | groups | select GROUP NODE
mihomoctl connections | traffic | latency NODE | subscription preview | apply
mihomoctl rules status | check
```

Full parameters: [docs/en/v1.md](docs/en/v1.md).

## What `status` always reports

Core, controller, **every** listener, the active config, the proxy layer, the Mihomo
routing mode, TUN, and errors. Any missing fact renders as `unknown` / `UNVERIFIED`;
incomplete data is **never** rendered as healthy.

## Health and evidence

`mihomoctl health` applies to the runtime only, never to a workload. Checks use
`PASS` / `FAIL` / `UNVERIFIED` / `SKIPPED` and carry an evidence level of
`confirmed` / `inferred` / `unavailable`.

Every output carries fixed boundary statements, including:

- readiness passing **is not** model end-to-end success;
- observing a listener **does not** prove its ownership;
- an authenticated probe **does not** prove the traffic used a remote node;
- node selection **does not** prove one specific request;
- an unobserved socket **does not** mean a direct connection.

External checks require an explicit `health check --egress-url URL`. Their result concerns that target probe only; it does not prove application traffic, and never gates local startup.

## Background services and containers

First define these names in `manager.yaml` under `bindings`, with their
`adapter` and `profile`. Container bindings also need a reachable `connect_host`;
a binding name is not an adapter type.

```bash
# writes configuration only, never restarts
mihomoctl integration install worker
mihomoctl integration show worker

# export only, never deployed automatically
# the reachable address is declared as connect_host in manager.yaml, not on the command line
mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"
mihomoctl integration export cluster-worker --output-dir "$HOME/.config/mihomoctl/export-cluster"
```

**`127.0.0.1` inside a container is the container's own loopback, not the host's.**
Exports require an explicit reachable address, and a wildcard address is never
emitted as a client address.

## Terminal console

```bash
mihomoctl tui
mihomoctl tui --plain          # numbered menu when Textual is unavailable
```

Pages: overview, nodes, subscriptions, access (profile), and more (connections /
rules / logs / providers / diagnostics / service). **Access** shows the proxy
profiles, the binding declarations and the fixed environment-injection boundaries;
**service** shows the seven runtime facts above. The console only renders
already-computed state and never builds its own readiness verdict. See
[console](docs/en/console.md).

## Documentation

- [Installation](INSTALL.md)
- [V1 command and configuration contract](docs/en/v1.md) · [中文](docs/zh-CN/v1.md)
- [V1 architecture and implementation contract](docs/architecture-v1.md)
- [ADR 0002: V1 generic runtime and retired third-party lifecycle](docs/adr/0002-v1-generic-runtime.md)
- [Design reference and derived boundaries](docs/design-reference.md)
- [Code audit](docs/code-audit.md)
- [Security model](docs/en/security.md)
- [Setup guide](docs/en/setup.md)
- [First use](docs/en/first-run.md)
- [Acceptance and evidence](docs/en/acceptance.md)
- [Troubleshooting](docs/en/troubleshooting.md)
- [Nodes and dashboards](docs/en/control-plane.md)
- [Private custom rules](docs/en/rules.md)
- [Updates and rollback](docs/en/update.md)
- [Archived: Paseo background injection](docs/en/paseo.md)

## License

[MIT](LICENSE). This is an independent, unofficial project with no affiliation
with MetaCubeX, Mihomo or Mihoro.
