# Scripts and server routing policy

Keep scripts and configuration in an account-owned private directory (700), with files at 600. A 664 script is rejected because another group member could change executable policy. Fix ownership and unsafe parent directories as well as the file mode; symlinks are refused. JavaScript is trusted account code: Node's VM is not a security sandbox. System-scope JavaScript overrides remain disabled.

```bash
chmod 700 "$HOME/private"
chmod 600 "$HOME/private/override.js"
mihomoctl override --script "$HOME/private/override.js"
mihomoctl override --script "$HOME/private/override.js" --apply
mihomoctl restart
```

The first command previews policy changes. `--apply` validates and saves; it does not restart. Restart performs validation before stopping the old core. The TUI subscription button instead saves and starts/restarts in one recoverable transaction. Preview success is not proof of successful saving, activation or a remote business request. Read the reported failure stage, restored/committed configuration and observed runtime state.

Only groups, rules and rule-providers may change through a script. The exact `__flclashRules` output key is discarded as desktop metadata in both normal and compatibility mode; it is never an exemption for changes to listeners, authentication, TUN, nodes or proxy-providers. `--flclash-compat` adapts trusted local provider caches for desktop scripts requiring inline input. It does not grant broader policy permissions or download Node. The complete application bundle does not include Node; use server YAML when Node is unavailable.

For a server fragment containing groups/rules, use the explicit overlay mode:

```bash
mihomoctl subscription preview --source-file "$HOME/private/server-policy.yaml" --policy policy --json
mihomoctl subscription apply PREVIEW_ID --sha256 CANDIDATE_SHA256
mihomoctl restart
```

`policy` replaces only supplied `proxy-groups`, `rules` and `rule-providers` sections. Omitted sections, nodes, proxy-providers and host settings survive. References are checked against the merged configuration: the published FlClash server policy expects a provider named `subscription`. Adapt that reference in a private copy if necessary; missing providers are not invented. Do not import a fragment in `provider` mode: full provider import intentionally defaults omitted policy sections to empty containers. `auto` keeps its existing detection and does not infer fragment overlays.

Full-policy previews run a core check; node-only previews perform structural checks. TUI reuse requires unchanged candidate bytes, core, identity and dependency resources. Across CLI processes or incomplete/changed dependencies, validation runs again. Isolation copies trusted resources into private staging and never points validation at the live core home. Cache contents and raw core output are not printed; a timeout does not establish repeated downloads as the production root cause.

Successful operations remove temporary transaction recovery copies and preview files. Historical backups/rollback are not retained. Failed or interrupted operations retain only recovery material still needed to restore state; an unverified recovery is never presented as success. See [subscriptions](subscriptions.md) and [troubleshooting](troubleshooting.md).
