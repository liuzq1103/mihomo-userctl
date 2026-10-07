# Nodes and dashboards

For node search, explicit manual-group conversion and local JavaScript policy previews, see [TUI and overrides](tui-overrides.md).

[English overview](../../README.en.md) · [简体中文](../zh-CN/control-plane.md)

v0.7 uses the Mihomo Controller API to show nodes, current group selections and active connection chains.
Mihomo still handles traffic. Ordinary shells remain direct and Codex preflight is unchanged.

## Enable once

Controller commands require **PyYAML** (`python3 -c 'import yaml'`). Existing proxy/Codex commands do not.
Use your distribution's python3-yaml or install PyYAML in a user-managed Python environment whose python3 is on PATH.
The tool does not install dependencies with elevated privileges.

```bash
mihomoctl controller setup
mihomoctl restart  # only when interrupting your proxy connections is acceptable
mihomoctl controller status
mihomoctl groups
```

Default config: `$XDG_CONFIG_HOME/mihomo/config.yaml`, falling back to `~/.config/mihomo/config.yaml`.
Default core working directory: `$XDG_DATA_HOME/mihomo`, falling back to `~/.local/share/mihomo`.
Require current-user ownership, config mode 600, working directory mode 700 and no symlink components.
For a custom deployment:

```bash
mihomoctl controller setup --config /ABSOLUTE/config.yaml --home-dir /ABSOLUTE/mihomo
mihomoctl groups --config /ABSOLUTE/config.yaml
```

Paths must match your systemd service arguments. Setup chooses a currently free independent port (or `--port PORT`),
generates a secret, enables selection persistence, and deploys static UI files. It preserves unrelated configuration text,
validates with `mihomo -t`, backs up privately, then replaces the config atomically. It never edits service units or restarts.
Port checks are snapshots, not reservations. A bind conflict must be resolved without killing the occupying process.

Public controllers, weak secrets, additional Unix/TLS/DoH endpoints, YAML anchors/aliases, duplicate keys, complex root
mappings and explicit document-end markers are rejected for manual review. Existing dashboards are preserved unless
an explicit archive is supplied. Failed validation leaves the config unchanged. Backups contain private data: keep mode 600,
never upload them. To recover, restore the reported backup, validate it, then restart when appropriate.

## Daily commands

```bash
mihomoctl nodes
mihomoctl groups --json
mihomoctl select "Proxy" "NODE NAME"
mihomoctl latency "NODE NAME"
mihomoctl connections
mihomoctl traffic
mihomoctl tui
```

Selection accepts an existing member of a manual Selector group and verifies the result by reading it back.
Automatic URLTest/Fallback/LoadBalance groups remain read-only. **Prefer `mihomoctl tui` on remote servers: no SSH port mapping required.**
The fullscreen interface shows groups and nodes side by side, marking the current node with `[*]`.
Use arrows to browse, Tab/left/right to switch panes, Enter to enter/select, r to refresh, t for latency,
c for the first two active chains, f for a traffic sample, and q to quit. Groups refresh every five seconds.
Use `mihomoctl tui --plain` for a numbered menu on narrow terminals or with screen readers. Existing connections are not forcibly closed. `profile.store-selected` enables
persistence, which also requires the core working directory to remain writable.

**Group selection is not proof of every request's exit.** Rules, nested groups, load balancing and existing connections
affect routing. `connections` reports active chains and rule types, omitting hostnames, IPs, process paths and rule payloads.
No active connections means no route evidence. `traffic` takes one rate sample (bytes/s, cumulative values in bytes).
`latency` makes a request through the named node to `https://www.gstatic.com/generate_204`; it is not model verification.

Noninteractive commands support `--json`, schema `mihomo-userctl.controller/v1`.
Exit 0: success; 1: known request failure or policy block; 2: configuration, dependency, inspection or usage error.
Reports omit secrets/subscriptions/raw connection metadata, but node and group names can themselves be private.

## Optional browser access

```bash
mihomoctl ui
mihomoctl dashboard  # alias
mihomoctl controller token
```

`ui` verifies the controller and prints a URL plus SSH instructions without launching a browser.
`controller token` explicitly reveals the secret only to an interactive terminal, never JSON or a pipe. Use a private terminal.
The bundled panel stores the secret only in memory, never URLs or browser storage.
On your computer, forward the server port reported by `ui`:

```bash
ssh -N -L LOCAL_PORT:127.0.0.1:REMOTE_CONTROLLER_PORT USER@SERVER
```

Open `http://127.0.0.1:LOCAL_PORT/ui/` and enter the secret. Keep both controller and tunnel loopback-only.
The panel uses same-origin requests without wildcard CORS or an additional daemon.

## MetaCubeXD

Obtain a reviewed, pinned **built static-site ZIP** from the [official project](https://github.com/MetaCubeX/metacubexd)
and verify its SHA256 against a trusted source. Desktop packages and unbuilt source archives are not supported.

```bash
mihomoctl controller setup --archive /ABSOLUTE/metacubexd-static.zip --sha256 VERIFIED_SHA256
mihomoctl restart
mihomoctl ui
```

The bounded ZIP installer requires a single index.html root and rejects traversal, links, duplicate entries and oversized data.
A matching hash alone does not authenticate the source. No downloaded code is executed by the installer and no UI is
automatically downloaded or updated. Browser JavaScript receives your controller secret, so deploy only trusted versions.
Third-party UI storage and operations follow that UI's design, replacing the bundled panel's restricted interface.
Configure MetaCubeXD with the forwarded loopback address and secret.

Controller and proxy credentials are separate. CLI checks loopback binding, socket UID and anonymous rejection before
sending credentials; this does not protect against root, same-UID malicious code or subsequent port races. Static `/ui/`
contains no secret; API calls require authentication. Subscription/core installation, global routing and model E2E remain outside this feature.

References: [Mihomo API](https://wiki.metacubex.one/api/), [controller/UI configuration](https://wiki.metacubex.one/config/general/).
