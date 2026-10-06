# First use after installing Codex proxy support

[中文](../zh-CN/first-run.md) · [Setup](setup.md) · [Troubleshooting](troubleshooting.md)

Installation success ≠ HTTP proxy ready ≠ Codex runtime ready ≠ model E2E verified.
Complete private subscription/configuration and install Codex; the user handles sign-in.
This page describes v0.6.0. The v0.5.0 launcher warned about old processes; v0.6.0 refuses unsafe or
unverifiable launches. v0.4.0 has no Codex-specific entry; its `with_proxy codex` is not the new runtime gate.

## Four levels

| Level | Meaning and evidence |
| --- | --- |
| `CONTROL_PLANE_INSTALLED` | Loadable control layer with validated configuration/credentials; not a complete receipt/hash audit |
| `PROXY_READY` | Active user service, selected port loopback-only, anonymous HTTP/SOCKS rejected, authenticated HTTP request passed |
| `CODEX_RUNTIME_CLEAN` | Codex found, prepared launch environment matches, process snapshot complete and identified candidates all match |
| `CODEX_E2E_VERIFIED` | Authorized minimal model request through the real client received a complete reply; automatic preflight always leaves this UNVERIFIED |

These are current observations, not persisted certification. A snapshot cannot prevent new processes appearing later.

## First terminal check

```bash
mihomoctl doctor
# Only when startup was selected and configuration is complete:
mihomoctl start
mihomoctl codex preflight
mihomoctl codex preflight --json
# Only after preflight permits launch and real acceptance is authorized:
mihomoctl codex
```

An already-running service needs no extra startup. Preflight sends a HEAD request to the configured public
HTTPS READY URL and checks anonymous HTTP CONNECT and SOCKS rejection. It never requests a model,
logs in or starts a service. READY URL must have no userinfo, query, fragment or local hostname and must
support HEAD with a 2xx response. If probing is unauthorized or unavailable, do not run preflight; record UNVERIFIED.

| Exit | Decision | Next action |
| --- | --- | --- |
| 0 | SAFE_TO_LAUNCH | Authorized Codex acceptance may proceed; no model success claim |
| 1 | BLOCKED | Observed service/listener/auth/HTTP failure, missing Codex or mismatched existing process; no Codex launch or model request |
| 2 | UNVERIFIED | Configuration/dependency/permission/inspection error; no launch or success claim |

Inspection errors take precedence over known blockers: return 2 while preserving all observed reasons.
Network probes skipped because prerequisites failed are SKIPPED, not additional inspection errors.
`mihomoctl codex` reruns this same full preflight internally on every launch, then execs the PATH executable
only on exit 0. It does not use aliases/functions, install tools or stop processes; no bypass flag is provided.
After successful launch it returns Codex's own exit status, which is no longer a preflight decision.
Pass arguments with `mihomoctl codex -- resume`; the executable also works outside Bash.

An ordinary direct shell is expected. `invoking_environment` classifies the caller; `codex.current_environment`
checks the eight-variable environment prepared for the new child, leaving the parent unchanged.
Existing candidates must match all eight variables, including NO_PROXY. A VS Code server using only two
variables may work but does not satisfy this conservative terminal gate; that is not proof its model traffic failed.

## Stale processes and safe recovery

```text
Overall
  BLOCKED
Reason: stale-direct-app-server
  PID=182034 role=app-server proxy_environment=direct
```

The PID above is fictional. Any identified direct/inconsistent CLI, helper or app-server blocks; the gate
does not guess which candidate will be reused. Unreadable state, PID changes or an unclassifiable live
same-UID process yields UNVERIFIED.

1. Save work, then normally quit or disconnect your own old Codex clients.
2. Run `mihomoctl diagnose codex` for the read-only snapshot and check remaining active sessions.
3. Run preflight again and reconnect through the correct entry after resolving the reasons.

The tool never kills processes or deletes sockets, `.codex`, credentials or sessions. Do not destroy active
sessions to pass the gate. Editing `.bashrc` changes disk state, not existing OpenCode, Claude Code or Codex
installer agent process trees, app-servers, Extension Hosts, tmux or Notebooks. A new CLI's 8/8 proves nothing
about the reused old service's environment.

## Local and remote transport

```text
CLI → localhost / 127.0.0.1 / ::1 / Unix socket → app-server
    local_transport = DIRECT_EXPECTED

app-server → HTTPS / WSS / other remote transport → remote service
    remote_transport = UNVERIFIED
    model_request = UNVERIFIED
```

`NO_PROXY=localhost,127.0.0.1,::1` is intentional; Unix sockets do not traverse HTTP proxies.
DIRECT_EXPECTED describes policy, not a successful local connectivity test. HTTP readiness cannot prove
remote WebSocket/model success. Locate the failing layer before blaming Mihomo. Diagnosis keeps the legacy
`websocket=UNVERIFIED` JSON field and adds local_transport/remote_transport/model_request.
Do not disable TLS verification or apply unverified transport settings.

## Diagnosis and policy enforcement

`mihomoctl diagnose codex [--json]` is offline deep diagnosis, always overall UNVERIFIED with exit 2;
it neither makes network requests nor authorizes launch. `mihomoctl codex preflight [--json]` is the launch
policy decision with exits 0/1/2. Both emit only same-UID candidate PIDs, roles and environment classifications,
never full argv, environments, subscriptions or credentials.
Preflight uses `mihomo-userctl.diagnostics/v1` with command `codex-preflight`: launch_safe is boolean,
proxy/codex contain check classifications, checks contain probe evidence, reasons contain stable codes,
and levels contain the four states above. Configuration/inspection errors retain the same core fields.
When Python or trusted modules are unavailable, a minimal error object contains only schema, command,
overall, launch_safe, reasons and error.

Recognition covers codex process/executable names and identifiable node/bash/sh Codex script entries.
Arbitrarily renamed binaries or embedded custom services may be missed. Unix peer causality, reuse,
final node selection and real remote requests are not automatically proven. SAFE_TO_LAUNCH means only
that the implemented checks passed at this snapshot.

## Remote, VS Code and installation agents

Verified Remote hooks retain their existing entry; VS Code follows its [separate integration](vscode-remote.md).
These paths and `with_proxy`/`exec` do not automatically run the Codex gate. Post-install Codex acceptance
must first run preflight; never use bare `codex` as a shortcut or try model requests after a blocked result.
The generic `.bashrc` hook is unchanged to avoid affecting non-Codex commands and existing remote connections.

The installation agent's own connectivity is not target Codex acceptance evidence. After user sign-in,
send an authorized minimal message through the real client, confirm a complete reply and separately record
route evidence. Report all four levels and pending subscription, login and reconnect actions independently.

## v0.7 Control Plane

Use [nodes and dashboards](control-plane.md) to opt into an independently authenticated loopback controller.
See [fixed-link installation](quick-install.md) for bootstrap. These features do not bypass Codex preflight or change direct-by-default shells.
