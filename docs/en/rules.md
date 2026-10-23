# Custom rules

Import a [subscription](subscriptions.md) first. Read `core.config` in your private manager.yaml and preview and validate changes before applying them; the tool retains no historical copy. The current checker requires a group named exactly `Proxy`: ensure it exists and selects your intended remote node (not DIRECT). Names are case-sensitive. Provider policy imports may later replace groups/rules; review again after importing.

Create these three files, keeping existing user rules when adapting this example. Do not run the file-creation snippet over existing files without merging their contents. Directory permission must be 700 and file permissions 600. Paths are relative to the managed Mihomo HomeDir, not the repository or working directory.

Add/merge the YAML provider and rule sections below into the active core configuration. Preserve all existing listeners, authentication, controller settings, groups and unrelated providers. Put every custom RULE-SET before the final fallback. First-match ordering applies: reject, direct, proxy is the example order, not a universal policy. The domain example is illustrative and not a complete Codex endpoint list.
```bash
rules_dir="${XDG_DATA_HOME:-$HOME/.local/share}/mihomoctl/core-home/rules"
install -d -m 700 "$rules_dir"
umask 077
cat > "$rules_dir/custom-direct.yaml" <<'YAML'
payload:
  - DOMAIN,localhost
YAML
cat > "$rules_dir/custom-proxy.yaml" <<'YAML'
payload:
  - DOMAIN,api.openai.com
YAML
cat > "$rules_dir/custom-reject.yaml" <<'YAML'
payload:
  - DOMAIN,ads.example.com
YAML
chmod 600 "$rules_dir"/custom-*.yaml
```

If Proxy does not exist after a nodes-only import, add the following group to the active core config. Replace YOUR_IMPORTED_NODE with an exact imported node name (inspect your private subscription or `mihomoctl nodes` after restart). If Proxy exists, edit its member list instead of duplicating it.

```yaml
proxy-groups:
  - name: Proxy
    type: select
    proxies: [YOUR_IMPORTED_NODE]
rule-providers:
  custom-direct:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-direct.yaml
  custom-proxy:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-proxy.yaml
  custom-reject:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-reject.yaml
rules:
  - RULE-SET,custom-reject,REJECT
  - RULE-SET,custom-direct,DIRECT
  - RULE-SET,custom-proxy,Proxy
  - MATCH,DIRECT
```

```bash
mihomoctl rules status --json
mihomoctl rules check --json
mihomoctl config validate
mihomoctl restart
```

The checker uses the binary declared in manager.yaml, not another `mihomo` found on PATH. It only inspects files and invokes core validation, never rewrites configuration or restarts the runtime. JSON works for both status and check. A passing contract does not establish remote egress; perform [client verification](first-run.md).
