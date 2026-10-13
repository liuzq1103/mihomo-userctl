<!-- ARCHIVED: retired in v1.0.0. The daemon lifecycle this page documents no
     longer exists. Keep the file for historical reference only; do not follow
     its commands. -->

# [ARCHIVED] Paseo background daemon proxy injection

> **Status: historical archive. The command surface was retired in v1.0.0.**
>
> v1.0.0 removed all third-party daemon lifecycle management.
> `mihomoctl paseo start|stop|restart|run|install-unit` **no longer exist**; an old
> invocation returns migration guidance and **never** starts, stops or replaces a
> third-party process or unit.
>
> **Use instead** the generic integration in the
> [V1 command and configuration contract](v1.md):
>
> | What you wanted | What V1 does |
> | --- | --- |
> | Put a background service behind the proxy | `mihomoctl --system integration install NAME` writes a managed drop-in plus `proxy.env` for **your** unit, then **you** run `daemon-reload` |
> | Run one command through the proxy | `mihomoctl exec -- COMMAND` |
> | Check whether the proxy works | `mihomoctl health` |
> | Put a container behind the proxy | `mihomoctl integration export container-worker --output-dir "$HOME/.config/mihomoctl/export-container"` (the reachable address is declared as `connect_host` in `manager.yaml`; `127.0.0.1` inside a container is not the host loopback) |
>
> This tool will **never** stop a third-party application automatically. A
> leftover unit is only detected and reported.
>
> What follows is kept only for tracing the historical implementation and
> decisions. **It is not a current operating guide.**

---
# Proxy injection for the Paseo daemon

Version 0.9.3 adds a validated process boundary for background Paseo daemons. Ordinary shells remain direct; TUN, global proxy settings, routing policy and other users' processes are unchanged. See the [manual production procedure](paseo-production.md).

## Check and launch

```bash
mihomoctl paseo preflight --json
mihomoctl paseo start
mihomoctl paseo exec -- COMMAND ARGUMENTS
```

Preflight returns `SAFE_TO_LAUNCH` (0), `BLOCKED` (1), or `UNVERIFIED` (2). It checks the Mihomo service, loopback listener, HTTP/SOCKS anonymous rejection, credentials, ready health and direct/proxied paths to chatgpt.com, api.openai.com and auth.openai.com. Proxy reachability requires the selected listener as the peer, CONNECT 200, successful TLS and an origin HTTP response. Responses such as 403/421 prove reachability, not a successful model request; `model_request` and remote transport remain `UNVERIFIED`. Direct reachability is informational and does not prevent proxy launch.

Commands select `PASEO_HOME` or `~/.paseo`; use `--home /absolute/path` for another local instance. `PASEO_HOST` is ignored and remote targets are unsupported. The adapter requires Paseo's `daemon start/run/stop/status --home` interface and local JSON status (checked against 0.11.2). Unsupported status shapes and incomplete process inspection fail closed; Paseo is never automatically upgraded.

`start` is idempotent for a healthy existing daemon. A running daemon with environment drift blocks `start` and `exec`. Repair explicitly during a maintenance window:

```bash
# Interrupts running agents; execute manually.
mihomoctl paseo restart
```

Repair validates the proxy and current-user supervisor/worker identity, then uses the CLI to fully stop/start the selected instance. Native `paseo daemon restart` retains the supervisor's launch environment and cannot repair this fault. No `--force` or independent process killing is used. Stop failure prevents launch. New processes must match all eight variables and pass ready plus OpenAI listener probes. Failure never falls back to a direct daemon.

`exec` preserves literal arguments and the child exit code; it cannot change an existing process. `doctor [--offline] [--json]` includes Paseo drift. Offline findings explicitly rely on configured provider dependencies rather than measured network blocking.

## Domestic providers and NO_PROXY

Every launch safely reads `client.env`, setting upper/lowercase pairs for HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY. Credential-bearing URLs never enter launcher arguments, reports or generated units.

NO_PROXY always includes `127.0.0.1,localhost,::1,relay.paseo.sh`, keeping local app-server HTTP/MCP traffic direct. Optional settings live at `${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/paseo-proxy.json`; require a current-user-owned regular file with mode 0600:

```bash
# From the source directory; merge manually if a personal file already exists.
install -m 600 examples/paseo-proxy.json \
  "${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/paseo-proxy.json"
```

- `direct_domains` adds explicit hosts. Supplying it replaces optional built-in hosts; mandatory entries remain.
- `opencode_allowed_domains` authorizes discovery at those domains and their subdomains. Only discovered full hostnames are added.
- `opencode_config_files` lists additional absolute paths, including project-specific files.

Defaults cover Zhipu, DeepSeek and MiniMax APIs. Discovery reads global `opencode/opencode.json` / `.jsonc`, `OPENCODE_CONFIG`, additional files and the invoking environment's `OPENCODE_CONFIG_CONTENT`. It unions hosts from `provider.*.options.baseURL`; it does not reproduce all OpenCode config precedence. No workspace traversal, config execution, `{file:...}` resolution or API key reporting occurs. URL `{env:NAME}` substitution uses the launch environment; unresolved values block launch. Unapproved hosts appear in `pending_direct_domains` and remain proxied. OpenAI hosts are never automatically bypassed; wildcard and explicit protected-domain conflicts are rejected.

Codex descendants of the validated Paseo tree may use its expanded bypass list; independent Codex processes retain their existing strict gate. Set the same `PASEO_HOME` when diagnosing a nondefault instance.

## systemd user service

```bash
mihomoctl paseo install-unit --dry-run
mihomoctl paseo install-unit
```

Installs `${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/paseo.service` and only runs daemon-reload, never enable/start. Identical installs are idempotent; unrelated units and another home's unit are refused. This named unit manages one instance; others can still be managed manually.

The unit pins stable launcher paths, home, installation PATH and config paths. ExecStart uses foreground `mihomoctl paseo run`, and ExecStop uses Paseo's own stop. The wrapper validates the worker, waits for its supervisor and forwards signals/exit status; it refuses an existing instance. `Restart=on-failure`, `RestartSec=10` and a dependency on the selected Mihomo user service support boot/crash recovery without changing Mihomo's enabled policy. That Mihomo unit must already exist.

**A human must migrate production during a maintenance window**, stopping the old daemon before enabling the unit. Boot persistence requires `loginctl enable-linger "$USER"`; local policy may require administrator assistance. Follow the [production procedure](paseo-production.md).

Credentials are read from `client.env` on each start and are never copied into the unit. After credential or bypass-list rotation, manually restart `paseo.service` and verify again. Reinstall the unit after changing binary/PATH/config paths. systemd does not inherit arbitrary interactive variables; prefer explicit file-based baseURLs or maintain required nonsecret environment settings yourself. Installation refuses to persist `OPENCODE_CONFIG_CONTENT`, which can contain keys.

With a managed unit, start/restart use systemd and verify that running processes belong to its cgroup. Consult the selected Paseo home's logs and `journalctl --user -u paseo.service`. Manually stop/disable the unit before uninstalling mihomo-userctl.

Sources: [Paseo CLI](https://paseo.sh/docs/cli), [OpenCode configuration](https://opencode.ai/docs/config/).
