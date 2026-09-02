# Security model

## Terminology

- **Sensitive information** includes subscription URLs, usernames, passwords,
  tokens, and complete proxy URLs.
- **Credentials** are values that authenticate or authorize access; here they
  primarily mean the listener username and password.
- **Keys** means actual cryptographic or API keys. Subscription URLs, passwords,
  and tokens are not all described as keys.

## Threats in scope

The project addresses accidental paid-proxy use by large downloads, inherited
proxy variables, executable configuration, weak credential permissions, secret
leakage in arguments or diagnostics, and accidental interference with unknown
ports or other users. It also avoids hidden global effects from TUN, routing,
system proxy settings, linger, cron, and root services.

It cannot provide strict isolation between Linux UIDs. Loopback belongs to the
host. Authentication reduces accidental use, but strict UID isolation requires
administrator-managed firewall policy and is outside this project.

## Direct by default

On load, the Shell module clears these eight variables:

```text
http_proxy https_proxy all_proxy no_proxy
HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY
```

Running Mihomo alone captures nothing because there is no TUN or transparent
proxy. An application must explicitly use the endpoint.

## Configuration is data

`mihomo-shell.conf` and `client.env` are never sourced or evaluated. The parser
accepts only fixed keys and simple quoted or unquoted values. Files must belong
to the current UID and be mode `600`; module directories cannot be writable by
group or others. Endpoint URLs must use `127.0.0.1` and the configured port.

Environment variables remain visible to sufficiently privileged tools and to
some processes under the same UID. Do not share one Unix account with untrusted
people.

## VS Code Remote credential boundary

The optional remote Machine `http.proxy` contains a complete authenticated URL,
so `~/.vscode-server/data/Machine/settings.json` is sensitive. It and every
backup must be current-user-owned and mode `600`; never print the URL while
configuring or testing it.

This setting is narrower than a global Shell proxy but is not necessarily
Codex-only: other remote extensions that honor VS Code `http.proxy` may use it.
Ordinary SSH shells, `axel`, and S3 remain direct. Do not solve extension
connectivity by exporting the proxy from `.profile`, a global environment, or
`server-env-setup`. See the
[recommended VS Code Remote configuration](vscode-remote.md).

## Conservative stopping

`mihomoctl stop` calls only `systemctl --user stop` for the validated service
name and waits for the configured port to be released. It never runs `kill` or
`pkill`, guesses an owner, stops SSH, uses sudo, or touches unrelated ports.

Never post subscriptions, full proxy URLs, credentials, or unredacted logs in
a public issue. Follow the private reporting instructions in
[SECURITY.md](../../SECURITY.md).
