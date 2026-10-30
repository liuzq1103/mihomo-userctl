# Install and initialize

For the complete bundle, run `mihomoctl` and use the [terminal guide](console.md): the bundled core and dependencies need no system Python or virtual environment. Preview the subscription, then confirm saving and starting. The following explicit CLI steps are a standard Python installation path for a prepared Linux/Python 3.10+ installation. Installation and init alone leave the runtime stopped. See [verified installation](../../INSTALL.md). For the current shell:

```bash
export PATH="$HOME/.local/bin:$PATH"
mihomoctl version
```

## Reuse an existing core

First inspect `${XDG_CONFIG_HOME:-$HOME/.config}/mihomoctl/manager.yaml` (use the actual path for a custom configuration directory). Preserve an existing manager: do not initialize again or proactively run core install. A missing/broken configured core needs a separately scoped repair; report the blocker. Without a manager, choose exactly one of the following paths.

Use an absolute, trusted, executable path owned by you or root, with no group/other write permission. Initialization validates a copy; the original binary/configuration stays intact:

```bash
mihomoctl init --core /absolute/path/to/mihomo
```

To import an existing configuration, instead initialize once with:

```bash
mihomoctl init --core /absolute/path/to/mihomo --config /absolute/path/to/config.yaml
```

Do not run both initializations on an existing manager. Imported routing is preserved. Review the resulting private configuration and listener authentication.

## Restore the default configuration

Subscriptions, rules and probe settings are layered one key at a time onto the configuration `init` produces, and nothing rewrites it as a whole; `init` also refuses to run twice over an existing manager. `reset` is the explicit, one-shot way back: preview first, then restart to make it effective.

```bash
mihomoctl reset --dry-run
mihomoctl reset --apply --plan-sha256 REVIEWED_PLAN_SHA256
mihomoctl config validate
mihomoctl restart
```

Preview and apply share one removal list. `reset --apply` stops the runtime, then transactionally removes the manager configuration, the active core configuration, every `profiles/*.yaml` credential file and the leftover `.before-policy-*` backups and `.userctl-state.json` receipt, and republishes exactly the default shape `init` produces (random ports, random secrets, `MATCH,DIRECT`). Recovery material exists only during the operation and is removed after success; `mihomoctl reset --core PATH` re-initializes from a different core instead.

Configuration is what resets, not the installation: the Mihomo core binary, the subscription previews and the logs are all kept. Credentials and the controller secret are regenerated, so the old ones stop authenticating and any previously exported environment file must be exported again. `reset` does not touch subscriptions; run the [subscription](subscriptions.md) preview/apply yourself afterwards.

## Explicitly install a fixed core

For a new installation with no trusted existing core and network access allowed, default to **v1.19.32** without asking the user to choose a version. This is the project's fixed tested version, not a claim about the latest upstream release. The included digest currently covers only Linux **x86_64 / amd64-compatible**:

```bash
mihomoctl core install --version v1.19.32
mihomoctl core list
mihomoctl init --core "${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/cores/v1.19.32/mihomo"
mihomoctl config validate
```

Without a manager, `core install` only stores the verified binary; initialize explicitly as shown. **With an existing manager it activates the new core and may stop and restart the running old core.** Do not apply this new-install recipe to an existing runtime. arm64/armv7 require a checked `--sha256` for their corresponding asset even at the same version, or a trusted local core. Other versions also need a digest. Never bypass verification. A curated pin establishes a digest match, not an upstream signature or reproducible build.

Source archives, wheels and legacy Python kits do not contain Mihomo; the recommended complete SSH bundle includes its pinned core. For a source/Python installation with networking allowed, explicitly download the core as above. For strict offline use, prepare a trusted core beforehand; report a missing core before installation. Core download needs direct connectivity or an existing trusted proxy environment. Do not bootstrap the missing core through this installation's uninitialized/stopped `mihomoctl exec`.

Report controller verification, core version and configuration validation separately. With the default stopped runtime, runtime health and remote routing remain UNVERIFIED. Continue below only when ready to start. Default `MATCH,DIRECT` does not provide remote routing.

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
| Logs and unfinished recovery | `$XDG_STATE_HOME/mihomoctl/` = `~/.local/state/mihomoctl/` |
| Cache | `$XDG_CACHE_HOME/mihomoctl/` = `~/.cache/mihomoctl/` |
| Runtime | `$XDG_RUNTIME_DIR/mihomoctl/`, or private state/runtime fallback |

New configuration defaults to `MATCH,DIRECT`. Proceed to [subscriptions](subscriptions.md), [custom rules](rules.md), then [verification](first-run.md).

[Python installation / 标准 Python 安装](python-install.md)
