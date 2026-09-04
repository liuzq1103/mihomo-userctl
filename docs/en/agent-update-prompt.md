# Coding-agent update prompt

[中文](../zh-CN/agent-update-prompt.md) · [Update guide](update.md) · [Acceptance](acceptance.md) · [Architecture](architecture.md)

Replace the target tag and give this prompt to an agent with terminal and file
access to the installed Linux account. Do not paste credentials into it.

```text
Update only this account's existing mihomo-userctl installation to the exact
published stable release <vX.Y.Z>. Complete the update and report evidence.

Before writing, read the repository constraints, docs/en/update.md,
acceptance.md, architecture.md, security.md, and the current installation
metadata. Treat those as normative; do not duplicate the installer, updater,
validation, or rollback logic.

Audit the installed version and immutable source identity, original HOME/XDG
and startup paths, managed-file integrity, backup state, service active/enabled
state, and unrelated work. Sensitive values stay local and are never quoted.
Preserve configuration, credentials, port, service name, Mihomo core and data,
non-managed startup content, and every unrelated file and process. Do not use
sudo, change service state, upgrade Mihomo, or reconnect/terminate clients.

Run and record the real exit code of:
  mihomoctl update --check
  mihomoctl update --version <vX.Y.Z> --dry-run
  mihomoctl update --version <vX.Y.Z>

Use scripts/migrate.py only when the installed metadata is genuinely from the
documented legacy layout. Never substitute main/latest, accept a moved tag,
downgrade silently, copy individual modules, or invent provenance. Use the
existing transaction and exact private backup for recovery.

Run the documented complete tests and acceptance checks without starting a
stopped service. Report each selected item as PASS, FAIL, UNVERIFIED, or
DEFERRED, including version/source, runtime integrity, preserved settings,
active/enabled state, listener/authentication, target routing, fresh Shell, and
long-lived clients. Listener readiness is not node selection. New Shells and
client reconnects remain DEFERRED until the user performs and verifies them.

Finish with exact commands and exit codes, requested/installed versions, commit
and archive identity, calculated digest, changed and preserved scope, backup,
precise rollback command, remaining failures, and user actions. Never claim
skipped or unrun work passed.
```
