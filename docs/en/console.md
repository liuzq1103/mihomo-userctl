# SSH terminal interface

The complete bundle includes Textual. Run `mihomoctl` or `mihomoctl tui` over SSH without separately installing a UI, Python environment, browser or port forwarding. Each Linux account owns an independent proxy.

## First use

1. Existing managers are preserved. For a new user, the UI prepares the included verified core and private configuration.
2. Paste a hidden HTTPS subscription URL or select a private YAML file.
3. Simple mode creates one manual Proxy selector; advanced full-policy import retains subscription groups and rules. Existing custom routing is preserved in simple import.
4. Review the candidate and confirm saving and starting. A failed activation restores the previous configuration and affected runtime when possible.
5. Search, measure and select nodes. Selections survive restart; existing connections are not forcibly closed.

```bash
mihomoctl
mihomoctl tui --engine plain
mihomoctl exec -- codex
mihomoctl direct -- codex
mihomoctl --help
```

Use Tab/arrow keys and Enter, and q to exit. The node page provides individual and batch latency checks. The plain menu supports basic subscription and selection operations on limited terminals. Exiting the UI leaves the core running and does not modify the calling shell environment. JSON, help, pipes and noninteractive calls never open the UI.

Network operations run in background workers. Esc cancels pending work, subject to the current bounded network-read timeout. Subscriptions and provider resources still need connectivity, even when the software bundle was transferred offline.

## Keyboard and delay results

| Key | Action |
| --- | --- |
| Tab / arrows / Enter | Move focus, browse and confirm |
| `/`, `[` / `]` | Search nodes; previous / next group |
| `t` / `T` | Measure highlighted node / batch of nodes |
| `r`, `p`, `s` | Refresh, pause observations, change sorting |
| `v`, `?`, `:` | View result details, help, command input |
| Esc, `q` / Ctrl+C | Cancel work; exit the interface |

Shortcuts apply when a text field is not consuming the key. A delay is a request through the selected node to the configured probe target, not a bandwidth benchmark or proof of a successful application request. `unknown-node` and `node-not-in-core` mean the exact name is absent from the core table; `node-unreachable` means the probe failed and `delay-timeout` means it timed out. See [delay troubleshooting](troubleshooting.md).

The secondary pages retain connections, providers, rules, logs, diagnostics and runtime controls. The command input accepts `subscribe /absolute/private/subscription.yaml` and probe settings such as `health-check provider "ProviderName" --preset resilient`; a Selector needs a probe on its underlying provider. Review the resulting preview before saving and explicitly restart where requested. The terminal's subscription save/start action performs both in one recoverable operation; the advanced CLI preview/apply commands below do not.

## Recovery policy and advanced use

Only current code, core and configuration remain. There is no historical rollback or restore-backup button. Temporary recovery material exists only for unfinished transactions and is deleted after success or successful recovery. Failed recovery preserves necessary material and reports an error.

Scripted `subscription preview --url-file` / `--source-file` and `subscription apply` remain available; explicitly start or restart after those commands. Advanced routing, health, integration and systemd commands are retained. Source extras/wheelhouse installation remains an advanced compatibility path.

Close other mihomoctl interfaces for this account before updating. The update checks this before switching, keeping open interfaces usable; closing the UI leaves the core running. Cancelled previews are removed, and previews older than 24 hours are removed on the next UI launch or subscription operation. Raw subscriptions are parsed in memory.
