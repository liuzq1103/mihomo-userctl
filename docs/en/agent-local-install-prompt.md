# Coding-agent prompt for local shared packages

[中文](../zh-CN/agent-local-install-prompt.md) · [Local setup](offline-install.md) · [Public online prompt](agent-install-prompt.md)

```text
Install the requested tools for this ordinary Ubuntu account from pre-downloaded local material.
Shared deployment directory: <absolute PUBLIC/mihomo-offline path>
Selected tools: <mihomo and optional node, codex, opencode>
Install mihomo-userctl controller: <yes/no>
Personal port: <confirmed value, or obtain a read-only suggestion for my confirmation>

Read offline-install.md, setup.md, security.md, acceptance.md, architecture.md,
troubleshooting.md and repository constraints before changes. Replace setup.md's online
Mihomo download and Git clone steps with the documented local workflow.
Do not access GitHub/npm/apt or run mihomoctl update (including --check). Never fall back
to downloading missing files. Inspect capabilities, Linux architecture/libc/CPU, dependencies,
systemd user manager, existing programs/PATH, proxy-variable categories, ports and service state.
Review shared-directory trust/permissions, pinned manifest, SOURCE.txt and source.
Missing packages, checksum mismatches or dependencies must stop the workflow with a specific report.

Use only documented offline_install.py check/install for selected tools. Never run npm install,
download through npx, or execute archive install scripts. Preserve conflicting existing commands;
report a concrete backup/migration plan before an unauthorized replacement. Copy reviewed source
to a private workspace and use the original install.sh for the controller. Proceed within existing
authorization; clarify only unresolved configuration or changes outside that authorization.
Do not use sudo, alter shared files/other users/system services/TUN/system proxies, or automatically
start Mihomo. Keep per-user ports, authenticated listeners and credentials; the default new service
is disabled, and existing state follows the original setup contract.

Keep credentials and private subscriptions in restricted personal files, never chat/logs/Git/shared
packages. If disabling OpenCode autoupdate, merge autoupdate=false without replacing other personal
settings. Do not automatically install plugins, LSP, MCP or extensions; list missing runtime resources.

Run documented local version checks, source regression tests and acceptance, preserving real exit
codes. Do not perform authentication, subscription refresh or external connectivity probes without
network authorization; mark them DEFERRED. Untested runtime compatibility is UNVERIFIED.
Listener readiness is not proxy-node evidence. Return versions/architecture/SHA256/local sources,
personal installation paths and receipts, controller backup/rollback commands, service state,
actual check results and remaining actions. Do not claim independent signature verification.
```
