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
**Version decision: retain 0.9.2; do not roll it back.**

# Manual production migration for Paseo

**A human must execute these steps on production. Development tests must not connect to or restart production daemons, or send real model requests.**

## Evidence and version decision

Release commit `6ccc94d` updates version markers; `66a24c3` changes the Controller, task console and subscription import. Between v0.9.1/v0.9.2, proxy common code only changes its version marker; the shell and Codex diagnostic chain are unchanged. Rolling back cannot inject an existing daemon's environment.

The initial `366ffe2` commit (v0.1.0) already made ordinary shells direct with proxy_off, so this policy did not originate in 0.9.0. An older daemon inheriting historical shell proxy variables is consistent with the supplied diagnosis; its actual launch history remains for human verification.

The reported production /proc and direct/listener observations are input evidence, not measurements repeated during development. The operator must verify the selected home, CLI version, processes, ports, credentials, provider URLs and real Codex turn. Version 0.9.3 adds the missing daemon boundary while preserving direct shells and the existing security model.

## Checks and activation

Log in as the daemon owner. Check active agents and schedule a maintenance window:

```bash
paseo --version
paseo daemon status --json
paseo ls
mihomoctl doctor --offline --json
```

Use matching `PASEO_HOME` and `--home /absolute/path` for a nondefault local instance. Install 0.9.3 using the [update guide](update.md), preserving private configuration. Configure the bypass list using the [Paseo guide](paseo.md), then run:

```bash
mihomoctl ready --json
mihomoctl paseo preflight --json
```

BLOCKED is expected for an existing drifted daemon. Investigate UNVERIFIED before changing it; no force bypass is provided.

Probe without placing proxy credentials in arguments or globally sourcing client.env:

```bash
mihomoctl exec -- bash --noprofile --norc -c '
for host in chatgpt.com api.openai.com auth.openai.com; do
  printf "%s " "$host"
  rc=0
  curl --disable --head --globoff --proto =https --silent --show-error \
    --noproxy "" --max-time 10 --output /dev/null \
    --write-out "http=%{http_code} connect=%{http_connect} peer=%{remote_ip}:%{remote_port} seconds=%{time_total}\n" \
    "https://$host/" || rc=$?
  printf "curl_rc=%s\n" "$rc"
done'
```

Require curl_rc=0, CONNECT=200, the configured loopback listener as peer and an origin HTTP response. 403/421 establish reachability, not model success. Preflight separately reports forced-direct observations; restored direct access does not prevent proxy startup.

**During the maintenance window, a human stops the existing supervisor and activates the unit:**

```bash
paseo daemon stop
mihomoctl paseo install-unit --dry-run
mihomoctl paseo install-unit
loginctl enable-linger "$USER"
systemctl --user enable --now paseo.service
systemctl --user status paseo.service --no-pager
mihomoctl paseo preflight --json
```

Ask an administrator to enable linger if local policy requires it. The Mihomo user unit must exist; the generated dependency starts it without enabling it independently. The Paseo unit uses Restart=on-failure and reads credentials at runtime.

Without systemd, manually use `mihomoctl paseo restart` instead. Once managed, use that command or `systemctl --user restart paseo.service`, rather than launching another bare daemon.

## Verify the processes and real turn

```bash
paseo daemon status --json
mihomoctl paseo preflight --json
paseo provider diagnostic codex --json
```

Preflight's daemon.processes reports the current supervisor and worker PIDs with redacted environment matches. Locate the new Codex child after diagnostics or the smoke test. Run the explicit, UID-checked `/proc/<pid>/environ` verification snippet in the [Chinese implementation report](../zh-CN/paseo-production.md); it compares all eight values against a validated injected child environment without printing them, checks PID reuse, and refuses other users' processes.

Run one real turn through Paseo in an empty private directory:

```bash
smoke_dir=$(mktemp -d "${TMPDIR:-/tmp}/paseo-codex-smoke.XXXXXX")
chmod 700 "$smoke_dir"
(
  cd "$smoke_dir"
  paseo run --provider codex "Reply only OK; do not modify any files"
)
```

Require a completed turn replying OK. Neither a model list nor curl alone is acceptance. Repeat the process environment check for the new Codex PID. If it fails, collect redacted turn errors, provider diagnostics and `journalctl --user -u paseo.service --since '-10 minutes'`; distinguish network, login, model and provider settings.

## Rotation, disabling and rollback

After credential or bypass-list changes, retain owner/0600 and restart the unit during a maintenance window; repeat preflight, environment and listener verification. No unit reinstall is required for credential rotation. Reinstall after binary/PATH/config-path changes.

Disable with `systemctl --user disable --now paseo.service`. Verify the managed marker before manually removing this unit and reloading systemd; never remove another application's unit. Disable before uninstalling mihomo-userctl.

For tool rollback, first disable this new unit and follow the [existing rollback procedure](update.md), preserving credentials, core and subscriptions. Returning to 0.9.2 does not repair daemon environment inheritance; do not automatically relaunch a direct daemon or restore a global shell proxy.

Development uses private HOME directories, mocked network/service interfaces, fake /proc and actual Linux substitute process trees. No production host, daemon or model request is used. Local Linux/Python 3.10 validation passed: 285 unittest cases (5 conditional skips for the real core and optional Node checks), including 33 Paseo cases; 53 shell checks and 6 installation audit checks. Syntax, ShellCheck, documentation, secret scanning and git diff --check passed. systemd-analyze --user verify returned 0; the development environment has no usable systemd user bus, so actual unit activation and the CI Python version matrix were not exercised. Production acceptance remains the operator's responsibility.
