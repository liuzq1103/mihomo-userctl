# mihomo-userctl

The [Chinese task console](docs/en/console.md) automatically selects available Textual or a numbered menu; explicit curses/plain remain available. It provides runtime observations, batch latency, read-only connections, providers, logs and provider nodes/groups/routing-policy import. See the guide and [acceptance boundaries](docs/en/console-acceptance.md).

**For shared Linux servers and remote development: a user-level Mihomo Runtime Manager
with a workload-aware proxy control and verification layer.**

[简体中文](README.md) · [Quick start](#quick-start) · [English documentation](docs/en/README.md)

Per-user proxy entry, service management and diagnostics for shared servers and remote development.
Each Linux account manages its own Mihomo, configuration, credentials and distinct port. Ordinary shells
start direct; opt a program into the proxy with `mihomoctl codex` or `mihomoctl exec -- COMMAND`.

## Why use it

- Your laptop proxy works, but Codex on the remote server cannot connect: remote processes need their own proxy setup.
- Several people share a research server: manage private configuration and `systemd --user` services without changing the global proxy.
- Codex needs a proxy while ordinary downloads should retain their usual network setup: configure only explicitly selected child processes.
- Mihomo is running but the application still fails: check service, listener, authentication and process environments separately.

Starting Mihomo does not proxy the entire terminal. Downloads launched by a proxied process may inherit
its environment; use `mihomoctl direct -- COMMAND` to clear the child's proxy variables.

### Already using Mihomo or Mihoro?

**If your applications already connect reliably, you usually do not need to migrate.**
[Mihomo](https://github.com/MetaCubeX/mihomo) handles proxy protocols and routing.
[Mihoro](https://github.com/spencerwooo/mihoro) covers a wider lifecycle: provisioning,
core, subscription and geodata management. This project packages explicit process entry,
workload diagnostics and shared-server deployment procedures.

The two are **not mutually exclusive** and neither replaces the other:

| | Stronger at | mihomo-userctl emphasises |
| --- | --- | --- |
| **Mihoro** | provisioning, Mihomo core, subscription, geodata | — |
| **mihomo-userctl** | — | shared-server port coordination, per-user credentials, per-process proxy, workload adapters, runtime diagnostics and evidence, remote development |

If you already use Mihoro you **do not need to reinstall anything**. This project does
not currently take over or modify a binary, configuration or service created by Mihoro.

This project depends on Mihomo. It does not make nodes faster, and it offers node
inspection, selection and dashboard access. Subscriptions support node merging or provider routing-policy import while preserving host runtime settings, and
does not guarantee model connectivity. See [architecture](docs/en/architecture.md),
the [Mihoro comparison](docs/en/mihoro-inspiration.md).

## Explicit non-goals

These are deliberate scope boundaries, not backlog items, and are never promises:

- **Not a FlClash / Clash Verge replacement**; it does not generate desktop Clash rules.
- **No desktop GUI**; the optional browser panel is only a local dashboard entry point.
- **No TUN or transparent proxying**; system routes are never modified.
- **Not a general YAML editor**; `rules status/check` is a read-only checker.
- **No rootless strong UID network isolation**; loopback ports are host-wide resources and
  authentication is a credential boundary, not a cross-UID firewall.
- **Environment variables are not enforced network policy**: they are inherited only at
  process creation, and a process can change its own environment.
- **Readiness is not model E2E success**: `SAFE_TO_LAUNCH` only means local proxy
  preconditions hold.
- **It does not take over your crontab** and performs no scheduled auto-update; updates
  are the explicit `mihomoctl update` command.
- **It does not terminate processes whose ownership it cannot confirm**, including to
  free a port.
- **It does not install or upgrade the Mihomo core**; `install.sh` and `mihomoctl update`
  upgrade the control layer only.

## Supported environments

| Environment | Use |
| --- | --- |
| Remote Linux development server | Manage your service over SSH and proxy selected commands |
| Shared research/compute server | Separate configuration, authentication and an unused loopback port for each Linux account |
| Local Linux computer | Also usable with the dependencies below, for explicit command-level proxy entry |
| Native Windows / macOS | Outside this project's support scope; existing desktop proxy clients often cover local needs |

Requires Linux, Bash 5+, Python 3.8+, a working `systemd --user` manager, `curl`, `ss`, `journalctl`,
and an authenticated Mihomo Mixed listener bound only to `127.0.0.1`.
Bring your own account, service access and working proxy nodes.

No root, TUN or transparent proxy is used. Loopback ports are host-wide; authentication is not strict
cross-UID firewall isolation. See the [security model](docs/en/security.md).

## Quick start

### Install the control layer with one command

```bash
curl -fsSL https://raw.githubusercontent.com/liuzq1103/mihomo-userctl/main/bootstrap.py -o mihomo-userctl-bootstrap.py && python3 mihomo-userctl-bootstrap.py
```

Resolves the latest published stable release to an immutable commit, chooses an unused proxy port,
and invokes the existing installer. Requires Linux, Python 3.8+ and a working systemd user manager.
**Control layer only:** prepare Mihomo, subscription and service configuration using the full guide below.
Add `--version vX.Y.Z` for a published version or `--dry-run` to preview. See [quick installation](docs/en/quick-install.md).
The entry point installs published releases, not unpublished development snapshots.

Choose how the target machine obtains software, then give the matching guide to a coding agent with
terminal and file access to your Linux account. Reuse suitable existing software; install selected
missing components privately by default.

| Software source | Entry point |
| --- | --- |
| Target can reach official sources | [Complete setup](docs/en/setup.md) · [Online installation prompt](docs/en/agent-install-prompt.md) |
| Packages already downloaded to private or shared storage | [Package list and workflow](docs/en/offline-install.md) · [Local-package installation prompt](docs/en/agent-local-install-prompt.md) |

“Local packages” means files already available, including on a remote server. Shared package storage is
for distribution; an [administrator-shared runtime](docs/en/shared-runtime.md) is a separate explicit choice.

For online installation, copy:

```text
Read https://github.com/liuzq1103/mihomo-userctl/blob/main/docs/en/agent-install-prompt.md
and follow it to install mihomo-userctl for this Linux account. First select an exact published version,
then use its matching documents, scripts and tests. Follow the deployment parameters and authorization
contract, and reuse suitable existing software.
```

For prepared packages, copy:

```text
Read https://github.com/liuzq1103/mihomo-userctl/blob/main/docs/en/agent-local-install-prompt.md
and install from my specified package directory for this Linux account. First resolve the exact
published version and selected software, then use the matching documents, scripts and tests in that
package. Report missing packages without falling back to online downloads.
```

These are entry instructions; fill in non-sensitive parameters in the matching prompt. Enter subscriptions
and credentials only on the target machine, not in chat. The full setup guide covers preparing Mihomo;
`install.sh` **installs only the control layer**, not the Mihomo core, and never starts or enables the service.
For manual installation follow [complete setup](docs/en/setup.md).

## Everyday use

After completing subscription configuration, start from an ordinary terminal as needed:

```bash
mihomoctl status
mihomoctl doctor --offline
mihomoctl start
mihomoctl codex preflight
mihomoctl codex
```

In v0.8.0, `mihomoctl codex preflight` checks proxy configuration, service, authentication, HTTP egress
and same-user Codex processes. Only `0 / SAFE_TO_LAUNCH` permits launch; `1 / BLOCKED` and
`2 / UNVERIFIED` never launch. `mihomoctl codex` runs this same full gate internally; running preflight
separately is optional and supports `--json`. Direct/inconsistent old processes block; incomplete
inspection fails closed. It does not start Mihomo, stop old processes or log you in. Put arguments
after `--`, e.g. `mihomoctl codex -- resume`. Continue with the [first-use guide](docs/en/first-run.md).

```bash
# Run another command through the proxy
mihomoctl exec -- curl --head https://example.com/
# Clear proxy variables in one child process
mihomoctl direct -- curl --head https://example.com/
# Inspect existing Codex processes and environments
mihomoctl diagnose codex
```

In Bash, `with_proxy COMMAND` is also available. Verified Remote hooks and VS Code Remote use their own
entry paths; follow [first use](docs/en/first-run.md) and [VS Code integration](docs/en/vscode-remote.md).
Writing the `.bashrc` loader does not automatically proxy a bare `codex` in an ordinary terminal.

## See and select nodes

**For remote servers, prefer the TUI: use it directly over SSH without port forwarding.**
v0.7 provides a fullscreen terminal interface; the browser dashboard is optional. Controller commands require PyYAML.

```bash
mihomoctl controller setup  # backup and validate; does not restart
mihomoctl restart          # when an interruption is acceptable
mihomoctl tui               # recommended over SSH
mihomoctl groups            # scripts / inspection
mihomoctl select "Proxy" "YOUR NODE"
mihomoctl ui                # optional browser dashboard
```

The bundled panel shows selections, switches nodes, tests latency and shows active connection chains.
You can also install a SHA256-pinned MetaCubeXD static archive. Use SSH forwarding for a remote server;
do not publish the controller port. See [nodes and dashboards](docs/en/control-plane.md).


## Common questions

**Why can Codex fail after HTTP readiness passes?**

HTTP proxy ready ≠ Codex runtime ready ≠ model E2E verified.
The HTTP check proves only that request; the actual client's remote transport and model reply need
separate verification. Local Unix sockets and localhost should remain direct. Not every WebSocket error
is a remote proxy failure.

**Why do old errors persist after changing the proxy?**

New variables do not update an old CLI, bridge, app-server or VS Code Extension Host. A proxied new CLI
does not prove that a reused service has the same environment. Run `mihomoctl diagnose codex`, save work,
then normally exit and reconnect your own clients. Do not broadly kill processes or delete sockets,
credentials or sessions. This diagnosis reports overall `UNVERIFIED` and exits `2`; that is not a failed model request.

**What happens after a reboot?**

The service defaults to disabled; run `mihomoctl start` when needed. This still leaves the current shell
unchanged. See [troubleshooting](docs/en/troubleshooting.md) for more cases.

## Update and uninstall

The current version is v0.9.1. Preview changes before upgrading; install optional Textual dependencies explicitly using the [console guide](docs/en/console.md).

v0.8.0 adds node search, explicit manual-group conversion and backed-up local JavaScript policy overrides,
plus SOCKS authentication-rejection evidence and non-dumpable helper classification fixes.
See [TUI and overrides](docs/en/tui-overrides.md).

```bash
mihomoctl update --check
mihomoctl update --version v0.9.1 --dry-run
mihomoctl update --version v0.9.1
```

Updates affect only the control layer, preserving configuration, credentials, port, loader and service
active/enabled state. They do not upgrade Mihomo. See [update and rollback](docs/en/update.md).
From a reviewed checkout, `./uninstall.sh --dry-run` previews removal and `./uninstall.sh` removes the
control layer and managed loader, retaining Mihomo, its service, configuration, subscriptions, caches and backups.

## Command and behavior reference

<details>
<summary>Expand all commands, exit codes, shell compatibility and evidence boundaries</summary>


```text
mihomoctl start
mihomoctl stop
mihomoctl restart

mihomoctl status [--json]
mihomoctl ready [--json]
mihomoctl doctor [--offline] [--json]

mihomoctl codex preflight [--json]
mihomoctl codex [-- ARGS...]
mihomoctl exec -- COMMAND [ARGS...]
mihomoctl direct -- COMMAND [ARGS...]

mihomoctl diagnose url URL [--json]
mihomoctl diagnose process PID [--json]
mihomoctl diagnose name NAME [--json]
mihomoctl diagnose codex [--json]

mihomoctl rules status [--json] [--home-dir PATH] [--config PATH]
mihomoctl rules check [--home-dir PATH] [--config PATH]

mihomoctl controller setup [--port PORT] [--home-dir PATH] [--archive ZIP --sha256 HASH]
mihomoctl controller status [--json]
mihomoctl controller token
mihomoctl tui [--plain]
mihomoctl nodes [--json]
mihomoctl groups [--json]
mihomoctl select GROUP NODE [--json]
mihomoctl latency NODE [--json]
mihomoctl connections [--json]
mihomoctl traffic [--json]
mihomoctl ui [--json]
mihomoctl dashboard [--json]
mihomoctl manual GROUP [--json] [--apply]
mihomoctl override --script FILE [--json] [--flclash-compat] [--apply]

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

Preflight exit codes are defined above; after launch, `codex`/`exec`/`direct` pass through the child status.
For ordinary diagnostics, exit `0` means success or a passed check, `1` means an observed runtime,
readiness, or target-check failure, and `2` means an argument, configuration,
permission, dependency, or unverifiable error. `diagnose name` returns `1` when
no exact current-user process matches. Versioned JSON writes one object to
stdout on success and ordinary failure; human diagnostics go to stderr.

### Shell compatibility

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

### Scope and evidence

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

</details>

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

## License

[MIT](LICENSE). An independent, unofficial project, not affiliated with MetaCubeX, Mihomo or Mihoro.
