# Server-first Mihomo console (v0.9.0)

`mihomoctl tui` automatically selects the available Chinese Textual task console, falling back to a Chinese numbered menu. Explicit curses, textual and plain engines remain available. Startup never downloads dependencies. All backends share controller services. Ordinary shells remain direct; node changes keep established connections open.

## Optional installation

Base CLI: Python 3.8+. Controller operations: PyYAML. Optional Textual environment: Python 3.9+.

When installed, the private environment also runs Controller commands and the start/restart validator, so its locked PyYAML does not need a system-wide installation.

```bash
bash install.sh --port YOUR_PORT --with-textual --tui-python python3
mihomoctl tui --engine textual
mihomoctl tui --engine curses
mihomoctl tui --plain
```

Omit `--port` for an existing installation. The installer builds a private venv in its generation using pinned versions, SHA256 hashes and wheels only. It never uses system pip, sudo, or starts/enables Mihomo. Missing UI dependencies produce an explicit error; opening the UI never installs packages. A pinned pip wheel bootstraps distributions without ensurepip.

Prepare an offline wheelhouse for the target Python and architecture:

```bash
python3 -m pip download --require-hashes --only-binary=:all: \
  -r scripts/textual-requirements.txt -d /ABSOLUTE/wheelhouse
bash install.sh --with-textual --tui-python python3 --wheelhouse /ABSOLUTE/wheelhouse
```

Include the pip bootstrap wheel and all dependencies. The wheelhouse must be owned by this user, without unsafe writable ancestors or symlinks. Offline installation never falls back to the network. Missing wheels or hash failures roll back the active installation. Normal updates reuse the private environment when the lock is unchanged; a changed lock requires an explicit `install.sh --with-textual`. The existing rollback lifecycle retains previous generations and environments.

## Pages and interaction

Main entries are Home, Nodes, Subscriptions and More (displayed in Chinese). Home exposes setup, start, stop, restart and mode selection. Nodes exposes search and latency buttons. More contains connections, rules, logs, providers, diagnostics and runtime. Subscriptions follows source → preview → save → restart. Private receipts preserve pending changes and backup recovery across sessions; external config edits invalidate automatic recovery.

Overview separates service observations, listener, authentication and readiness, and shows version, traffic, memory, connections and selections. Proxies provides groups, search, sorting, switching, latency and policy previews. Connections is read-only. Rules shows type counts and rule-provider summaries without private payloads. Logs streams Controller events into a bounded buffer. Profiles shows disk configuration counts. Providers shows node-provider status. Diagnostics reuses offline doctor/Codex diagnosis; preflight and ready require explicit commands. Runtime exposes user-service status and explicit lifecycle commands.

Tab/Shift+Tab moves focus; arrows browse; Enter selects. `/` searches, `r` refreshes, `t` tests one node, `T` confirms a batch of visible nodes (at most four concurrent requests), `p` pauses connections/logs, `s` reverses sorting, `c` shows connections, `f` samples traffic and `v` opens the full last result. Latency does not prove model E2E. `m`/`o` preview manual-group/trusted-JS policy, and `y` reviews and saves the exact candidate. Esc cancels input, previews or queued latency tests; `q` quits outside input fields. `[`/`]` changes groups in compact layouts too.

`?` opens help; `:` accepts commands: `page NAME`, `group NAME`, `start`, `stop`, `restart`, `mode rule|global|direct`, `dns NAME [TYPE]`, `provider NAME`, `subscribe FILE`, `subscribe-url PRIVATE_URL_FILE`, `cancel`, `log-level debug|info|warning|error`, `ready`, `doctor`, `codex`, `rules-status`, `rules-check`, `theme dark|light`.

Keyboard operation is complete; mouse is optional. Full layout targets 80×24, compact layout 60×14; smaller terminals show guidance. `--ascii` uses ASCII selection markers, `--theme dark|light` selects the theme and `NO_COLOR=1` disables colors. No Nerd Font is needed. `--details` explicitly enables private connection hosts/rule payloads/log messages; known credentials remain masked in logs. Logs are not exported by default.

Refresh preserves filters, object identity and scroll position. Failed requests keep stale data with time and reason. Only 404/405 denotes an unsupported endpoint; auth failures do not. Traffic samples every second, visible connections every two seconds and groups/services every five seconds. Logs hold at most 2,000 entries and revalidate on reconnect, with 1/2/4/8/15-second failure backoff. Mutations are never replayed automatically.

## Provider policies and node subscriptions

`: journal` reads the current user's last 200 service journal entries through the same safe projection; `v` opens the full result. Controller logs stream in the Logs page.

`: diagnose url PUBLIC_HTTPS_URL` explicitly runs the existing network diagnosis (no userinfo, query or fragment). `: diagnose process PID` uses the existing current-UID process diagnosis. Results keep the original evidence statuses; `v` opens the full report.

CLI defaults to `--policy nodes`: only a top-level `proxies` list is accepted; matching nodes replace existing entries and others remain. `--policy provider` accepts provider YAML and replaces `proxies`, `proxy-providers`, `proxy-groups`, `rules` and `rule-providers` together. Names, order, group types and references are retained without generating groups; missing policy fields become empty. Host ports, controller, secrets, DNS, TUN and other runtime settings are ignored and listed in preview. Duplicate names, missing references and unsafe provider paths are rejected. Provider preview and apply both validate with the installed core. Base64 and URI lists remain unsupported.

Provider paths must stay in dedicated `providers/`, `proxy-providers/`, `proxy_provider/`, `proxy_providers/`, `rules/`, `rule-providers/` or `rule_provider/`, `rule_providers/` trees under the core home. HTTP providers require an explicit cache path. Paths overlapping the host configuration, backups, receipts or another provider are rejected; adjust unsafe subscription paths before previewing.

The TUI defaults to provider policy; select node merging for a node-only list. Provider mode clears missing strategy fields; review removed groups/rules before saving. Equivalent CLI:

```bash
mihomoctl subscription preview --source-file /ABSOLUTE/provider.yaml --policy provider --json
mihomoctl subscription preview --stdin --policy provider --json < /ABSOLUTE/provider.yaml
# Review the piped preview in the current SSH PTY; no automatic save:
mihomoctl tui --stdin < /ABSOLUTE/provider.yaml
```

`tui --stdin` consumes and validates YAML before restoring keyboard input from `/dev/tty`. It requires a controlling terminal and terminal output, supports Textual/plain, and defaults to provider policy. Curses does not support this entry. Config stays unchanged until save is confirmed.

```bash
chmod 600 /ABSOLUTE/private-nodes.yaml
mihomoctl subscription preview --source-file /ABSOLUTE/private-nodes.yaml --json
# Review the per-node additions/replacements and use the returned ID and digest:
mihomoctl subscription apply PREVIEW_ID --sha256 PREVIEW_SHA256 --json
```

For HTTPS use `--url-file PRIVATE_FILE`; `--stdin` reads node YAML. URLs/credentials never enter argv. Downloads use verified TLS, direct transport, no redirects/compression, a size limit of 8 MiB and bounded time. In the UI, `subscribe`/`subscribe-url` stages a preview; `y` reviews and saves it.

Raw data, candidates and plans reside in a private `mihomo-userctl-subscriptions` directory (0700; files 0600). Applying checks both candidate and original digests, enforces the selected policy boundary, validates with Mihomo, checks drift, backs up and atomically replaces under the operation lock. Failure preserves active bytes. Saving requires a separate restart and creates no scheduler. The JS policy allowlist is unchanged.

## Startup gates and scope

start/restart holds the same-user operation lock across mixed/controller port checks, the action and post-checks. Foreign-UID, wildcard and IPv6 collisions block; same-UID sockets must belong to the service MainPID/cgroup. Unknown ownership is UNVERIFIED. A configured Controller is rechecked for loopback, UID and anonymous rejection after startup. No automatic port changes or process killing. A bind probe is a snapshot, not a reservation.

When a disk core config exists, port parsing requires PyYAML; missing validation blocks. Stop retains its behavior. Runtime mode changes only PATCH `mode` and verify readback; no shell/disk edits. Provider refresh explicitly asks Mihomo to download. DNS queries never change system DNS.

Core downloading/upgrades, TUN, system proxy, arbitrary runtime replacement, remote Controllers and a persistent daemon remain out of scope. Existing cores are checked by config validation and API capabilities rather than an exact version requirement. Unsupported optional APIs affect only their corresponding features. Loopback authentication is not a UID firewall. See [console acceptance](console-acceptance.md) for real Linux/multi-user/SSH checks.
