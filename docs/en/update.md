# Upgrade and rollback

## Installed 1.2.0 and compatible later releases

```bash
mihomoctl release check
mihomoctl update --latest --dry-run
mihomoctl update --latest
```

Checks report the official stable version observed at a particular time, never
that an installed version is the latest. Optional interactive status/version/doctor/TUI
checks run in a detached worker with a five-second lifetime and a daily attempt
limit; a later entry displays each newer version once per scope. Optional failures
preserve the original exit code. Explicit network failures return 2 / UNVERIFIED.
Set `MIHOMOCTL_NO_UPDATE_CHECK=1` to disable automatic checks. JSON, pipes and other
commands do not trigger checks.

`update --latest` fixes one observed release, acquires and validates it, then calls
the original offline installer. Supported Ubuntu environments prefer a complete kit;
an explicit `--wheelhouse` selects the normal release and those local dependencies.
Other environments use installed dependencies or require a compatible local wheelhouse;
there is no automatic PyPI fallback. Dry-run can download and validate but does not
switch installations. SOURCE and --latest are exclusive; a missing source is still
rejected. `mihomoctl update SOURCE` remains entirely offline.

## Acquire on one machine, install on another

```bash
mihomoctl release fetch --output-dir "$HOME/releases/mihomoctl-kit" --target ubuntu22.04-x86_64-py310
```

The other target is `ubuntu24.04-x86_64-py312`; choose the destination environment.
Fetch only obtains and verifies files. Use `--version v1.2.0` to pin a release.
Without a target it fetches normal source archives, wheel, checksums, receipt and
gate evidence without dependencies. The output directory must not exist; failed
downloads never publish a partial result or overwrite existing files.

Transfer the entire directory to a private location on the destination. Source
archives are under kit/release and dependencies under kit/wheelhouse; acquisition.json
uses relative paths. Extract the source and use its new install.sh offline. An
existing compatible CLI can instead use `update SOURCE --wheelhouse DIR` with the
archive path. See [offline installation](offline-install.md).

Existing v1.0.0–v1.1.1 binaries have neither these commands nor automatic discovery.
Continue using the verified new installer described below; notifications are an
additional information channel.

Use [INSTALL.md](../../INSTALL.md) and the verified **1.2.0 installer** to upgrade v1.0.x. The old updater may reject reorganized sources because it expects obsolete Bash version markers; do not add shims or bypass its checks. Run the new installer from a complete verified release tree, with its dependency wheelhouse and explicit interpreter as needed.

Installation creates a private backup and reports its path. It swaps code/launcher only and does not restart Mihomo or applications. Verify the installed version and run the new installer's `scripts/bootstrap.py verify`. Keep the backup until satisfied. For recovery use the self-contained copied driver:

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

The driver includes the recovery engine; original sources are unnecessary. Existing configuration/credentials/subscriptions/cache/core remain intact. New versions must pass protocol, version, source/wheel inventory, dependency and private-path checks. `mihomoctl update SOURCE --dry-run` previews future compatible updates; never use an unverified checkout as a release.
