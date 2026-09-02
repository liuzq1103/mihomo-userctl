# Recommended VS Code Remote configuration

Use this guide when Mihomo and `mihomo-userctl` are already installed in a
remote Linux account, `with_proxy codex` works in a terminal, but the Codex
extension in VS Code Remote still times out.

## Why the terminal works while the extension fails

The launch paths are independent:

```text
terminal
  -> with_proxy codex
     -> Codex inherits eight proxy variables

VS Code Remote
  -> Extension Host
     -> Codex extension starts its bundled app-server
```

The Extension Host does not run `with_proxy`, and installing
`mihomo-userctl` does not automatically proxy it. `CODEX_REMOTE_PAYLOAD` is a
separate, locally verified compatibility hook for Codex Remote; do not assume
that the VS Code extension supplies it.

Official OpenAI documentation identifies Codex App Server as the interface
used by rich clients such as the VS Code extension and explains that the CLI
and IDE extension share Codex configuration layers:

- [Codex App Server](https://learn.chatgpt.com/docs/app-server)
- [Basic Codex configuration](https://learn.chatgpt.com/docs/config-file/config-basic)

During v0.1.5 acceptance, extension build `26.825.51511` was observed reading
VS Code's `http.proxy` and supplying `HTTP_PROXY` and `HTTPS_PROXY` to the
app-server it launches. This is version-specific observed behavior, not a
stable OpenAI interface guaranteed by this project. Re-test it after extension
upgrades.

## Prerequisites

Use ordinary SSH to start and verify the user service before connecting VS
Code Remote:

```bash
mihomoctl start
mihomoctl ready
```

The service must remain `disabled`. Do not enable it or add linger, cron, or a
system-level service just to make the extension start automatically.

## Back up Remote Machine Settings

Server-side Machine Settings for VS Code Remote are stored at:

```text
~/.vscode-server/data/Machine/settings.json
```

Back up the file and tighten its permissions first:

```bash
settings="$HOME/.vscode-server/data/Machine/settings.json"
backup_dir="$HOME/.config/mihomo/backups/vscode"
timestamp=$(date +%Y%m%d-%H%M%S)

install -d -m 700 "$backup_dir"
cp -p -- "$settings" "$backup_dir/settings.json.before-proxy.$timestamp"
chmod 600 \
  "$backup_dir/settings.json.before-proxy.$timestamp" \
  "$settings"
```

If the file is absent, let VS Code Remote create Machine Settings or create a
valid JSON object owned by the current user with mode `600`. Never overwrite
existing settings.

## Add the recommended settings

Open these files locally on the server:

```text
~/.config/mihomo/client.env
~/.vscode-server/data/Machine/settings.json
```

Read the complete `MIHOMO_HTTPS_PROXY` value from `client.env` and place it in
the top-level `http.proxy` setting. Never paste that value into chat, a command
line, logs, screenshots, Git, or a report.

Structure example:

```json
{
  "http.proxy": "http://<user>:<password>@127.0.0.1:<port>",
  "http.proxyStrictSSL": true
}
```

The angle-bracket text is a placeholder. The real value must exactly match the
current account's mode-600 `client.env`. Preserve every existing key and valid
JSON/JSONC syntax. Never set `http.proxyStrictSSL` to `false`.

After saving, verify permissions without printing the file:

```bash
chmod 600 "$HOME/.vscode-server/data/Machine/settings.json"
stat -c 'owner=%U mode=%a path=%n' \
  "$HOME/.vscode-server/data/Machine/settings.json"
```

Expect current-user ownership and mode `600`.

## Restart and verify

First run this from the VS Code command palette:

```text
Developer: Reload Window
```

The Codex extension's restart command is also suitable. See the
[OpenAI MCP documentation](https://learn.chatgpt.com/docs/extend/mcp) for the
documented extension-restart flow after configuration changes.

If the extension still reuses an old process, use:

```text
Remote-SSH: Kill VS Code Server on Host...
```

Select only the current account's own host connection and ensure no important
task is active. Never terminate another user's processes, SSH sessions, or VS
Code Server.

Find the newest extension Codex process:

```bash
vscode_codex_pid=$(
  pgrep -n -f \
    "$HOME/.vscode-server/extensions/openai.chatgpt-.*/bin/linux-x86_64/codex"
)
printf 'vscode_codex_pid=%s\n' "$vscode_codex_pid"
```

Check only variable presence, without exposing the authenticated URL:

```bash
count=0
for name in HTTP_PROXY HTTPS_PROXY; do
  grep -zq "^${name}=" \
    "/proc/$vscode_codex_pid/environ" 2>/dev/null &&
    count=$((count + 1))
done
printf 'proxy_vars=%s/2\n' "$count"
```

The currently observed result is:

```text
proxy_vars=2/2
```

Do not require `8/8` here. Terminal `proxy_on` manages eight upper- and
lower-case variables, while the current VS Code extension supplies two
upper-case HTTP proxy variables to its app-server. The Extension Host itself
may remain `0/8`.

Finally inspect the real route:

```bash
ss -ntp | grep -E "pid=${vscode_codex_pid}|127\.0\.0\.1:<port>"
mihomoctl logs --follow
```

Replace `<port>` with this account's configured port. Codex should connect to
the loopback listener, and ChatGPT/OpenAI domains in Mihomo logs should select
the intended user policy.

## Security and scope

- `settings.json` now contains listener credentials. It must remain owned by
  the current user with mode `600`.
- `http.proxy` is a remote VS Code Machine Setting. Other extensions that honor
  it may also use Mihomo.
- Ordinary SSH shells, new terminals, `axel`, S3, and large downloads remain
  protected by the direct-by-default `.bashrc` model.
- Do not export proxy variables globally from `.profile` and do not fabricate
  `CODEX_REMOTE_PAYLOAD`.
- A broad `server-env-setup` injection is not needed for this verified path.
- Never inspect, modify, or terminate another user's VS Code or Codex process
  on a shared server.

## Long-lived process trap

Environment variables are inherited only when a process starts. A Codex
app-server that predates installation or a proxy change cannot acquire the new
environment automatically. During one real incident, a new CLI process reached
Mihomo but reused an old app-server with `0/8` proxy variables. The stale server
made direct connections that remained in `SYN-SENT` until requests timed out.

Close or restart only the current user's Codex/VS Code connection, then verify
the new PID. Never kill server-wide `codex`, `ssh`, or `sshd` processes by name,
and never touch another user's processes.

## Rollback

Remove only the settings added by this guide:

```json
"http.proxy"
"http.proxyStrictSSL"
```

Alternatively restore the timestamped backup. Keep the restored file at mode
`600`, reload the VS Code window, and confirm that new extension processes no
longer contain proxy variables. Rolling back VS Code settings must not stop
Mihomo or change `.bashrc`, subscriptions, nodes, or another user's files.
