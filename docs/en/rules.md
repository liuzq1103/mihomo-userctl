# Private custom rules

[中文](../zh-CN/rules.md) · [Documentation](README.md) · [Setup](setup.md)

`mihomo-userctl` keeps routing policy private and separate from the public project. The controller can inspect the documented layout, but it never creates rule files, edits `config.yaml`, restarts Mihomo, or uploads policy data.

## Layout and permissions

Place three files below the Mihomo HomeDir used by `mihomo -d`:

```text
<Mihomo HomeDir>/rules/custom-direct.yaml
<Mihomo HomeDir>/rules/custom-proxy.yaml
<Mihomo HomeDir>/rules/custom-reject.yaml
```

The `rules` directory must be owned by the current user with mode `700`; each file must be a regular, current-user-owned, non-symlink file with mode `600`. Start from the fictional files in `examples/rules/`; do not put real private rules in this repository.

Each file uses Mihomo's classical provider format:

```yaml
payload:
  - DOMAIN-SUFFIX,example.com
```

Reference them from `config.yaml` with these exact provider contracts:

```yaml
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
```

The matching rules must appear before the final fallback:

```yaml
rules:
  - RULE-SET,custom-direct,DIRECT
  - RULE-SET,custom-proxy,Proxy
  - RULE-SET,custom-reject,REJECT
  - MATCH,DIRECT
```

`Proxy` must be an existing proxy group. `DIRECT` and `REJECT` are Mihomo built-ins. Rules are evaluated from top to bottom, so a preceding `MATCH` would make later custom rules unreachable.

## Read-only commands

```bash
mihomoctl rules status
mihomoctl rules status --json
mihomoctl rules check
```

Defaults are `${XDG_DATA_HOME:-$HOME/.local/share}/mihomo` and `${XDG_CONFIG_HOME:-$HOME/.config}/mihomo/config.yaml`. If the service uses different paths, state both explicitly rather than guessing:

```bash
mihomoctl rules check --home-dir /absolute/mihomo-home --config /absolute/config.yaml
```

`status` reports only filenames, counts, SHA-256 digests, modification times and permission status. It never prints rule entries. `check` also validates provider references, target groups, ordering, and runs the installed Mihomo binary with `-t`; all Mihomo output is suppressed because arbitrary configuration errors can contain private values.

The structural check intentionally supports the documented block-style sections. Anchors, merges, flow mappings or other forms that it cannot classify safely produce exit `2`; rewrite only the relevant custom-provider sections into the documented form and run the check again. A missing final `MATCH` is a warning because the desired fallback remains the user's decision.

Exit `0` means every required check passed, possibly with the documented fallback warning. Exit `1` means an observed file, provider, target, ordering or Mihomo configuration failure. Exit `2` means invalid arguments, unsafe paths, missing dependencies or an unsupported structure that could not be verified.

Before changing private rules, make a private backup of the three files and `config.yaml`. After editing, run `mihomoctl rules check`. Whether to restart Mihomo remains a separate, explicit user action. Restore the backup and run the same check if validation fails.
