# Migrate from a large `.bashrc` implementation

## Before changing anything

Record the current service, enablement, configured listener, Shell status, and
active downloads. Pause if the port owner is unknown, credentials are not mode
`600`, multiple legacy blocks exist, or a required step would interrupt work.

```bash
systemctl --user is-active mihomo
systemctl --user is-enabled mihomo
ss -lntp 'sport = :17890'
proxy_status
```

Run the dry-run first:

```bash
./install.sh --dry-run --port 17890 --bashrc "$HOME/.bashrc"
```

The installer recognizes only one managed loader or the precisely supported
legacy block. Ambiguous layouts stop; it never removes every line containing
`proxy`. Backups are tightened to mode `600`.

Install and open a genuinely new session:

```bash
./install.sh --port 17890 --bashrc "$HOME/.bashrc"
type mihomoctl proxy_on proxy_off proxy_status with_proxy
proxy_status
mihomoctl ready
with_proxy curl https://github.com
proxy_status
```

The last status must still be direct. Shell migration does not require a Mihomo
restart and must not interrupt ordinary SSH or downloads.

For rollback, preserve the current file, restore the printed timestamped
`.bashrc` backup, run `bash -n ~/.bashrc`, and validate in another new Shell.
Do not reintroduce a PC SSH reverse proxy as the long-term architecture.
