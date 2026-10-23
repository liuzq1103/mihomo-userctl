# Update and failure recovery

Transfer a verified complete bundle to the server, then run:

```bash
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz --dry-run
mihomoctl update /absolute/path/to/verified-portable-bundle.tar.gz
```

Migrate a source installation with the new bundle's `./install.sh --user`; the old updater does not need to understand the new format. `mihomoctl update --latest` requires connectivity and a published, verified portable release and release gate.

Successful updates keep only current code and delete managed old versions and backups. They preserve user configuration, do not replace an active core, restart services or edit shell startup files. `mihomoctl rollback BACKUP` returns `historical-rollback-disabled`.

An unsuccessful operation restores its previous state before cleanup. Interrupted operations are recovered on the next operation/UI launch. Failed recovery or an unrelated manual edit preserves temporary material and reports an error. Historical versions cannot be restored; intentional reinstallation requires another verified package.

Close all mihomoctl interfaces for this account before installation, update or uninstall. Otherwise `installation-console-open` refuses the change before switching. This leaves the core running. A committed-cleanup-pending error means the new state is active; the next locked operation retries cleanup. Do not assume an old version or configuration was restored after that error.
