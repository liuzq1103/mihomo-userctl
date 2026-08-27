# Copyable Codex installation prompt

Use this for a fresh per-user installation. In a Codex client that offers it,
switch the task to **Plan mode** before pasting the prompt below. Plan mode and
interactive popups are Codex-client capabilities, not Mihomo requirements; if
they are unavailable, the agent must stop and let the user choose whether to
continue with explicit conversational confirmation.

Do not pre-fill port placeholders. Codex should audit first and collect
non-secret choices interactively. Never paste subscriptions or passwords into
the prompt, a popup, or chat; secrets belong only in mode-600 server files.

```text
Install a per-user Mihomo stack and mihomo-userctl for my current Linux account.

Planning and interaction rules:
- confirm that this task is in Plan mode; if not, stop and recommend switching;
- after read-only discovery, present a complete plan and wait for my approval
  before changing files;
- whenever a non-secret value needs customization, use request_user_input or
  the client's equivalent interactive popup; never guess or hard-code it;
- ask only 1-3 short questions per popup, show a recommended choice with impact,
  and allow a user-entered value;
- interactively confirm at least the listener port, readiness URL, service name,
  subscription integration method, existing-config merge strategy, and policy
  choices;
- never collect a subscription URL, listener password, or token in a popup or
  chat; generate it locally or let me write it to a mode-600 server file, then
  accept only the path and validate permissions;
- if interactive input is unavailable, pause and report that limitation instead
  of silently selecting defaults.

Required result:
- ordinary logins, new shells, axel, S3, and large datasets are direct by default;
- only with_proxy, proxy_on, and explicitly approved remote-tool hooks use Mihomo;
- Mihomo has one authenticated Mixed listener on a user-confirmed loopback port;
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
3. Confirm a user-approved checkout directory, then clone or use a local
   mihomo-userctl checkout at a pinned released tag. Verify its origin, inspect
   the files, and do not use curl-piped installation.
4. From that verified checkout, run ./install.sh --suggest-port and inspect
   current listeners. Use an
   interactive popup to let me accept the candidate or enter a custom port.
   Users on the same server must avoid each other's ports; recheck before bind.
5. Collect the other non-secret choices interactively, then report the exact
   plan, files, and processes in scope. Stop before administrator permission or
   an ambiguous existing setup.
6. Back up every in-scope file with restrictive permissions.
7. Install a pinned official MetaCubeX Mihomo release: download the matching
   asset, verify its official SHA256, test the candidate version and config,
   then atomically install it under ~/.local/bin.
8. Create a loopback-only authenticated configuration, private provider/cache
   paths, a systemd user unit, and mode-600 client.env without exposing secrets.
9. Run mihomo-userctl's tests, then explicitly pass the confirmed
   port to install.sh --dry-run --port and install.sh --port --bashrc "$HOME/.bashrc".
10. Do not enable or automatically start the service. Start it manually for tests.
11. Verify: unauthenticated HTTP/SOCKS is rejected; authenticated HTTP and
   SOCKS5H work; service is disabled; new shell is direct; with_proxy does not
   change its parent; ordinary axel/S3 is direct; logs and Git contain no secrets.
12. Give me exact rollback commands and a redacted verification report.

The readiness URL must be interactively confirmed. Keep MATCH,DIRECT as the
final Mihomo rule. Treat all policy rules and subscriptions as user-owned and
do not replace them without a redacted diff and approval.
```

The prompt deliberately tells Codex to use deterministic project scripts. A
prompt alone is not a reproducible installer, and `curl | bash` is not used.
