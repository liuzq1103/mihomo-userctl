# Offline preparation and transfer

Obtain `mihomoctl-1.4.1-portable-linux-x86_64.tar.gz` and its `.sha256` on a connected machine. Verify through a trusted release record, then transfer both. Python, Textual, dependencies and the pinned core are included; no wheelhouse, venv or system Python is needed.

```bash
umask 077
sha256sum --check --strict mihomoctl-1.4.1-portable-linux-x86_64.tar.gz.sha256
tar -xzf mihomoctl-1.4.1-portable-linux-x86_64.tar.gz
cd mihomoctl-1.4.1-portable-linux-x86_64
./install.sh --user
```

A connected installation can fetch the new format using `mihomoctl release fetch --output-dir DIR --target linux-x86_64`. Use the verified assets from the [v1.4.1 release](https://github.com/liuzq1103/mihomo-userctl/releases/tag/v1.4.1).

Copy materials into an owned private directory; shared storage is an input source, not a trusted writable executable location. After installation the extraction can be removed. Run `mihomoctl` to configure subscriptions and select nodes in the terminal. Remote subscriptions/providers still need connectivity; prepared local YAML input is supported.

The earlier Ubuntu/Python wheelhouse kits remain legacy compatibility formats and contain no independent interpreter. Only current software and configuration are retained, with no historical backups.

## Legacy Python kit compatibility

These recipes apply only to the earlier source/wheelhouse kits. They require a separately prepared trusted system Python and core. Prefer the complete bundle above for new SSH users. Review archive paths and independently authenticate digests before extraction.

```bash
# offline-fetch-layout
umask 077
KIT=/absolute/private/mihomoctl-kit
kit_root="$KIT/kit"
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

```bash
# offline-archive-layout
umask 077
PACKAGES=/absolute/private/packages
bundle=mihomoctl-1.4.1-offline-ubuntu22.04-x86_64-py310
(cd "$PACKAGES" && sha256sum --check --strict "$bundle.tar.gz.sha256") &&
kit_parent=$(mktemp -d "$HOME/mihomoctl-kit.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$PACKAGES/$bundle.tar.gz" -C "$kit_parent" &&
kit_root="$kit_parent/$bundle" &&
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

```bash
# offline-controller-install
umask 077
source_parent=$(mktemp -d "$HOME/mihomoctl-source.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$kit_root/release/mihomoctl-1.4.1.tar.gz" -C "$source_parent" &&
cd "$source_parent/mihomoctl-1.4.1" &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse" --dry-run &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse"
```
