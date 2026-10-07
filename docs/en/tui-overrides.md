# Terminal selection and local JavaScript overrides

Linux Mihomo consumes YAML. Desktop `main(config)` scripts run in the client before core configuration is loaded.
This release runs a trusted local script with Node.js and accepts changes only to proxy groups, rules and rule providers.
Listeners, authentication, DNS, TUN, inline nodes and proxy providers stay protected. Node vm is not a security sandbox;
use only scripts you reviewed. Configs, scripts and provider caches must be current-user-owned regular files, mode 600.

## Terminal controls

`mihomoctl tui` shows the active group even while node focus is selected. `[*]` marks the real selection; highlight marks the cursor.
Use arrows and Tab to navigate, Enter to select a manual group's member, `/` to filter (empty clears), `t` for latency,
`c` for connection chains, `f` for traffic, `r` to refresh and `q` to quit.
The interaction references [mihomoTui](https://github.com/shuideyimei/mihomoTui); no source code was copied.

Automatic groups are explicitly read-only. `m` previews converting a configured group to `select`; `y` validates, backs up and saves.
GLOBAL is core-generated and cannot be converted this way. CLI equivalent:

```bash
mihomoctl manual Proxy
mihomoctl manual Proxy --apply
# When interrupting your existing connections is acceptable:
mihomoctl restart
mihomoctl tui
```

Conversion changes all traffic matching the group. Ordinary node selection leaves existing connections intact; restart interrupts them.

## Script preview and application

Store a reviewed local `main(config)` script, then run:

```bash
chmod 600 ~/.config/mihomo/override.js
mihomoctl override --script ~/.config/mihomo/override.js
mihomoctl override --script ~/.config/mihomo/override.js --apply
```

Add `--flclash-compat` for the current [FlClash-rules script](https://github.com/liuzq1103/FlClash-rules/blob/main/dist/override.js).
It creates missing entry/fallback groups, feeds existing local YAML subscription caches to the script and converts generated
node choices back to provider references with exact-name filters. Proxy credentials are not copied into the configuration.
Unsupported or missing caches are rejected. Use `--home-dir /ABSOLUTE/mihomo` if the core uses a nondefault working directory.
Provider updates do not automatically add new names to the generated filters; preview and apply the script again.

For TUI preview use `mihomoctl tui --script /ABSOLUTE/override.js --flclash-compat`, then `o` to preview and `y` to save.
The numbered `--plain` interface supports selection only; use CLI commands for policy edits.
Before saving, the tool runs `mihomo -t`, checks concurrent config changes, saves a private `config.yaml.before-policy-*`
backup and replaces config atomically. A separate restart activates it. Restore the reported backup to roll back, then validate
and restart as appropriate. Do not share backups. Summary output omits full configuration and script error contents.

## Routing and acceptance evidence

`mihomoctl connections --details` explicitly includes private destination hosts and matched-rule payloads. Observe during a model
request and correlate the destination and chain; node labels do not prove final egress IP or regional access.
The proxy hook supplies a listener endpoint, not regional authorization.

v0.8.0 distinguishes SOCKS method 02 (username/password required, but unoffered) from anonymous method 00.
02 and FF provide anonymous-access rejection evidence; 00 is a failure, and malformed/incomplete responses remain UNVERIFIED.
An authenticated request is still independently checked. Published v0.7.0 artifacts and their acceptance contract are unchanged.

Process inspection classifies clear non-candidates before reading identity/environment. For non-dumpable sd-pam/fusermount3/sshd
helpers with inaccessible executable links, comm and bounded cmdline must corroborate the helper identity before exclusion.
Unknown live executables, uncorroborated helper names and unreadable Codex candidates remain UNVERIFIED. This classification
does not defend against malicious processes of the same UID. No processes are killed and no model request is performed by preflight.
