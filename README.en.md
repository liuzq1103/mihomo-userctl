# mihomoctl

mihomoctl manages a user-level Mihomo runtime on Linux, injects authenticated proxy environments, and connects applications through declarative bindings.

[简体中文](README.md)

## When to use it

Use it on servers, development machines and CI to explicitly route selected commands or applications through a configured Mihomo proxy. The user process backend works without systemd; systemd management is optional.

It supplies no subscription service and cannot force clients to honor proxy variables. It does not manage Codex/Paseo application lifecycles. Machine-wide transparent routing requires an administrator's explicit system scope and TUN configuration.

## Requirements and stable version

<!-- stable-version: 1.4.1 -->
Current stable version: **1.4.1**. The new complete bundle targets Ubuntu 22.04/24.04 x86_64 and includes Python, Textual, dependencies and a pinned core. Separate Linux accounts own independent instances. No venv, pip, UI installation or port forwarding is needed. Download the complete bundle and checksum from the [v1.4.1 release](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.4.1). Source archives and legacy wheelhouse kits still need a prepared Python environment.

## Quick Start

Verify and extract the complete bundle as described in [INSTALL.md](INSTALL.md), then run:

```bash
./mihomoctl
```

Paste an HTTPS subscription into the terminal form, review it, confirm saving and starting, then search, measure and select a node. Existing managers are preserved. Optionally run `./install.sh --user`, then use `mihomoctl` directly. Use `mihomoctl tui --engine plain` for a basic terminal.

```bash
mihomoctl exec -- codex
```

Software preparation can be offline; subscriptions and referenced resources must remain reachable. Successful operations retain no previous versions or configuration backups. Historical rollback is disabled.

## Initialize and start Mihomo

The advanced CLI command `init` creates private configuration and an authenticated loopback listener. It neither downloads a core nor starts a service. Import existing configuration with `init --config`, then explicitly `start`; explicitly `restart` after changes. To go back to the initial state, preview with `mihomoctl reset --dry-run` and then run `mihomoctl reset --apply`: it keeps the core binary and the subscription previews, and resets only configuration and credentials. See [setup](docs/en/setup.md) for fixed-version core installation and XDG paths.

## Configure subscriptions

Save subscription content in a private file, preview the candidate, review its ID and SHA256, apply it, then explicitly restart. Pass a subscription URL through a private file; never put its credentials in arguments.

```bash
mihomoctl subscription preview --source-file "$HOME/private/subscription.yaml" --policy nodes
```

The [subscription tutorial](docs/en/subscriptions.md) explains auto/nodes/provider modes and digest validation.

## Configure custom rules

Import subscriptions first. Create three private rule files, reference their providers in the active configuration, and put their rules before the fallback. The current checker requires a group named `Proxy`.

```bash
mihomoctl rules check --json
```

The [rule tutorial](docs/en/rules.md) includes paths, permissions and complete snippets. The checker is read-only; saving configuration and restarting remain explicit.

## Launch Codex through the proxy

Install Codex separately and ensure `codex` is on PATH. These commands inject an environment into the new child process:

```bash
mihomoctl exec -- codex
mihomoctl exec -- codex --help
mihomoctl exec -- codex "检查当前项目"
mihomoctl direct -- codex
```

For third-party CLI installers, wrap the entire installation shell so its subsequent downloads inherit the proxy; see [installer proxy inheritance](docs/en/first-run.md#install-a-third-party-cli-through-the-proxy).

`exec` refuses to launch when local health checks fail. `direct` clears eight proxy variables. Remote-node routing still depends on client behavior, NO_PROXY and destination rules. See [first run and verification](docs/en/first-run.md).

## Connect systemd, containers and CI

Declare bindings in manager.yaml, then use `integration check/export/install`. systemd consumes a private environment file; containers need an explicitly reachable address; CI integration only exports configuration. Follow the complete [integration tutorial](docs/en/operations/integrations.md). Operators restart third-party services themselves.

## Status and troubleshooting

```bash
mihomoctl status
mihomoctl health check
mihomoctl doctor
mihomoctl logs --lines 50
```

A reachable listener, selected node or successful external probe alone cannot prove that Codex used a remote node. Check runtime state, authenticated proxy access, destination routing and the actual client request in sequence; see [verification](docs/en/first-run.md).

## Safety boundaries

Default user/process scope; no self-elevation, sudo, shell startup file edits (.bashrc, .zshrc, profile) or automatic third-party service actions. Credentials stay in private files and default output is redacted. Do not publish `--reveal` output or exported environment files. TUN requires explicit `--system` operations. Updates and uninstall preserve user configuration, credentials, subscriptions, caches and the Mihomo core. See [security](docs/en/security.md).

## Documentation

- [Local agent installation prompt](docs/en/agent-local-install-prompt.md) · [Offline installation](docs/en/offline-install.md)
- [Installation and upgrades](INSTALL.md) · [Tutorials](docs/en/README.md)
- [CLI reference](docs/en/reference/cli.md) · [Configuration contract](docs/en/reference/configuration.md)
- [Operations](docs/en/operations/integrations.md) · [Release acceptance](docs/en/operations/release.md)
- [Repository layout](docs/architecture-v1.md) · [Changelog](CHANGELOG.md) · [Archive](docs/archive/README.md)

## License and affiliation

The manager is licensed under [MIT](LICENSE). The complete bundle also includes Python, dependencies and Mihomo (GPL-3.0) under their respective licenses; its `licenses.json` lists components and notice files, and `core/LICENSE` and `core/SOURCE.txt` provide the core license and upstream source links. This independent, unofficial manager is not affiliated with Mihomo, OpenAI/Codex or Paseo.

## Discover and acquire releases

```bash
mihomoctl release check
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target linux-x86_64
mihomoctl update --latest
```

Since 1.2.0, interactive status/version/doctor/TUI entries can launch a daily,
bounded background check and show each observed newer version once on a later
entry. Failures preserve the original exit code. JSON, pipes and exec do not
trigger checks. Set `MIHOMOCTL_NO_UPDATE_CHECK=1` to disable automatic checks.
An observation never establishes that an installed version is the latest.

Existing v1.0.0–v1.1.1 users must still use the verified new installer described
in [INSTALL.md](INSTALL.md); old binaries cannot gain notifications themselves.
See [update and failed-operation recovery](docs/en/update.md) for portable offline acquisition.
