# Copyable Codex installation prompt

Use this when you want Codex to guide a fresh, per-user installation. Replace
the bracketed values before sending it. Do not paste subscription URLs or
passwords into the prompt; provide secrets only through a mode-600 server file
when Codex asks for the local path.

```text
Install a per-user Mihomo stack and mihomo-userctl for my current Linux account.

Required result:
- ordinary logins, new shells, axel, S3, and large datasets are direct by default;
- only with_proxy, proxy_on, and explicitly approved remote-tool hooks use Mihomo;
- Mihomo has one authenticated Mixed listener on 127.0.0.1:[PORT];
- use only systemctl --user; mihomo.service must remain disabled;
- no sudo, root service, linger, cron, TUN, controller, system proxy, or route changes;
- do not inspect, modify, stop, or authenticate as any other user;
- do not stop unknown listeners, ssh/sshd, downloads, or unrelated sessions;
- do not touch a pre-existing 127.0.0.1:7890 unless I separately authorize it;
- never print, log, commit, or place subscription URLs or proxy credentials in command arguments.

Implementation order:
1. Read this repository's README and docs/en/setup.md completely.
2. Perform read-only checks for OS, CPU architecture, libc compatibility, Bash,
   systemd user manager, dependencies, current proxy variables, candidate ports,
   current user service, downloads, and existing configuration.
3. Report the exact files and processes in scope. Stop before any step requiring
   administrator permission or before changing an ambiguous existing setup.
4. Back up every in-scope file with restrictive permissions.
5. Install a pinned official MetaCubeX Mihomo release: download the matching
   asset, verify its official SHA256, test the candidate version and config,
   then atomically install it under ~/.local/bin.
6. Create a loopback-only authenticated configuration, private provider/cache
   paths, a systemd user unit, and mode-600 client.env without exposing secrets.
7. Clone or use mihomo-userctl, run its tests, then run install.sh --dry-run
   --port [PORT] and install.sh --port [PORT] --bashrc "$HOME/.bashrc".
8. Do not enable or automatically start the service. Start it manually for tests.
9. Verify: unauthenticated HTTP/SOCKS is rejected; authenticated HTTP and
   SOCKS5H work; service is disabled; new shell is direct; with_proxy does not
   change its parent; ordinary axel/S3 is direct; logs and Git contain no secrets.
10. Give me exact rollback commands and a redacted verification report.

Use [READY_URL] for readiness. Keep MATCH,DIRECT as the final Mihomo rule. Treat
all policy rules and subscriptions as user-owned and do not replace them without
showing a redacted diff and receiving approval.
```

The prompt deliberately tells Codex to use deterministic project scripts. A
prompt alone is not a reproducible installer, and `curl | bash` is not used.
