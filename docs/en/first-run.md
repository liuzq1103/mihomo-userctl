# First use after installing Codex proxy support

[中文](../zh-CN/first-run.md) · [Setup](setup.md) · [Troubleshooting](troubleshooting.md)

Installation is not proof of Codex connectivity. Finish your private subscription/configuration,
confirm Codex is installed, and handle sign-in yourself. `mihomoctl codex` and `mihomoctl diagnose codex`
are additions in v0.5.0. On released v0.4.0, use `with_proxy codex` in a
loaded Bash shell or `mihomoctl exec -- codex`, and `mihomoctl diagnose name codex` for process inspection.

## Choose your actual entry point

| How you use Codex | Entry point |
| --- | --- |
| Ordinary SSH/Bash terminal | `mihomoctl codex`: HTTP readiness check and existing-process advice |
| Codex Remote with a verified working hook | Connect normally; reconnect and verify after proxy changes |
| VS Code Remote extension | Follow [VS Code integration](vscode-remote.md); terminal success is not extension acceptance |
| Scripts or other tools | `mihomoctl exec -- COMMAND`, or `with_proxy COMMAND` in a loaded Bash shell |

The `.bashrc` loader defines functions and loads a conditional hook. Ordinary shells clear proxy
variables; automatic proxy entry requires the remote launcher to supply nonempty `CODEX_REMOTE_PAYLOAD`.
Typing plain `codex` in an ordinary terminal therefore has no automatic proxy guarantee. Do not persist
that variable or turn on global proxying to fix one app. This project does not replace or alias `codex`.

## First terminal check

Open a new terminal. If `mihomoctl` is not on PATH, use `~/.local/bin/mihomoctl` and correct the PATH
setup from installation. This executable also works outside Bash, without sourcing `.bashrc`.

```bash
mihomoctl doctor --offline
mihomoctl start
mihomoctl codex
```

Finish subscription/configuration before starting. If the service is already running, go directly to
the launcher. The service defaults to disabled and needs manual startup after a machine reboot.
The launcher never starts it automatically. Pass Codex arguments after `--`, e.g. `mihomoctl codex -- resume`.
Arguments and exit status are preserved. It uses the executable on PATH, not a shell alias/function,
and does not install tools or log you in.

The launcher requests the configured READY URL through the proxy before starting Codex. Failure blocks
this launch with recovery guidance. Success proves that HTTP check only. After login, send one minimal
message through your actual client when you authorize a model request, and confirm a complete reply.
API requests can incur charges; diagnostics never initiate a model request automatically.

## Locate a WebSocket failure

| Symptom | Next check |
| --- | --- |
| Command not found | Selected tool installation and PATH, not networking |
| Doctor/readiness or proxy authentication fails | Service, private port, matching credentials, subscription and node |
| HTTP passes but WebSocket handshake/stream fails | Actual outbound process, target route/node, TLS/certificates and intermediaries; HTTP alone is insufficient |
| Local Unix socket or localhost connection fails | Owning client/app-server lifecycle; local connections should bypass the proxy |
| 401/403 or account/quota error | Authentication, permissions or gateway policy at the failing layer; do not repeatedly clear credentials |
| Old errors persist after changing proxy configuration | Reconnect your own old clients and check possible process reuse below |

WebSockets can carry client-to-app-server traffic or remote app-server connections; identify the
failing layer rather than assuming every error is model egress. See the [official connection guide](https://learn.chatgpt.com/docs/app-server).
Successful curl, eight environment variables or a transport fallback is not proof of a working target
WebSocket. Do not apply unverified version-specific disable-WebSocket settings or disable TLS checks.

## Existing processes and safe recovery

```bash
mihomoctl diagnose codex
# For agent-readable output:
mihomoctl diagnose codex --json
```

This offline, read-only snapshot reports the current environment and same-user Codex candidates by
PID, role and proxy environment classification. It never emits argv, subscriptions or proxy passwords.
`direct` means no proxy variables were read, not proof of direct model traffic; `inconsistent` means
the environment differs from current private proxy settings. A match is not WebSocket verification.
No candidates may simply mean Codex is not running. Unreadable/changing processes remain unverified.
Custom launchers may be missed; this command does not correlate Unix peers or prove service reuse.
The overall result is always `UNVERIFIED` with exit code `2`, even without issues; this is not a failed model request.

1. Save work and normally quit or disconnect your own Codex clients.
2. Run the snapshot again. A remaining, old or `direct` process may serve another active session of yours.
3. Before manually stopping anything, confirm the current PID, owner, client/session association and
   recheck immediately before stopping to avoid PID reuse. Stop only the confirmed unused process normally.
   Never use broad pkill/killall, or delete sockets, `~/.codex`, credentials or session data.
4. Reconnect using the appropriate entry above, verify the actual service environment, and make one
   authorized minimal request.

Restarting Mihomo, opening a terminal or sourcing `.bashrc` cannot change an old app-server environment.
The launcher advises about risk but neither stops processes nor promises to repair existing services.
Use [detailed troubleshooting](troubleshooting.md) for missing correlation evidence instead of reinstalling blindly.

## What installation handoff must include

Report the actual subscription location and completion, service state, chosen startup entry, whether
old clients need reconnecting, actual request evidence and pending login/verification separately.
Controller installed, HTTP proxy ready and model reply received are three different milestones.
