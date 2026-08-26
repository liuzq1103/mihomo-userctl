# Troubleshooting

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
ss -lntp 'sport = :17890'
```

Typical causes are expired providers, unavailable nodes, listener credentials
or ports differing from `client.env`, or policy blocking the readiness URL.

## Port remains occupied

Perform only a read-only check. Do not kill unknown `ssh`/`sshd` or another
user's process:

```bash
ss -lntp 'sport = :17890'
```

Stop the migration and ask the administrator for the smallest ownership check
needed.

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

## Confirm that `axel` is direct

In the exact Shell that launches it:

```bash
proxy_status
env | grep -iE '^(http|https|all|no)_proxy='
```

Expect `shell=direct` and no variable output. Mihomo listening on a port does
not mean an ordinary download uses it.
