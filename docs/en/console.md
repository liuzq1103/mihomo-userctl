# Server-first Mihomo console (v0.9.0)

The existing `mihomoctl tui` still defaults to curses. Textual is an optional frontend inside an SSH PTY or tmux, with no extra server or listening port. All backends share controller services. Ordinary shells remain direct; node changes keep established connections open.

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

Overview separates service observations, listener, authentication and readiness, and shows version, traffic, memory, connections and selections. Proxies provides groups, search, sorting, switching, latency and policy previews. Connections is read-only. Rules shows type counts and rule-provider summaries without private payloads. Logs streams Controller events into a bounded buffer. Profiles shows disk configuration counts. Providers shows node-provider status. Diagnostics reuses offline doctor/Codex diagnosis; preflight and ready require explicit commands. Runtime exposes user-service status and explicit lifecycle commands.

Tab/Shift+Tab moves focus; arrows browse; Enter selects. `/` searches, `r` refreshes, `t` tests one node, `T` confirms a batch of visible nodes (at most four concurrent requests), `p` pauses connections/logs, `s` reverses sorting, `c` shows connections, `f` samples traffic and `v` opens the full last result. Latency does not prove model E2E. `m`/`o` preview manual-group/trusted-JS policy, and `y` reviews and saves the exact candidate. Esc cancels input, previews or queued latency tests; `q` quits outside input fields. `[`/`]` changes groups in compact layouts too.

`?` opens help; `:` accepts commands: `page NAME`, `group NAME`, `start`, `stop`, `restart`, `mode rule|global|direct`, `dns NAME [TYPE]`, `provider NAME`, `subscribe FILE`, `subscribe-url PRIVATE_URL_FILE`, `cancel`, `log-level debug|info|warning|error`, `ready`, `doctor`, `codex`, `rules-status`, `rules-check`, `theme dark|light`.

Keyboard operation is complete; mouse is optional. Full layout targets 80×24, compact layout 60×14; smaller terminals show guidance. `--ascii` uses ASCII selection markers, `--theme dark|light` selects the theme and `NO_COLOR=1` disables colors. No Nerd Font is needed. `--details` explicitly enables private connection hosts/rule payloads/log messages; known credentials remain masked in logs. Logs are not exported by default.

Refresh preserves filters, object identity and scroll position. Failed requests keep stale data with time and reason. Only 404/405 denotes an unsupported endpoint; auth failures do not. Traffic samples every second, visible connections every two seconds and groups/services every five seconds. Logs hold at most 2,000 entries and revalidate on reconnect, with 1/2/4/8/15-second failure backoff. Mutations are never replayed automatically.

## Node-only subscriptions

`: journal` reads the current user's last 200 service journal entries through the same safe projection; `v` opens the full result. Controller logs stream in the Logs page.

`: diagnose url PUBLIC_HTTPS_URL` explicitly runs the existing network diagnosis (no userinfo, query or fragment). `: diagnose process PID` uses the existing current-UID process diagnosis. Results keep the original evidence statuses; `v` opens the full report.

Input must be Mihomo YAML with only a top-level `proxies` list, including Provider payloads in that format. Full configs, Base64, URI lists and external provider definitions are rejected. Matching names replace nodes; other nodes remain. Group membership is never rewritten.

```bash
chmod 600 /ABSOLUTE/private-nodes.yaml
mihomoctl subscription preview --source-file /ABSOLUTE/private-nodes.yaml --json
# Review the per-node additions/replacements and use the returned ID and digest:
mihomoctl subscription apply PREVIEW_ID --sha256 PREVIEW_SHA256 --json
```

For HTTPS use `--url-file PRIVATE_FILE`; `--stdin` reads node YAML. URLs/credentials never enter argv. Downloads use verified TLS, direct transport, no redirects/compression, a size limit of 8 MiB and bounded time. In the UI, `subscribe`/`subscribe-url` stages a preview; `y` reviews and saves it.

Raw data, candidates and plans reside in a private `mihomo-userctl-subscriptions` directory (0700; files 0600). Applying checks both candidate and original digests, enforces the proxies-only boundary, validates with Mihomo, checks drift, backs up and atomically replaces under the operation lock. Failure preserves active bytes. Saving requires a separate restart and creates no scheduler. The JS policy allowlist is unchanged.

## Startup gates and scope

start/restart holds the same-user operation lock across mixed/controller port checks, the action and post-checks. Foreign-UID, wildcard and IPv6 collisions block; same-UID sockets must belong to the service MainPID/cgroup. Unknown ownership is UNVERIFIED. A configured Controller is rechecked for loopback, UID and anonymous rejection after startup. No automatic port changes or process killing. A bind probe is a snapshot, not a reservation.

When a disk core config exists, port parsing requires PyYAML; missing validation blocks. Stop retains its behavior. Runtime mode changes only PATCH `mode` and verify readback; no shell/disk edits. Provider refresh explicitly asks Mihomo to download. DNS queries never change system DNS.

Core installation/adoption, TUN, system proxy, full config import, arbitrary remote Controllers and a persistent daemon remain out of scope. Loopback authentication is not a UID firewall. See [console acceptance](console-acceptance.md) for real Linux/multi-user/SSH checks.
