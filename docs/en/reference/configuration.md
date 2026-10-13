# Configuration and compatibility contract

The manager schema remains `version: 1`, independently of package version 1.1.0. Public JSON remains `mihomoctl/v1`, with command, scope, overall, data, checks and errors. PASS exits 0, FAIL exits 1, UNVERIFIED exits 2; exec/direct preserve child exit and signal behavior after launch.

Read the initialized private manager.yaml rather than replacing it wholesale. A profile references named core listeners and a private credentials_file; it never duplicates ports or embeds passwords. Bindings reference a profile and adapter. Supported adapters: exec, systemd, docker, kubernetes, supervisor, pm2, ci. See [integration examples](../operations/integrations.md).

Unknown keys, duplicate YAML keys, unsafe aliases and cross-scope secret paths fail closed. System paths are fixed, independent of HOME and CWD. Explicit allow_non_loopback authorizes addresses, without opening ports. The core config controls routing; a profile only selects the proxy listener. NO_PROXY exclusions can bypass that listener.

All current commands and options are generated in [CLI reference](cli.md) from the dispatch parser. Compatibility aliases: profiles → profile list, export --binding NAME → integration export NAME, dashboard → ui, health → health check. Retired command names codex/paseo/opencode/diagnose/ready are rejected and appear here only as migration mappings. Use exec/direct for application launch and bindings for runtime integration. No application daemon or automatic shell hook returns.
