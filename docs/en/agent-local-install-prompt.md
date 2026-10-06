# Coding-agent prompt for local archives

[中文](../zh-CN/agent-local-install-prompt.md) · [Local setup](offline-install.md) · [Public online prompt](agent-install-prompt.md)

Use the shared [deployment parameters and delivery contract](deployment-contract.md).

```text
Install the requested tools for this ordinary Ubuntu account from pre-downloaded local material.
Archive directory: <absolute path, for example /mnt/nas/public/software>
Source version: <exact published version, for example v0.7.0; clarify ambiguous candidates>
Runtime: <personal installation by default; administrator-shared Node/npm/Codex only if selected>
Selected tools: <mihomo by default; codex/node/opencode optional; reuse suitable existing tools>
Install mihomo-userctl controller: <yes by default>
Personal port: <confirmed value, or obtain a read-only suggestion for my confirmation>
Known environment/reuse: <existing tool paths/versions; reuse suitable installations>
Goal: <controller installation / include Codex end-to-end acceptance>
Startup: <install only and preserve state / install and start for acceptance>
Network acceptance: <selected refresh/probes/minimal model request; not online installation>

The public directory holds a source ZIP and independent dependency archives, not a shared runtime.
List archives read-only and identify the exact source release; clarify ambiguous versions instead
of guessing names or selecting latest. Follow offline-install.md's source preparation: copy the ZIP
to a new private workspace, compare SHA256 before/after, and inspect paths, symlinks, duplicate members
and size limits before extraction. Reject escapes and overwrites. Confirm release provenance/version
against trusted records; a locally computed digest proves transfer consistency only. Stop if unknown.
No pre-expanded source/, packages/, external scripts or SOURCE.txt are required in the public directory.
Read the extracted release's offline-install.md, setup.md, security.md, acceptance.md, architecture.md,
troubleshooting.md, deployment-contract.md and repository constraints before executing project scripts.
Use one fixed release for documentation, scripts and tests; never expand authorization or mix in main.
Replace online download/clone steps with local preparation. Never access GitHub/npm/apt or run
mihomoctl update (including --check), and never download missing files as a fallback.
Inspect Linux architecture/libc/CPU, dependencies, systemd user manager, existing programs/PATH,
proxy-variable categories, ports, service state and archive-directory trust/permissions.
Review the extracted source's pinned manifest and provenance records.
Missing packages, checksum mismatches or dependencies must stop the workflow with a specific report.
Report the audit and concrete change/rollback scope. Reuse suitable system Node/npm/Codex without
shadowing them. Follow the contract's redacted audit: no environment dumps, full argv or raw logs.
Read shared-runtime.md in shared mode: missing public tools go to the administrator, never a personal
fallback. Verify fresh-login/proxy Node/npm/Codex resolution, npm-launcher interpreter and private
CODEX_HOME. Preserve authentication, sessions, NVM and old installs; migration/uninstallation needs
explicit selection, never cleanup commands copied from deployment notes.
Follow shared-runtime.md for Remote hook, CLI/persistent-server Unix-socket and egress evidence;
0/8 or 8/8 alone is insufficient. Never persist CODEX_REMOTE_PAYLOAD or automatically restart old servers.

Use private-source scripts/offline_install.py check/install with examples/offline-packages.json;
--bundle-dir points to the actual archive directory. The installer copies and rechecks dependencies
in private storage. Install only selected missing tools. Never run npm install,
download through npx, or execute archive install scripts. Preserve conflicting existing commands;
report a concrete backup/migration plan before an unauthorized replacement. Use the original install.sh from the reviewed private source for the controller.
Installed commands must not depend on the public archive directory. Proceed within existing
authorization; clarify only unresolved configuration or changes outside that authorization.
Do not use sudo or alter shared files/other users/system services/TUN/system proxies. The installer
never starts services itself. Explicit install-and-start authorization permits starting the user service
after configuration/port checks, keeping it disabled. Install-only preserves runtime state; never stop
working services for tests. Keep per-user ports, authenticated listeners and credentials; the default new service
is disabled, and existing state follows the original setup contract.

Keep credentials and private subscriptions in restricted personal files, never chat/logs/Git/shared
packages. If disabling OpenCode autoupdate, merge autoupdate=false without replacing other personal
settings. Do not automatically install plugins, LSP, MCP or extensions; list missing runtime resources.
For missing credentials, provide the documented restricted local file/editing method, wait for user
completion, and never request secret values in chat. Do not repeat existing approvals.

Run documented local version checks, source regression tests and acceptance, preserving real exit
codes. Do not perform authentication, subscription refresh or external connectivity probes without
network authorization; mark them UNVERIFIED. DEFERRED requires explicit user postponement;
unselected features are unselected. Follow the contract for separate Codex executable, new-process,
Listener/proxy-egress and authorized minimal model request evidence; the user handles login.
Untested runtime compatibility is UNVERIFIED.
Listener readiness is not proxy-node evidence. Return versions/architecture/SHA256/local sources,
personal installation paths and receipts, controller backup/rollback commands, service state,
actual check results and remaining actions, using the contract's report fields and scoped isolation
claims. Do not claim independent signature verification.
Finish with deployment-contract.md's subscription handoff: actual absolute path/provider URL key,
local editing and authorized follow-up checks. Preserve existing subscriptions; file providers use
their actual import location. Never request links in chat or report missing setup as fully usable.
For Codex delivery follow first-run.md: install → mihomoctl doctor → mihomoctl start only if selected →
mihomoctl codex preflight only when public probing is authorized. Exit 0 permits authorized real-client
acceptance; exit 1 is BLOCKED: no Codex or model request, guide safe client reconnect; exit 2 is UNVERIFIED: no launch.
Never run bare codex for post-install acceptance; mihomoctl codex repeats the gate. Use mihomoctl diagnose codex
for offline diagnosis; its UNVERIFIED/exit 2 does not mean model failure. WebSocket needs local/remote distinction.
The installation agent's own connectivity is not Codex evidence; .bashrc changes disk state, not existing
Agent/app-server/Extension Host/tmux/Notebook environments. Never kill or delete sockets/authentication/sessions.
Report four levels and pending subscription/login/reconnect; HTTP success cannot replace an actual model reply.
```
