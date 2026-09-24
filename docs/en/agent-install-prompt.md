# Coding-agent installation prompt

This is the public **official online-source** workflow. For packages already downloaded
to a shared directory, use the [local installation prompt](agent-local-install-prompt.md).
Do not mix acquisition workflows.

[中文](../zh-CN/agent-install-prompt.md) · [Setup](setup.md) · [Architecture](architecture.md) · [Security](security.md) · [Acceptance](acceptance.md)

Copy the prompt below into an agent that has terminal and file access to the
intended Linux account. Replace placeholders only with non-secret choices; keep
credentials and subscription URLs on the target machine.
Supply the non-secret [deployment parameters](deployment-contract.md); reuse existing choices.

```text
Install mihomo-userctl for this ordinary Linux account from an exact reviewed,
pinned released tag. Complete the work and return evidence, not only a plan.
Known environment/reuse: <OS/architecture/existing tool paths and versions; reuse suitable tools>
Runtime: <administrator-shared Node/npm/Codex / explicitly selected personal install; shared paths/versions>
Goal: <controller installation / include Codex end-to-end acceptance>
Startup: <install only and preserve state / install and start for acceptance>
Network acceptance: <selected subscription refresh, public probes, minimal model request>

Acquire and review pinned source first. Before changing the target environment, read
deployment-contract.md, the repository constraints and these same-version documents
in full: docs/en/setup.md, architecture.md, security.md, acceptance.md,
troubleshooting.md, and vscode-remote.md when that integration is selected.
Follow those documents instead of copying their implementation details into a
new ad-hoc procedure. Do not mix releases or let documentation expand authorization.

Begin with a capability gate and read-only audit. Record the current account,
Linux/libc/architecture, current proxy-variable classification, systemctl --user
availability, service name and active/enabled state, listeners, ssh/sshd
processes, active downloads, existing Mihomo/core/config/provider/rule state,
Shell startup path, and Git worktree state. Preserve unrelated and uncommitted
work. Collect only non-secret choices: pinned project release, pinned official
Mihomo release and published checksum, user-selected port, subscription
integration method, startup file, desired disabled policy, optional
VS Code Remote integration through http.proxy, and preserve/merge strategy. Report the audit and
concrete change/rollback scope. Existing explicit approval or installation authorization permits
continuing; ask only about unauthorized replacements, conflicts or unresolved choices.
Reuse suitable existing tools; do not replace system Node/npm/Codex or shadow them with new copies.
In shared mode read shared-runtime.md: install only personal Mihomo/controller; missing shared tools
go to the administrator, not a Node/Codex fallback. Verify normal/proxy PATH, the npm launcher's Node
and private CODEX_HOME. Preserve authentication, sessions and NVM; migrating defaults or old tools
requires explicit selection, never removal commands copied from another machine.
Follow deployment-contract.md for redacted audits; never return environment dumps, full argv or raw logs.

Sensitive information must never enter chat, command arguments, logs, diffs,
Git, or the final report. Read it locally only when the security guide permits.
Never use sudo, a system service, linger, cron, TUN, transparent/system proxy,
or another user's files or processes. Never terminate clients or downloads.
The installer never starts or enables services itself. An explicitly selected install-and-start
goal permits starting the user service after configuration and port checks, keeping it disabled.
Install-only preserves existing runtime state. For missing secrets, provide the restricted local
file/editing method and wait for user completion; never ask for secret values in chat.

Use only the reviewed checkout and documented deterministic installer. Obtain
the pinned released tag before running ./install.sh --suggest-port. Verify the
official release source, asset, checksum, libc compatibility, configuration,
authenticated loopback listener, default-direct Shell boundary, and the narrow
MATCH,DIRECT fallback selected by the user. Use the documented
CODEX_REMOTE_PAYLOAD compatibility path only when applicable. Do not invent a
parallel installer or replace safe argument arrays with evaluated strings.

Run the complete test suite and scripts/acceptance.sh exactly as documented,
including --expect-status when selected. Preserve real exit codes; when output
is piped, record PIPESTATUS rather than the last pipeline program. Record SHA256
evidence without printing private content. Classify every selected check as
PASS, FAIL, UNVERIFIED, or DEFERRED. Listener readiness is not proxy-node proof.
Follow deployment-contract.md for separate Codex executable, new-process, Listener/proxy-egress
and authorized minimal-model-request evidence; the user handles login. Missing evidence or
authorization is UNVERIFIED; DEFERRED requires explicit user postponement. Unselected is not passed.

On failure, stop within the authorized scope and use the documented rollback;
do not improvise destructive recovery. Finish with a redacted diff and final
acceptance report covering changes, versions and source identity, actual test
commands/exit codes, active/enabled preservation, backup and rollback command,
remaining UNVERIFIED/DEFERRED items, and user actions such as opening a new
terminal or reconnecting a long-lived client. This is the final acceptance
record; use deployment-contract.md's report fields and limit isolation claims to measured scope.
Never claim an unrun check passed.
```
