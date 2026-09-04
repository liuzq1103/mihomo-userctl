# Coding-agent installation prompt

[中文](../zh-CN/agent-install-prompt.md) · [Setup](setup.md) · [Architecture](architecture.md) · [Security](security.md) · [Acceptance](acceptance.md)

Copy the prompt below into an agent that has terminal and file access to the
intended Linux account. Replace placeholders only with non-secret choices; keep
credentials and subscription URLs on the target machine.

```text
Install mihomo-userctl for this ordinary Linux account from an exact reviewed,
pinned released tag. Complete the work and return evidence, not only a plan.

Before any write, read the repository constraints and these normative documents
in full: docs/en/setup.md, architecture.md, security.md, acceptance.md,
troubleshooting.md, and vscode-remote.md when that integration is selected.
Follow those documents instead of copying their implementation details into a
new ad-hoc procedure.

Begin with a capability gate and read-only audit. Record the current account,
Linux/libc/architecture, current proxy-variable classification, systemctl --user
availability, service name and active/enabled state, listeners, ssh/sshd
processes, active downloads, existing Mihomo/core/config/provider/rule state,
Shell startup path, and Git worktree state. Preserve unrelated and uncommitted
work. Collect only non-secret choices: pinned project release, pinned official
Mihomo release and published checksum, user-selected port, subscription
integration method, startup file, desired disabled policy, optional
VS Code Remote integration through http.proxy, and preserve/merge strategy. Obtain
explicit approval for the concrete changes and rollback before writing.

Sensitive information must never enter chat, command arguments, logs, diffs,
Git, or the final report. Read it locally only when the security guide permits.
Never use sudo, a system service, linger, cron, TUN, transparent/system proxy,
or another user's files or processes. Never terminate clients or downloads.
Mihomo must never start automatically; the documented user service remains
disabled unless the user explicitly chooses otherwise.

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

On failure, stop within the authorized scope and use the documented rollback;
do not improvise destructive recovery. Finish with a redacted diff and final
acceptance report covering changes, versions and source identity, actual test
commands/exit codes, active/enabled preservation, backup and rollback command,
remaining UNVERIFIED/DEFERRED items, and user actions such as opening a new
terminal or reconnecting a long-lived client. This is the final acceptance
record; never claim an unrun check passed.
```
