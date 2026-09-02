# Copyable installation prompt for coding agents

Use this prompt with a coding agent that can read files, run terminal commands,
connect to the target Linux account over SSH when needed, and pause for your
reply. A chat-only model cannot perform the installation; it can only explain
the manual steps.

Copy the text block below into a new agent task. Never append a subscription
URL, password, token, private key, or other credential to the prompt or chat.

```text
Install Mihomo and mihomo-userctl for my current, unprivileged Linux account.
The required end state is a manually started, disabled systemd user service; an
authenticated Mixed listener bound only to 127.0.0.1 on a user-selected unique
port; direct-by-default new shells; and opt-in proxying through proxy_on,
with_proxy, or the locally verified CODEX_REMOTE_PAYLOAD compatibility hook for
Codex Remote. Work only in my account and do not affect other users.

Follow this protocol exactly.

Phase 1 — capability gate, read-only audit, and plan

1. Before doing anything else, confirm that you can:
   - read and inspect files without exposing sensitive values;
   - run terminal commands on the target Linux account;
   - use SSH if the target is remote;
   - pause, ask questions in this conversation, and wait for my reply.
   If any required capability is unavailable, do not modify anything and do not
   claim installation success. Stop after giving exact manual instructions for
   the missing portion.
2. Perform only read-only discovery. Identify the current user, HOME, CPU
   architecture, Linux distribution, libc compatibility, Bash version, systemd
   user-manager availability, required commands, current proxy variables,
   existing Mihomo files and user service, shell startup file, active listeners,
   active downloads and relevant SSH sessions, candidate project checkout
   directory, and any files that would be modified. Do not use sudo, root,
   another account, a system service, linger, cron, TUN, a controller, or system
   proxy settings. Do not stop processes, change ports, start services, or write
   files in this phase. Treat a pre-existing 127.0.0.1:7890 and every unknown
   listener as out of scope unless I separately authorize it. Other users are
   always out of scope.
3. Ask me for non-sensitive choices through ordinary conversation, at most
   three concise questions at a time. Confirm the checkout path, shell startup
   file, readiness URL, service name, subscription integration method,
   existing-configuration preserve/merge strategy, policy choices, and a final
   per-user port. There is no default port. Users on the same server must select
   different ports. Do not ask me to paste any sensitive information into chat.
4. Sensitive information must stay on the target machine. Generate listener
   credentials locally without printing them, or instruct me to enter a
   subscription URL or existing credential directly into a current-user-owned,
   mode-600 file. Receive only the file path. Check ownership, mode, and required
   structure without echoing values into commands, tool output, logs, diffs, or
   the final report. If the available tools cannot guarantee this boundary,
   pause and provide a manual local insertion step instead.
5. Present a complete implementation plan before changing anything. List the
   exact files, commands, backups, validation steps, failure stops, and rollback
   procedure. Resolve ambiguity first. Wait for my explicit approval of that
   plan. Silence, an earlier request to inspect, or approval of a different
   scope is not permission to modify files.

Phase 2 — implementation after explicit approval

6. Proceed only after I explicitly approve the Phase 1 plan. Stay within that
   approved scope. Before each group of writes, create a timestamped,
   current-user-only backup and verify that it is recoverable. Never authenticate
   as another user or stop unknown listeners, ssh/sshd processes, active
   downloads, or unrelated sessions.
7. Obtain the mihomo-userctl repository before invoking any of its scripts:
   clone or inspect the user-approved checkout, verify the origin is
   https://github.com/liuzq1103/mihomo-userctl, check out a pinned released tag,
   and read its README, setup guide, security guide, and installer help. Never
   pipe a network download directly into a shell.
8. Only after the verified checkout exists, run ./install.sh --suggest-port.
   Treat its output as a candidate, not a reservation. Compare it with all
   visible listeners, ask me to confirm the final port, and recheck immediately
   before binding. Do not inspect, stop, or repurpose an unknown listener.
9. Follow docs/en/setup.md from the Mihomo installation step onward. Download
   Mihomo only from the official release source, pin the release asset, verify
   the published checksum before installation, validate every candidate config,
   and use atomic replacement. Keep the listener authenticated, loopback-only,
   and on the confirmed port. Keep TUN and external controller disabled. Keep
   MATCH,DIRECT as the final routing fallback unless my separately reviewed
   policy explicitly says otherwise. Treat existing policy rules, subscriptions,
   providers, and node data as user-owned; do not replace them without a
   redacted diff and my separate explicit approval.
10. When the approved plan requires them, create current-user-only provider and
    cache paths and a systemd user unit. Store non-sensitive shell settings in
    mihomo-shell.conf and authenticated local endpoint URLs in mode-600
    client.env. Do not place subscription URLs, credentials, provider contents,
    or private node data in Git, chat, command arguments, logs, screenshots,
    diffs, or reports.
11. In the verified checkout, first run its documented Bash syntax checks,
    ShellCheck when available, complete test suite, documentation/link tests,
    sensitive-information scan, and whitespace check; stop on any failure. Then
    run the deterministic control-layer workflow: ./install.sh --dry-run --port
    PORT, followed by ./install.sh --port PORT --bashrc PATH. Substitute only the
    values approved in Phase 1. Do not enable the service. Do not modify files
    outside the current user's approved paths.
12. Verify the installed Shell integration without redefining or persistently
    exporting CODEX_REMOTE_PAYLOAD. Every ordinary Shell load must call
    proxy_off first. When the remote launcher supplies a non-empty
    CODEX_REMOTE_PAYLOAD, the module must automatically run the equivalent of
    `proxy_on || exit 1`: it uses the authenticated user listener when ready and
    fails closed when unavailable. It must never start Mihomo automatically.
    Document that this variable is a locally verified compatibility hook, not a
    public or stable API, and re-test it after remote-client upgrades.
13. Validate configuration syntax before any service start. A test start must
    use systemctl --user only. Confirm systemctl --user is-enabled mihomo remains
    disabled. Do not enable linger or create any automatic startup mechanism.
14. Perform final acceptance tests without exposing sensitive information:
    authenticated HTTP and SOCKS5H succeed; unauthenticated requests fail; the
    listener is only 127.0.0.1 on the chosen port; new shells are direct;
    proxy_on and proxy_off work; with_proxy affects only its child shell; the
    CODEX_REMOTE_PAYLOAD path becomes proxied when the service is ready, fails
    clearly rather than falling back to direct when unavailable, and never
    starts the service; normal axel, S3, and large downloads remain direct;
    service stop releases the port; logs and the project checkout contain no
    sensitive values; and no other user or unrelated listener was changed. Use
    the isolated project test harness for failure paths when stopping a live
    service could interrupt current work.
15. If a write or acceptance test fails, stop, restore the affected files from
    the verified backup when safe, and report the remaining state. Never kill an
    unknown process, broaden permissions, use sudo, or silently weaken a check.
16. Finish with a redacted report containing: versions and verified checksums;
    chosen port; files changed; backup locations; service active/enabled state;
    acceptance results; any skipped or failed check; and exact rollback steps.
    Do not include any sensitive value.
```

The prompt is an orchestration contract, not a replacement for the repository's
deterministic installer and tests. Review the agent's Phase 1 plan before
granting approval.
