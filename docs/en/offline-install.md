# Local and strictly offline installation

Local packages do not necessarily mean a disconnected target. Complete new setup includes controller, core and initialization, with the runtime stopped by default. Source releases and offline control-plane kits **do not include the Mihomo core**. For strict offline use, prepare a verified compatible core beforehand. With networking allowed, explicitly download the fixed core after controller installation using [setup](setup.md). For an agent, copy the [local installation prompt](agent-local-install-prompt.md).

## Materials and target checks

Complete dependency kits support Ubuntu 22.04 x86_64 / Python 3.10 and Ubuntu 24.04 x86_64 / Python 3.12. Never force a mismatched target. Inspect existing managers first; preserve their core/configuration and do not initialize again. Report missing offline cores/dependencies before installation writes.

Treat a NAS directory such as `/mnt/nas/public/software` as source only. Set `umask 077`, copy required archives, digests, evidence and the entire wheelhouse into an owned private directory under HOME, then verify and use that copy. Do not execute shared writable code or change NAS permissions. Code and ancestors must meet installer trust requirements. Compare outer digests with an independently trusted release record; colocated checksums, receipts and gates establish consistency, not independent signatures. Before extraction, inspect archive entries and reject absolute/traversing paths, symbolic/hard links and special files. Extract into a new private directory. Commands below assume those checks have passed.

## Path one: complete release fetch output

On a connected Linux/WSL machine with 1.2.0 installed:

```bash
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target ubuntu22.04-x86_64-py310
```

Also supported: `ubuntu24.04-x86_64-py312`. The download machine need not match the target. Transfer the entire output directory, retaining the original kit, digests, gate evidence and acquisition.json relative paths, rather than only the source archive.

On the target, KIT is the complete output copied to a private location. Fetch already expanded the inner kit; do not expand the original outer archive again:

```bash
# offline-fetch-layout
umask 077
KIT=/absolute/private/mihomoctl-kit
kit_root="$KIT/kit"
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

## Path two: directly downloaded offline tarball

With only `mihomoctl-1.2.0-offline-TARGET.tar.gz` and its `.sha256`, expand the outer archive first. This example targets Ubuntu 22.04; set PACKAGES to the directory containing private copies:

```bash
# offline-archive-layout
umask 077
PACKAGES=/absolute/private/packages
bundle=mihomoctl-1.2.0-offline-ubuntu22.04-x86_64-py310
(cd "$PACKAGES" && sha256sum --check --strict "$bundle.tar.gz.sha256") &&
kit_parent=$(mktemp -d "$HOME/mihomoctl-kit.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$PACKAGES/$bundle.tar.gz" -C "$kit_parent" &&
kit_root="$kit_parent/$bundle" &&
(cd "$kit_root" && sha256sum --check --strict SHA256SUMS)
```

Stop on any failure; do not continue installation. These comparisons do not replace independent digest verification and archive entry review before extraction.

## Install the controller from the verified kit

Both paths now provide the actual `kit_root`. Read its README.txt and review build-receipt.json, bundle-manifest.json and accompanying gate evidence. Then extract its source archive. Choose a target-compatible Python; this example uses `/usr/bin/python3`:

```bash
# offline-controller-install
umask 077
source_parent=$(mktemp -d "$HOME/mihomoctl-source.XXXXXXXX") &&
tar --no-same-owner --no-same-permissions -xzf "$kit_root/release/mihomoctl-1.2.0.tar.gz" -C "$source_parent" &&
cd "$source_parent/mihomoctl-1.2.0" &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse" --dry-run &&
bash install.sh --user --python /usr/bin/python3 --wheelhouse "$kit_root/wheelhouse"
```

The installer uses `--no-index` with local wheelhouse, never downloads dependencies and does not start services. Upgrade old versions with the verified new installer, without depending on the old CLI's release or --latest support. A normal source archive alone has no complete dependencies: provide a trusted wheelhouse or an existing trusted Python environment with all dependencies.

## Complete core setup and initialization

Set PATH for this terminal only. For strict offline use also disable unrelated background update queries:

```bash
export PATH="$HOME/.local/bin:$PATH"
export MIHOMOCTL_NO_UPDATE_CHECK=1
mihomoctl version
/usr/bin/python3 "$source_parent/mihomoctl-1.2.0/scripts/bootstrap.py" verify --user
```

Run verify using the Python selected during installation. Without a manager, use the prepared trusted core and [setup](setup.md) to init exactly once and validate configuration; preserve an existing manager without reinstalling its core. Leave the runtime stopped by default. Report controller, core and initialization separately; runtime health and remote routing remain UNVERIFIED. Retain the self-contained backup reported by the installer and the working directory; see [upgrade/rollback](update.md). Restoring controller code does not remove newly initialized user data.
