# Install Mihomo and configure the complete stack

This tutorial starts with a new Linux account: install Mihomo, create an
authenticated listener and personal routing policy, create a user service and
credential file, then install `mihomo-userctl`. The controller does not download
or update Mihomo for you.

Never commit subscription URLs, listener credentials, or `client.env`, paste
them into issues, or put them in command arguments. Port `17890` is only an
example; every user must choose a separate port.

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
ss -lntp 'sport = :17890'
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

## 3. Private directories and credentials

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

## 4. Create `config.yaml`

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
    port: 17890
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
  - name: Ai+
    type: url-test
    use: [subscription]
    url: https://www.gstatic.com/generate_204
    interval: 600
  - name: Academic Search
    type: select
    proxies: [Ai+, DIRECT]
  - name: Academic Access
    type: select
    proxies: [DIRECT, Ai+]

rules:
  - DOMAIN,sea-ad-single-cell-profiling.s3.amazonaws.com,DIRECT
  - DOMAIN-SUFFIX,github.com,Ai+
  - DOMAIN-SUFFIX,chatgpt.com,Ai+
  - MATCH,DIRECT
```

Do not add a global `mixed-port`, TUN, external controller, dashboard, or route
changes. Keep the listener authenticated and loopback-only, store provider
cache under the Mihomo home directory, use exact large-data DIRECT rules, and
retain final `MATCH,DIRECT`.

```bash
chmod 600 "$HOME/.config/mihomo/config.yaml"
"$HOME/.local/bin/mihomo" -t \
  -d "$HOME/.local/share/mihomo" \
  -f "$HOME/.config/mihomo/config.yaml"
```

## 5. Create the user service

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
ss -lntp 'sport = :17890'
```

Expect `active`, `disabled`, and only `127.0.0.1:17890`. Never run `enable`,
`loginctl enable-linger`, `sudo systemctl`, or create a system unit. Not starting
after a reboot is intentional.

## 6. Create `client.env`

Create `~/.config/mihomo/client.env` with exactly the listener's credentials:

```ini
MIHOMO_HTTP_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_HTTPS_PROXY='http://username:password@127.0.0.1:17890'
MIHOMO_ALL_PROXY='socks5h://username:password@127.0.0.1:17890'
```

```bash
chmod 600 "$HOME/.config/mihomo/client.env"
stat -c '%U %a %n' "$HOME/.config/mihomo/config.yaml" \
  "$HOME/.config/mihomo/client.env"
```

Percent-encode URL user information if you did not use hex-only credentials.
Do not source this file; `mihomo-userctl` parses it as data.

## 7. Install the controller

From the repository root:

```bash
bash tests/test.sh
bash tests/docs-test.sh
bash tests/secret-scan.sh
./install.sh --dry-run --port 17890 --bashrc "$HOME/.bashrc"
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
exec bash
```

The installer neither starts nor enables the service and does not overwrite an
existing `client.env`.

## 8. Acceptance tests

```bash
proxy_status
mihomoctl doctor
mihomoctl ready
systemctl --user is-enabled mihomo
```

Expect `shell=direct service=up endpoint=127.0.0.1:17890` and `disabled`.
An unauthenticated request must fail:

```bash
curl --fail --silent --show-error --max-time 10 \
  --proxy http://127.0.0.1:17890 https://example.com/ && echo 'ERROR: auth bypass'
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

## 9. Lifecycle and rollback

```bash
mihomoctl stop
mihomoctl start
mihomoctl restart
mihomoctl logs --lines 100
```

If the port does not release, `stop` reports an error and kills nothing. Restore
the timestamped `.bashrc` backup to roll back integration. Restore the exact
binary backup for a core rollback. Stop only your user service before restoring
configuration, re-run `mihomo -t`, and then `daemon-reload`.

Do not restore a Windows SSH reverse forward as the long-term solution, and do
not clean up an unrelated `127.0.0.1:7890` listener.
