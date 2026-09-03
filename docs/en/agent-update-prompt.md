# Coding-agent update prompt

[中文](../zh-CN/agent-update-prompt.md) · [Update guide](update.md) · [Installation prompt](agent-install-prompt.md)

Replace the target tag and copy the following prompt into an agent with terminal
and file access to the intended Linux account. A chat-only model cannot execute it.
Never paste credentials or a subscription URL into the prompt.

```text
Update only my existing mihomo-userctl installation to this exact published
stable release: <vX.Y.Z>. Do the work and report evidence, not just a plan.

Read the repository constraints and docs/en/update.md, docs/en/acceptance.md, and
the existing installation metadata before writing. Preserve any unrelated or
uncommitted work. Establish the current account, installed executable, version,
source record, original XDG_CONFIG_HOME/XDG_DATA_HOME and Shell startup file.
Read sensitive files locally only; never quote their contents. If historical source
is unknown, say unknown. Do not invent a commit, checksum, signature verification,
successful test, rollback result, fresh Shell, or client reconnect.

The authorized scope is this account's mihomo-userctl code and managed loader.
Preserve the existing port, service name, mihomo-shell.conf, client.env, Listener
credentials, Mihomo core/config.yaml, subscriptions/providers/nodes/routing,
non-managed startup content and active/enabled state. Do not use sudo, configure
linger, enable/start/restart/stop the service, set system proxies, kill any process,
upgrade the Mihomo core, or affect other users. A stopped service must remain stopped.

Use the installed deterministic entry point:
  mihomoctl update --check
  mihomoctl update --version <vX.Y.Z> --dry-run
  mihomoctl update --version <vX.Y.Z>
Use the executable and paths established from the current install. Replace the
placeholder with my explicit target; never substitute main/latest, downgrade,
accept a moved tag, or choose another release silently. Check the official release
and protocol compatibility. If the target is not published or incompatible, explain
the exact blocker. A successful check finding an update has exit 0.

If this old installation lacks the update command/metadata, follow the one-time
migration section of update.md. Obtain and review an official source snapshot with
scripts/migrate.py, establish all original paths explicitly, inspect old managed
code for local customizations, and run that helper's --dry-run then actual migration
for my target. Generation metadata corruption requires the documented backup
recovery, not legacy migration. Do not guess paths, forge provenance, remove hashes,
or write a temporary replacement updater/install/rollback workflow. Missing evidence
or a material change of scope requires a specific question, not an invented default.

Use the installer's transaction backup and atomic generation flow. Do not copy
individual new modules over the installation. Keep the backup private. If an
operation fails or was interrupted, inspect the exact transaction/result and use
only its documented recovery command when recovery is needed. Do not overwrite
personal edits made after an update or restore a stale backup over a later update.
Capture each command's actual exit code; a pipeline or transcript summary alone
does not prove it. Never paste raw download errors, credentials, complete proxy
URLs, subscription URLs, or full private logs/configuration.

Use separate PASS, FAIL, UNVERIFIED and DEFERRED rows for:
1. Target versus actual installed version and immutable source identity.
2. Files installed and local integrity checks.
3. Settings, credentials, port, service name, startup content and service state preserved.
4. Listener binding, authenticated HTTP/SOCKS5H and no-authentication rejection.
5. Real target matched the intended proxy rule/node (not merely a listener connection).
6. A fresh Shell loaded the new module and the required compatibility hook.
7. Long-lived Codex/VS Code reconnected and the relevant new process was checked.

Reuse project acceptance checks without starting a stopped service. Do not claim
skipped probes passed. Do not claim an authenticated listener proves proxy routing.
Independent publisher archive checksum/signature verification is UNVERIFIED when
the flow only calculated a local hash. New terminals and client reconnects remain
DEFERRED until observed; do not kill clients to force them. Report every failed
check even when file installation succeeded. Exit 3 means files are installed but
acceptance is incomplete; exit 5 means files are installed with verifier FAIL.

Finish with a concise evidence table including exact commands and exit codes,
requested and installed versions, commit/archive identity and calculated hash,
verification actually performed, changed scope, preserved baseline, private backup
path, precise rollback command/result, remaining failures, and user actions for
new terminals or reconnects. Distinguish code tests, installation checks, Listener
checks, target routing and long-lived process checks. Do not write “all passed”
while any required item is FAIL, UNVERIFIED, DEFERRED, skipped or unrun.
```
