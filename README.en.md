# mihomoctl

mihomoctl manages a user-level Mihomo runtime on Linux, injects authenticated proxy environments, and connects applications through declarative bindings.

[简体中文](README.md)

## When to use it

Use it on servers, development machines and CI to explicitly route selected commands or applications through a configured Mihomo proxy. The user process backend works without systemd; systemd management is optional.

It supplies no subscription service and cannot force clients to honor proxy variables. It does not manage Codex/Paseo application lifecycles. Machine-wide transparent routing requires an administrator's explicit system scope and TUN configuration.

## Requirements and stable version

<!-- stable-version: 1.2.0 -->
Current stable version: **1.2.0**. Requires Linux, Python 3.10+, PyYAML 6.0.1+, and Bash for the installer. Supply Mihomo separately or install it explicitly. Textual is optional; a plain terminal menu is available by default. On Windows, run inside Linux/WSL.

## Quick Start

Follow [INSTALL.md](INSTALL.md) to verify the release and install the controller with its dependencies. With an existing trusted Mihomo binary:

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl init --core /absolute/path/to/mihomo
mihomoctl start
mihomoctl health check
mihomoctl exec -- curl --fail --head https://example.com
```

The initial routing rule is `MATCH,DIRECT`: this checks the local proxy path, not remote-node routing. Continue with subscriptions and rules.

## Initialize and start Mihomo

`init` creates private configuration and an authenticated loopback listener. It neither downloads a core nor starts a service. Import existing configuration with `init --config`, then explicitly `start`; explicitly `restart` after changes. See [setup](docs/en/setup.md) for fixed-version core installation and XDG paths.

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

- [Installation and upgrades](INSTALL.md) · [Tutorials](docs/en/README.md)
- [CLI reference](docs/en/reference/cli.md) · [Configuration contract](docs/en/reference/configuration.md)
- [Operations](docs/en/operations/integrations.md) · [Release acceptance](docs/en/operations/release.md)
- [Repository layout](docs/architecture-v1.md) · [Changelog](CHANGELOG.md) · [Archive](docs/archive/README.md)

## License and affiliation

[MIT License](LICENSE). This independent, unofficial manager is not affiliated with Mihomo, OpenAI/Codex or Paseo.

## Discover and acquire releases

```bash
mihomoctl release check
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target ubuntu22.04-x86_64-py310
mihomoctl update --latest
```

Since 1.2.0, interactive status/version/doctor/TUI entries can launch a daily,
bounded background check and show each observed newer version once on a later
entry. Failures preserve the original exit code. JSON, pipes and exec do not
trigger checks. Set `MIHOMOCTL_NO_UPDATE_CHECK=1` to disable automatic checks.
An observation never establishes that an installed version is the latest.

Existing v1.0.0–v1.1.1 users must still use the verified new installer described
in [INSTALL.md](INSTALL.md); old binaries cannot gain notifications themselves.
See [upgrade and rollback](docs/en/update.md) for portable offline acquisition.
