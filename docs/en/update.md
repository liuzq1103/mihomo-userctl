# Upgrade and rollback

Use [INSTALL.md](../../INSTALL.md) and the verified **1.1.1 installer** to upgrade v1.0.x. The old updater may reject reorganized sources because it expects obsolete Bash version markers; do not add shims or bypass its checks. Run the new installer from a complete verified release tree, with its dependency wheelhouse and explicit interpreter as needed.

Installation creates a private backup and reports its path. It swaps code/launcher only and does not restart Mihomo or applications. Verify the installed version and run the new installer's `scripts/bootstrap.py verify`. Keep the backup until satisfied. For recovery use the self-contained copied driver:

```bash
python3 /absolute/backup/bootstrap.py rollback /absolute/backup
```

The driver includes the recovery engine; original sources are unnecessary. Existing configuration/credentials/subscriptions/cache/core remain intact. New versions must pass protocol, version, source/wheel inventory, dependency and private-path checks. `mihomoctl update SOURCE --dry-run` previews future compatible updates; never use an unverified checkout as a release.
