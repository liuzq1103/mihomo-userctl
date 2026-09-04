# Troubleshooting

## Installation stops at `doctor`

The installer treats the update as a transaction. It restores the previous
controller, modules, completion, non-secret configuration, `.bashrc`, and prior
managed-directory modes, then prints the retained backup path. Review its
mode-600 `manifest.tsv` and the redacted `doctor` output. Do not delete the
backup until the cause is understood. The installer never starts or enables
Mihomo during this process.

## After a power failure or reboot

The service is deliberately disabled and will not start automatically:

```bash
mihomoctl status
mihomoctl start
```

The Shell remains direct after a successful start. Use `with_proxy` for one
command.

## `proxy_status` says `inconsistent`

Some variables are missing, do not match the current credential file, or point
to an unavailable service:

```bash
proxy_off
mihomoctl doctor
```

Do not repair a few variables by hand.

## Service is active but readiness fails

```bash
mihomoctl doctor
mihomoctl logs --lines 100
PROXY_PORT=$(awk -F= '$1 == "MIHOMO_PORT" { print $2 }' \
  "$HOME/.config/mihomo/mihomo-shell.conf")
ss -lntp "sport = :$PROXY_PORT"
```

Typical causes are expired providers, unavailable nodes, listener credentials
or ports differing from `client.env`, or policy blocking the readiness URL.

## Port remains occupied

Perform only a read-only check. Do not kill unknown `ssh`/`sshd` or another
user's process:

```bash
PROXY_PORT=$(awk -F= '$1 == "MIHOMO_PORT" { print $2 }' \
  "$HOME/.config/mihomo/mihomo-shell.conf")
ss -lntp "sport = :$PROXY_PORT"
```

Stop the installation or change and ask the administrator for the smallest
ownership check needed.

## Codex remote startup fails

The compatibility hook fails closed. Manually start and verify the service,
then reconnect normally:

```bash
mihomoctl start
mihomoctl ready
mihomoctl doctor
```

`CODEX_REMOTE_PAYLOAD` is a locally verified compatibility hook, not a public,
stable Codex API. Re-test after Codex upgrades.

### A non-interactive `.bashrc` returns too early

Ubuntu commonly returns near the top of `.bashrc` for non-interactive shells.
Version `0.1.5` places or relocates the managed loader before that guard. Inspect
the order without exposing credentials:

```bash
grep -nE 'mihomo-userctl managed loader|case \$-|(^|[;[:space:]])return([;[:space:]]|$)' \
  "$HOME/.bashrc"
```

Never persist or invent `CODEX_REMOTE_PAYLOAD`. A compatibility test may supply
a non-sensitive value to one child process; the parent must remain direct.

### A proxied terminal still reuses a stale App Server

Environment changes do not alter an existing process. A Codex App Server that
predates installation can retain `0/8` proxy variables even when a new
`with_proxy codex` CLI has `8/8`, and the new CLI may reuse that server through
a local socket. Direct `SYN-SENT` attempts from the old server plus a local
listener connection from the new client are strong evidence of this split.

Exit and reconnect only the current user's Codex client. Stop a residual process
only after verifying its PID, UID, and parentage. Never use a server-wide
process-name kill or interfere with another user or an unknown SSH session.

## Terminal Codex works but the VS Code Remote extension fails

The VS Code Extension Host does not run `with_proxy`, and callers must not assume
it supplies `CODEX_REMOTE_PAYLOAD`. Follow the
[recommended VS Code Remote configuration](vscode-remote.md): set remote Machine
`http.proxy`, keep the authenticated settings file current-user-owned and mode
`600`, then reload the window. In the same-version tested extension, the Codex
child receives two uppercase variables (`proxy_vars=2/2`); the Extension Host
itself may remain `0/2`.

If it still fails, restart only the current user's remote VS Code connection and
verify that the new Codex child connects to `127.0.0.1:<user-port>`. Do not use a
global profile or `server-env-setup`, which broadens proxy inheritance beyond
the intended extension path.

## Confirm that `axel` is direct

Use the explicit child boundary when the parent Shell may already be proxied:

```bash
mihomoctl direct -- axel -n 10 'https://example.org/large-file'
```

To diagnose a long-lived current-user process without printing its environment:

```bash
mihomoctl diagnose process PID --json
mihomoctl diagnose name codex --json
```

`proxy_state=inconsistent` means some variables are absent or do not match the
current credential file. Restart or reconnect only that known current-user
application; the command never kills it.

After repairing a loader, credential file, or IDE setting, reconnect the
current-user client when the reported PID predates the change. Environment
variables cannot be injected into an already running process.

For custom-rule failures, run `mihomoctl rules status` first, then
`mihomoctl rules check`. Exit `2` with `config-unsupported-yaml` means the
custom-provider sections must be expressed in the documented block style; it
does not prove that the underlying configuration is invalid.
The command checks only the project contract; use the user's own Mihomo and
end-to-end evidence for complete routing behavior.

In the exact Shell that launches it:

```bash
proxy_status
env | grep -iE '^(http|https|all|no)_proxy='
```

Expect `shell=direct` and no variable output. Mihomo listening on a port does
not mean an ordinary download uses it.
