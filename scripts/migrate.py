#!/usr/bin/env python3
"""One-time, explicit-path migration for flat pre-update installations.

Run only from an inspected official source snapshot. Download/validation and
installation are shared with the updater; historical provenance stays unknown.
"""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

try:
    from . import update as up
except ImportError:
    import update as up

ins = up.installer


def main(argv=None, client=None):
    parser = up.Parser(description=__doc__)
    parser.add_argument("--version", required=True, metavar="TAG")
    parser.add_argument("--config-home", required=True)
    parser.add_argument("--data-home", required=True)
    parser.add_argument("--bashrc", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    up.version(args.version)
    home = ins.safe_path(os.environ["HOME"], True)
    config = ins.safe_path(args.config_home, True)
    data = ins.safe_path(args.data_home, True)
    startup = ins.safe_path(args.bashrc)
    root = ins.safe_path(data / "mihomo-userctl", True)
    if home not in startup.parents:
        raise up.UpdateError("startup-file-must-be-inside-HOME", 2)
    if (root / "current").is_symlink():
        raise up.UpdateError("generation-installation-use-update-or-restore-backup", 2)
    if (root / "pending-install.json").exists():
        raise up.UpdateError("interrupted-installation-restore-backup-first", 2)
    controller = ins.safe_path(home / ".local/bin/mihomoctl")
    common = ins.safe_path(root / "common.bash")
    if not controller.is_file() or not common.is_file() or not startup.is_file():
        raise up.UpdateError("legacy-installation-not-found-at-explicit-paths", 2)
    match = re.search(r'^MIHOMO_USERCTL_VERSION="([0-9]+\.[0-9]+\.[0-9]+)"$', common.read_text(), re.M)
    if match is None:
        raise up.UpdateError("legacy-version-cannot-be-established-review-local-code", 2)
    if up.version(args.version) < up.version("v" + match[1]):
        raise up.UpdateError("migration-downgrade-refused", 2)
    record = dict(home=str(home), config_home=str(config), data_home=str(data), bashrc=str(startup),
                  bin_file=str(controller), install_root=str(root), version=match[1], generation=None)
    up.emit("PASS", "current-version", match[1])
    up.emit("UNVERIFIED", "historical-source", "unknown;not-reconstructed-by-migration")
    client = client or up.GitHub()
    with ins.locked(data) as fd:
        config_values = up.settings(record)
        target = client.resolve(args.version)
        if target["tag"] != args.version:
            raise up.UpdateError("release-tag-mismatch")
        up.emit("PASS", "target-source", "tag=" + target["tag"] + ";commit=" + target["commit"])
        up.emit("PASS", "source-archive", target["archive_url"] + ";release-id=" + str(target["release_id"]))
        temporary = ins.safe_path(data / "mihomo-userctl-downloads", True)
        temporary.mkdir(parents=True, mode=0o700, exist_ok=True)
        if temporary.stat().st_mode & 0o077:
            raise up.UpdateError("download-directory-must-be-private", 2)
        with tempfile.TemporaryDirectory(prefix="migration-", dir=temporary) as work:
            work = Path(work)
            archive = work / "source.zip"
            client.archive(target, archive)
            up.emit("PASS", "download-sha256", target["archive_sha256"] + ";calculated-locally")
            up.emit("UNVERIFIED", "independent-archive-verification", "official-digest-and-signature-not-provided")
            source = up.extract(archive, work / "source")
            up.validate(source, args.version)
            if args.dry_run:
                state = up.service_state(config_values["MIHOMO_SERVICE"])
                up.emit("PASS", "migration-plan", "flat-to-atomic-generations;launcher-and-managed-loader-replaced")
                up.emit("PASS", "install-root", str(root))
                up.emit("PASS", "startup-file", str(startup))
                up.emit("PASS", "service-state-to-preserve", ";".join(state))
                up.emit("PASS", "backup-plan", str(data / "mihomo-userctl-backups") + ";restore.py-rollback")
                up.emit("UNVERIFIED", "local-customizations", "review-old-managed-code-against-official-source-before-applying")
                return 0
            return up.apply(source, target, record, config_values, fd)


def cli(argv=None, client=None):
    try:
        return main(argv, client)
    except up.UpdateError as error:
        up.emit("FAIL", "migration", str(error))
        return error.code
    except ins.InstallError as error:
        up.emit("FAIL", "migration", str(error))
        return 4 if "another-install" in str(error) else 2
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        up.emit("FAIL", "migration", "operation-failed;private-values-suppressed;inspect-local-backup")
        return 1


if __name__ == "__main__":
    sys.exit(cli())
