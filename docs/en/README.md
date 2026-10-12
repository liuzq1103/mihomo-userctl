# English documentation

> **v1.0.0:** the automatic shell hook has been removed and the installer writes no
> startup file; application-specific daemon lifecycle is retired. The command
> surface follows the [V1 command and configuration contract](v1.md).

For a new server, read these in order:

1. [Installation](../../INSTALL.md)
2. [Setup guide and the full stack](setup.md)
3. [First use](first-run.md)
4. [V1 command and configuration contract](v1.md)
5. [V1 architecture and implementation contract](../architecture-v1.md)
6. [Security model](security.md)

## V1 baseline

- [V1 command and configuration contract](v1.md)
- [V1 architecture and implementation contract](../architecture-v1.md)
- [ADR 0002: V1 generic runtime and retired third-party lifecycle](../adr/0002-v1-generic-runtime.md)
- [Design reference and derived boundaries](../design-reference.md)
- [Code audit](../code-audit.md)
- [Security policy](../../SECURITY.md)

## Using

- [Setup guide](setup.md) · [Quick installation](quick-install.md) ·
  [Offline installation](offline-install.md)
- [First use](first-run.md)
- [Nodes and dashboards](control-plane.md)
- [Console](console.md) · [Console acceptance](console-acceptance.md)
- [TUI overrides and manual groups](tui-overrides.md)
- [Private custom-rule contract and read-only checks](rules.md)
- [VS Code Remote](vscode-remote.md)
- [Shared runtime on multi-user servers](shared-runtime.md)

## Operations and verification

- [Deployment parameters and delivery contract](deployment-contract.md)
- [Installation acceptance and evidence](acceptance.md)
- [Updates and rollback](update.md)
- [Troubleshooting](troubleshooting.md)
- [Security model](security.md)

## Coding agent prompts

- [Installation prompt](agent-install-prompt.md)
- [Local installation prompt](agent-local-install-prompt.md)
- [Update prompt](agent-update-prompt.md)

## Archived

These pages are kept for the record; **their command surface was retired in v1.0.0**:

- [Paseo background injection and systemd](paseo.md)
- [Paseo production report](paseo-production.md)

The replacement is generic integration via `mihomoctl integration`; see the
[retired-command mapping](v1.md#12-retired-commands).

## Historical roadmap (not the current implementation)

[architecture-vnext.md](../architecture-vnext.md) ·
[ADR 0001: V1 foundation decision](../adr/0001-vnext-foundation.md)
