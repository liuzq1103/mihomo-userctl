# Coding-agent prompt for local shared packages

[中文](../zh-CN/agent-local-install-prompt.md) · [Local setup](offline-install.md) · [Public online prompt](agent-install-prompt.md)

Use the shared [deployment parameters and delivery contract](deployment-contract.md).

```text
Install the requested tools for this ordinary Ubuntu account from pre-downloaded local material.
Shared deployment directory: <absolute PUBLIC/mihomo-offline path>
Runtime: <administrator-shared Node/npm/Codex / explicitly selected personal install; shared paths/versions>
Selected tools: <shared mode: mihomo; personal mode may add node/codex; opencode separately selected>
Install mihomo-userctl controller: <yes/no>
Personal port: <confirmed value, or obtain a read-only suggestion for my confirmation>
Known environment/reuse: <existing tool paths/versions; reuse suitable installations>
Goal: <controller installation / include Codex end-to-end acceptance>
Startup: <install only and preserve state / install and start for acceptance>
Network acceptance: <selected refresh/probes/minimal model request; not online installation>

Read offline-install.md, setup.md, security.md, acceptance.md, architecture.md,
troubleshooting.md, deployment-contract.md and repository constraints before changes. Use
documentation, scripts and tests from one fixed release; never expand authorization or mix in main.
Replace setup.md's online
Mihomo download and Git clone steps with the documented local workflow.
Do not access GitHub/npm/apt or run mihomoctl update (including --check). Never fall back
to downloading missing files. Inspect capabilities, Linux architecture/libc/CPU, dependencies,
systemd user manager, existing programs/PATH, proxy-variable categories, ports and service state.
Review shared-directory trust/permissions, pinned manifest, SOURCE.txt and source.
Missing packages, checksum mismatches or dependencies must stop the workflow with a specific report.
Report the audit and concrete change/rollback scope. Reuse suitable system Node/npm/Codex without
shadowing them. Follow the contract's redacted audit: no environment dumps, full argv or raw logs.
Read shared-runtime.md in shared mode: missing public tools go to the administrator, never a personal
fallback. Verify fresh-login/proxy Node/npm/Codex resolution, npm-launcher interpreter and private
CODEX_HOME. Preserve authentication, sessions, NVM and old installs; migration/uninstallation needs
explicit selection, never cleanup commands copied from deployment notes.
Follow shared-runtime.md for Remote hook, CLI/persistent-server Unix-socket and egress evidence;
0/8 or 8/8 alone is insufficient. Never persist CODEX_REMOTE_PAYLOAD or automatically restart old servers.

Use only documented offline_install.py check/install for selected tools. Never run npm install,
download through npx, or execute archive install scripts. Preserve conflicting existing commands;
report a concrete backup/migration plan before an unauthorized replacement. Copy reviewed source
to a private workspace and use the original install.sh for the controller. Proceed within existing
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
```
