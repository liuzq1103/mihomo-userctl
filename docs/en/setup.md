# Install and initialize

Start with [verified controller installation](../../INSTALL.md). Linux and Python 3.10+ are required. The installer never downloads a core or edits your shell startup files. For the current session:

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl version
```

## Reuse an existing core

Use an absolute, trusted, executable path owned by you or root, with no group/other write permission. Initialization validates a copy; the original binary/configuration stays intact:

```bash
mihomoctl init --core /absolute/path/to/mihomo
```

To import an existing configuration, instead initialize once with:

```bash
mihomoctl init --core /absolute/path/to/mihomo --config /absolute/path/to/config.yaml
```

Do not run both initializations on an existing manager. Imported routing is preserved. Review the resulting private configuration and listener authentication.

## Explicitly install a fixed core

On supported Linux architectures, the curated digest for this fixed version is included. Downloading is an explicit action:

```bash
mihomoctl core install --version v1.19.32
mihomoctl core list
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
```

Without a manager, `core install` only stores the verified binary; initialize it explicitly as shown. On an existing manager it activates the new core through a guarded transaction. For another version, supply its independently checked archive SHA256 with `--sha256`; unknown versions without a digest fail. A curated pin establishes a digest match, not an upstream signature or reproducible build.

## Start and locate files

```bash
mihomoctl config validate
mihomoctl start
mihomoctl status
mihomoctl health check
```

The default backend is a user process; root and systemd are unnecessary. `init` does not start it. On changes, validate then explicitly restart. `service install` optionally selects the managed systemd backend, without enabling or starting it. System scope requires a leading explicit `--system` and administrator execution; the tool never invokes sudo.

| Purpose | User path (XDG defaults) |
| --- | --- |
| Manager | `$XDG_CONFIG_HOME/mihomoctl/manager.yaml` = `~/.config/mihomoctl/manager.yaml` |
| Active core config | `~/.config/mihomoctl/mihomo/config.yaml` (confirm `core.config` in manager) |
| Credentials | `~/.config/mihomoctl/profiles/` |
| Core HomeDir | `$XDG_DATA_HOME/mihomoctl/core-home` = `~/.local/share/mihomoctl/core-home` |
| Logs and backups | `$XDG_STATE_HOME/mihomoctl/` = `~/.local/state/mihomoctl/` |
| Cache | `$XDG_CACHE_HOME/mihomoctl/` = `~/.cache/mihomoctl/` |
| Runtime | `$XDG_RUNTIME_DIR/mihomoctl/`, or private state/runtime fallback |

New configuration defaults to `MATCH,DIRECT`. Proceed to [subscriptions](subscriptions.md), [custom rules](rules.md), then [verification](first-run.md).
