# Install Mihomo and configure the complete stack

This tutorial starts with a new Linux account: install Mihomo, create an
authenticated listener and personal routing policy, create a user service and
credential file, then install `mihomo-userctl`. The controller does not download
or update Mihomo for you.

Never commit subscription URLs, listener credentials, or `client.env`, paste
them into issues, or put them in command arguments. There is no default port;
every user on the same server must choose a different one.

## 1. Read-only preflight

```bash
uname -s
uname -m
getconf LONG_BIT
ldd --version 2>&1 | head -n 1
bash --version | head -n 1
systemctl --user show-environment >/dev/null && echo 'systemd user manager: ready'
command -v curl gzip sha256sum ss journalctl openssl
env | grep -iE '^(http|https|all|no)_proxy=' || true
```

Stop if the user manager is unavailable, the candidate port has an unknown
owner, or a step would require administrator privileges.

## 2. Install an official Mihomo release

Choose a pinned version and CPU-compatible asset only from the official
[MetaCubeX/mihomo Releases](https://github.com/MetaCubeX/mihomo/releases).
The worked example below is pinned to `v1.19.30`, amd64-compatible asset, SHA256
`db214c7a2517e63c150d123178d16d102e03a241ccdae4e5e07ffbe9cf56c6f9`.
It is not a claim about the latest release. Other versions or architectures
must use the digest published for that exact official asset.

```bash
umask 077
install -d -m 700 "$HOME/.local/bin"
install -d -m 700 "$HOME/.local/share/mihomo/downloads"

MIHOMO_VERSION='v1.19.30'
MIHOMO_ASSET='mihomo-linux-amd64-compatible-v1.19.30.gz'
MIHOMO_SHA256='db214c7a2517e63c150d123178d16d102e03a241ccdae4e5e07ffbe9cf56c6f9'
MIHOMO_DOWNLOAD_DIR=$(mktemp -d "$HOME/.local/share/mihomo/downloads/install.XXXXXX")

curl --fail --location --proto '=https' --tlsv1.2 \
  "https://github.com/MetaCubeX/mihomo/releases/download/${MIHOMO_VERSION}/${MIHOMO_ASSET}" \
  --output "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET"
printf '%s  %s\n' "$MIHOMO_SHA256" "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET" \
  | sha256sum --check --strict
gzip --decompress --stdout "$MIHOMO_DOWNLOAD_DIR/$MIHOMO_ASSET" \
  > "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate"
chmod 755 "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate"
"$MIHOMO_DOWNLOAD_DIR/mihomo.candidate" -v
```

Install only after the checksum says `OK` and the candidate reports the expected
version. Back up an existing binary and atomically move the candidate on the
same filesystem:

```bash
if [[ -e "$HOME/.local/bin/mihomo" ]]; then
  cp -p "$HOME/.local/bin/mihomo" \
    "$HOME/.local/bin/mihomo.backup.$(date +%Y%m%d-%H%M%S)"
fi
mv "$MIHOMO_DOWNLOAD_DIR/mihomo.candidate" "$HOME/.local/bin/mihomo"
chmod 755 "$HOME/.local/bin/mihomo"
"$HOME/.local/bin/mihomo" -v
```

## 3. Obtain the controller source and select a per-user port

Choose a directory owned by your user, then obtain a reviewed release of this
project before invoking any project script. For example:

```bash
git clone --branch v0.1.2 --depth 1 \
  https://github.com/liuzq1103/mihomo-userctl.git "$HOME/mihomo-userctl"
cd "$HOME/mihomo-userctl"
git remote -v
git describe --tags --exact-match
```

If the destination already exists, inspect and reuse it instead of overwriting
it. Do not use `curl | bash`. The remaining commands in this guide assume the
current directory is this verified checkout.

From the `mihomo-userctl` repository root, request a read-only candidate:

```bash
PROXY_PORT=$(./install.sh --suggest-port)
printf 'candidate=%s\n' "$PROXY_PORT"
ss -lnt "sport = :$PROXY_PORT"
```

The helper searches `20000-29999`, starting from a position derived from the
current UID. It neither binds nor reserves the port. Confirm it with the user,
coordinate with other users of the same server, and re-run `ss` immediately
before starting Mihomo. Different users cannot bind the same loopback address
and port. Authentication reduces misuse but does not solve binding conflicts.

You may replace `PROXY_PORT` with another user-selected value in `1024-65535`.
Avoid conventional ports used by existing proxy software and any port already
listed by `ss`.

## 4. Private directories and credentials

```bash
install -d -m 700 "$HOME/.config/mihomo"
install -d -m 700 "$HOME/.local/share/mihomo"
install -d -m 700 "$HOME/.local/share/mihomo/proxy_providers"
install -d -m 700 "$HOME/.local/share/mihomo/backups"
install -d -m 700 "$HOME/.config/systemd/user"
```

Generate a local random username and at least 32 random password bytes. Hex is
recommended because it avoids URL-encoding mistakes:

```bash
openssl rand -hex 8
openssl rand -hex 32
```

Place the output directly into mode-600 local files. Never paste it back into a
chat or public log.

## 5. Create `config.yaml`

Create `~/.config/mihomo/config.yaml`, replace the three private placeholders,
and immediately set mode `600`:

```yaml
allow-lan: false
mode: rule
log-level: info
ipv6: false

listeners:
  - name: authenticated-loopback
    type: mixed
    listen: 127.0.0.1
    port: PORT_SELECTED_BY_USER
    udp: false
    users:
      - username: replace-with-local-username
        password: replace-with-local-password

proxy-providers:
  subscription:
    type: http
    url: "replace-with-private-subscription-url"
    path: ./proxy_providers/subscription.yaml
    interval: 86400
    proxy: DIRECT
    size-limit: 5242880
    health-check:
      enable: true
      url: https://www.gstatic.com/generate_204
      interval: 600

proxy-groups:
  - name: Proxy
    type: url-test
    use: [subscription]
    url: https://www.gstatic.com/generate_204
    interval: 600

rules:
  - DOMAIN-SUFFIX,github.com,Proxy
  - DOMAIN-SUFFIX,chatgpt.com,Proxy
  - MATCH,DIRECT
```

Do not add a global `mixed-port`, TUN, external controller, dashboard, or route
changes. Keep the listener authenticated and loopback-only, store provider
cache under the Mihomo home directory, and retain final `MATCH,DIRECT`. The
domains and `Proxy` group above are neutral examples, not project policy.
Dataset, research-site, provider-node, and other custom routing requirements
belong only in each user's own Mihomo configuration.

```bash
chmod 600 "$HOME/.config/mihomo/config.yaml"
"$HOME/.local/bin/mihomo" -t \
  -d "$HOME/.local/share/mihomo" \
  -f "$HOME/.config/mihomo/config.yaml"
```

Replace `PORT_SELECTED_BY_USER` with the confirmed numeric value before running
the config test.

## 6. Create the user service

Create `~/.config/systemd/user/mihomo.service`:

```ini
[Unit]
Description=User-level Mihomo proxy
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=%h/.local/bin/mihomo -d %h/.local/share/mihomo -f %h/.config/mihomo/config.yaml
Restart=on-failure
RestartSec=5s
NoNewPrivileges=true
PrivateTmp=true
UMask=0077

[Install]
WantedBy=default.target
```

```bash
chmod 644 "$HOME/.config/systemd/user/mihomo.service"
systemctl --user daemon-reload
systemctl --user start mihomo
systemctl --user is-active mihomo
systemctl --user is-enabled mihomo
ss -lntp "sport = :$PROXY_PORT"
```

Expect `active`, `disabled`, and only `127.0.0.1:$PROXY_PORT`. Never run `enable`,
`loginctl enable-linger`, `sudo systemctl`, or create a system unit. Not starting
after a reboot is intentional.

## 7. Create `client.env`

Create `~/.config/mihomo/client.env` with exactly the listener's credentials:

```ini
MIHOMO_HTTP_PROXY='http://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
MIHOMO_HTTPS_PROXY='http://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
MIHOMO_ALL_PROXY='socks5h://username:password@127.0.0.1:PORT_SELECTED_BY_USER'
```

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
stat -c '%U %a %n' "$HOME/.config/mihomo/config.yaml" \
  "$HOME/.config/mihomo/client.env"
```

Percent-encode URL user information if you did not use hex-only credentials.
Do not source this file; `mihomo-userctl` parses it as data.

Replace `PORT_SELECTED_BY_USER` with the same confirmed numeric value. The three
URLs and the Mihomo listener must agree exactly.

## 8. Install the controller

From the repository root:

```bash
bash tests/test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
./install.sh --dry-run --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
./install.sh --port "$PROXY_PORT" --bashrc "$HOME/.bashrc"
exec bash
```

The installer neither starts nor enables the service and does not overwrite an
existing `client.env`. Before changing active files it creates a mode-700
transaction backup under `~/.local/share/mihomo-userctl-backups/`. If the final
`mihomoctl doctor` fails, it restores the previous controller, modules,
completion, non-secret configuration, and `.bashrc`; the backup is retained for
inspection.

## 9. Acceptance tests

```bash
proxy_status
mihomoctl doctor
mihomoctl ready
systemctl --user is-enabled mihomo
```

Expect `shell=direct service=up endpoint=127.0.0.1:<selected-port>` and `disabled`.
An unauthenticated request must fail:

```bash
curl --fail --silent --show-error --max-time 10 \
  --proxy "http://127.0.0.1:$PROXY_PORT" https://example.com/ && echo 'ERROR: auth bypass'
```

An opted-in child command must work without changing the parent:

```bash
with_proxy curl --fail --silent --show-error https://example.com/ >/dev/null
proxy_status
```

The second command must still report direct. For a dedicated SOCKS5H test, use
a temporary child Shell, run `proxy_on`, clear only its HTTP/HTTPS variables,
and let curl use `ALL_PROXY`; exit the child afterward.

Before ordinary `axel` or S3 downloads, confirm `proxy_status` is direct.
A listening Mihomo service does not itself capture their traffic.

### Optional: VS Code Remote

A working terminal `with_proxy codex` and Codex Remote hook do not imply that
the VS Code Extension Host inherits the same environment. If the Codex extension
is required in VS Code Remote, continue with the
[recommended VS Code Remote configuration](vscode-remote.md). This is a
separate opt-in because it stores an authenticated URL in remote Machine
Settings and can affect other extensions that honor the setting; ordinary
shells and large downloads remain direct.

## 10. Lifecycle and rollback

```bash
mihomoctl stop
mihomoctl start
mihomoctl restart
mihomoctl logs --lines 100
```

If the port does not release, `stop` reports an error and kills nothing. To roll
back a successful controller install, restore the exact files from the backup
path printed by `install.sh`; do not copy the whole directory blindly. Restore
the exact binary backup for a core rollback. Stop only your user service before
restoring configuration, re-run `mihomo -t`, and then `daemon-reload`.

Rollback must not introduce a new external tunnel or clean up an unrelated
listener. Treat anything outside the current user's declared scope as untouched.
