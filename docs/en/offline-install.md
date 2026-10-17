# Offline installation

With 1.2.0 installed on a connected Linux/WSL machine, use
`mihomoctl release fetch --output-dir DIR --target ubuntu22.04-x86_64-py310`.
The other target is `ubuntu24.04-x86_64-py312`. The download machine need not match
the target. Transfer the complete output directory, including original kit,
checksums, gate evidence and relative acquisition record. Transport consistency
checks are not independent publisher signature authentication.

On the destination, KIT is the absolute path to the transferred directory:

```bash
umask 077
mkdir "$HOME/mihomoctl-offline-source"
tar -xzf "$KIT/kit/release/mihomoctl-1.2.0.tar.gz" -C "$HOME/mihomoctl-offline-source"
cd "$HOME/mihomoctl-offline-source/mihomoctl-1.2.0"
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$KIT/kit/wheelhouse" --dry-run
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$KIT/kit/wheelhouse"
```

Older installations use this verified new installer directly; no new command is
required in the old CLI. The destination performs no downloads and does not
depend on absolute paths from the download machine.

Use the complete kit matching Ubuntu 22.04 x86_64 Python 3.10 or Ubuntu 24.04 x86_64 Python 3.12. Verify its outer .sha256 against independently obtained release checksums before extraction; inspect and verify SHA256SUMS inside. The kit contains source, wheel, dependency wheelhouse and an installer. Extract into a private, owned directory; no symlinks or group/other writable code paths.

Read the kit README.txt and invoke its install.sh from that extracted directory. It checks target compatibility and installs with --no-index from wheelhouse. No pre-expanded public deployment directory is required. Installation remains user-scoped by default and performs no runtime/service actions. Keep the reported self-contained backup. See [INSTALL.md](../../INSTALL.md) and [upgrade/rollback](update.md). Offline core provisioning is separate: provide an already verified executable and initialize it explicitly.
