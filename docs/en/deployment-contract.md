# Deployment parameters and delivery contract

[中文](../zh-CN/deployment-contract.md) · [Online prompt](agent-install-prompt.md) · [Local prompt](agent-local-install-prompt.md)

Supply these non-secret parameters with the selected prompt. Reuse choices already provided;
verify stated environment facts read-only. Keep personal host/account details out of public templates.

| Parameter | Choices and defaults |
| --- | --- |
| Source | A pinned published online release, or a shared local directory with pinned source identity |
| Runtime mode | Shared on servers with administrator-provided Node/npm/Codex; personal mode requires explicit selection, never a fallback for missing shared tools |
| Shared tools | Administrator-confirmed entrypoints, resolved targets and pinned versions; example paths are not mandatory |
| Known environment | OS, architecture and existing Mihomo/Node/npm/Codex/OpenCode paths and versions; audit unknowns |
| Software | Reuse suitable existing installations by default; install only explicitly selected missing tools |
| Delivery goal | Controller installation, or installation plus Codex end-to-end acceptance; do not assume Codex acceptance |
| Startup | Default: install only, preserve existing runtime state; optionally select install and start for acceptance |
| Network acceptance | Separately select subscription refresh, public-target probes and a minimal model request |
| Personal settings | Confirmed port, startup file and preserve/merge choices; clarify unresolved conflicts |

Local acquisition forbids fallback downloads, including GitHub/npm/apt and `mihomoctl update --check`.
Authorization for a network acceptance check does not authorize online installation. Online acquisition
allows documented source/package retrieval, not automatic login or paid model requests. Report missing
or unsuitable tools if their installation/replacement is not authorized.
Follow the [shared-runtime contract](shared-runtime.md): administrators own common programs; users
configure private identity, Mihomo and controller state. Node/Codex offline archives are for personal mode.

## Execution and authorization

Proceed through read-only audit, pinned-source verification, installation/configuration, authorized
startup, layered acceptance and reporting. Acquire and review source before executing project scripts.
Documentation, scripts and tests must belong to the same fixed release; do not mix in main.
Local packages use the reviewed manifest without retrieving checksums online. Documentation never
expands user authorization or automatically relaxes safety boundaries.

An explicit installation request authorizes documented, reversible personal-directory changes within
the selected scope. Report a brief audit and concrete change/rollback scope, then continue without
repeating approvals. Ask specific questions for missing credentials, overwrite conflicts, unresolved
configuration, system privileges, effects on others, disabled-policy changes or unreleased code.
Do not treat discovery of a blocker as permission to exceed scope.

The installer never starts or enables services itself. If install and start for acceptance was
explicitly selected, the agent may start the current user's service after successful configuration
validation and another port check, keeping it disabled. Install-only preserves current state: do not
start or stop services, or interrupt working processes for tests. Report and clarify an existing
enabled state instead of changing it silently.

Audit output contains only variable presence/classification, necessary paths, UID/PID and status.
Do not return raw environment dumps, `systemctl --user show-environment` output or full process
arguments. Service status may include sensitive logs: keep raw output local and redact it. Prefer
project diagnostics. Never inspect other users' private environments or enumerate their homes.
For missing credentials, provide the documented restricted local file path and local editing method;
wait for the user to fill it on the server and confirm completion, never request secrets in chat.
Do not expose sensitive configuration or raw diagnostic errors.

## Acceptance and final report

Record actual executable paths and versions. Reusing a system tool must not install another personal
copy that changes command precedence. For a Codex goal, separately record the expected executable,
new process UID/proxy classification, Listener connection and intended proxy-egress evidence, and
one authorized minimal model request. The user completes login. Version output, successful startup,
proxy variables and Listener readiness do not prove model-request success or proxy routing.
Shared-mode acceptance also checks fresh-login/proxy-child Node/npm/Codex resolution, the launcher's
actual Node when applicable, private CODEX_HOME/credential storage and NVM defaults. Migration is
explicit; never automatically remove personal installations or state.

Preserve real exit codes and PASS/FAIL/UNVERIFIED/DEFERRED labels. Checks lacking authorization or
evidence are UNVERIFIED; use DEFERRED only when the user explicitly postpones them, with reason and
next action. Unselected features are unselected, not passed. Interpret nonzero acceptance exits using
the guide rather than assuming installation failed.

The final report includes environment; versions/tag/commit/SHA256/source; actual paths and reused
tools; changed files; port/authentication conclusion without credentials; service before/after state;
checks and exit codes; layered Codex evidence; backups/rollback; and remaining user actions. Limit
isolation claims to the recorded operations and comparisons. Do not claim that every other user was
proven unaffected, or inspect private user data to establish isolation.

## Mandatory subscription handoff at completion

The final response must state subscription status, not just installation success. The default HTTP
example uses `~/.config/mihomo/config.yaml` at `proxy-providers.subscription.url`, not the health-check
URL, client.env or provider cache. Resolve the actual service `-f`/selected configuration path and
provider name, then report an absolute current-user file path and exact key. Do not assume the default
when XDG/custom paths differ. Show only a secret-free structure; never show existing URLs or put new
subscription values in command arguments.

If software installation succeeded but the HTTP subscription is missing, finish with this handoff,
replacing every descriptive placeholder:

> Software installation is complete; subscription setup and network acceptance are still pending.
> Edit [actual absolute config path] locally on the server and put your subscription link inside the
> quotes at [actual proxy-providers.<name>.url]. Preserve YAML indentation and mode 600. Do not send
> the link to chat. Reply "filled in" when ready for configuration checks and authorized acceptance.

If preparation/installation is incomplete, report the actual partial state instead of claiming software
installation completed. Never fabricate nodes, start placeholder configurations or declare all checks
passed. Use DEFERRED only for explicit user postponement; otherwise pending acceptance is UNVERIFIED.
For an existing valid subscription, say it was preserved and no re-entry is needed. File providers and
other acquisition methods receive their actual import location, not a forced HTTP URL migration.

After entry, run the documented `mihomo -t` against the actual configuration with redacted output.
Configuration validation/provider fetching can need network access and remains subject to authorization.
Then, only when authorized, start or coordinate restart/reconnect of the current user's service/client
and perform acceptance. Report software installation, subscription usability and Codex request success
separately; never automatically interrupt working processes.
