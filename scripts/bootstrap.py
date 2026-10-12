#!/usr/bin/env python3
"""mihomoctl V1 installer driver (installation protocol 2).

Bash (install.sh/uninstall.sh) is only a bootstrap: it finds a Python 3.10+
interpreter and execs this script.  Everything here is offline and local:

- no shell startup file is ever written (.bashrc/.zshrc/profile untouched);
- no service, unit or third-party daemon is started, stopped or reloaded;
- no proxy and no network access is required or used;
- existing Mihomo cores are never adopted, replaced or removed;
- default scope is the current user; ``--system`` requires root.

Sources: a release source tree, a release .tar.gz/.zip archive, a directory
holding the mihomoctl wheel (``--wheelhouse`` adds dependency wheels).
Old protocol-1 sources are refused before any write.

Self-contained rollback: every install/uninstall backup carries a copy of
this script; ``python3 <backup>/bootstrap.py rollback <backup>`` restores
the previous state without the original source tree.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import stat

REPO_ROOT = Path(__file__).resolve().parents[1]


def _validate_code(root):
    owners = {0} if os.geteuid() == 0 else {0, os.geteuid()}
    paths = list(Path(root).parents) + [Path(root)]
    paths += [p for p in Path(root).rglob("*") if "__pycache__" not in p.parts]
    for path in paths:
        info = path.lstat()
        sticky_root = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in owners or (info.st_mode & 0o022 and not sticky_root):
            print("bootstrap: untrusted installation code path", file=sys.stderr)
            raise SystemExit(2)


def _install_engine():
    """Locate mihomoctl.installation near this script, in an installation
    (current generation or a rollback backup tree), or on the system path."""
    candidates = [Path(__file__).resolve().parent / "recovery", REPO_ROOT]
    backup_root = Path(__file__).resolve().parent
    if backup_root.name == "install-backups" or (backup_root / "tree").is_dir():
        # Running from inside a self-contained backup.
        for record in sorted(backup_root.glob("*/tree/record.json")):
            candidates.append(record.parent / "lib")
    home = os.environ.get("HOME", "")
    data_home = os.environ.get("XDG_DATA_HOME") or (Path(home) / ".local/share" if home else "")
    if data_home:
        pointer = Path(data_home) / "mihomoctl" / "install" / "current"
        if pointer.is_symlink():
            candidates.append(pointer / "lib")
    for candidate in candidates:
        if (candidate / "mihomoctl" / "installation.py").is_file():
            _validate_code(candidate)
            sys.path.insert(0, str(candidate))
            break
    else:
        print("bootstrap: cannot locate the mihomoctl package next to this script",
              file=sys.stderr)
        raise SystemExit(2)
    from mihomoctl import installation
    from mihomoctl.errors import MihomoctlError
    from mihomoctl.scope import Scope
    return installation, MihomoctlError, Scope


def _scope_from_args(args, installation, Scope, *, require_system=False):
    if args.system and os.geteuid() != 0:
        raise installation.InstallationError(
            "scope-violation", "system scope requires root; rerun with sudo or drop --system")
    return Scope(system=bool(args.system))


def _emit(result):
    print(json.dumps(result, sort_keys=True, indent=2))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="bootstrap.py", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    install_parser = commands.add_parser("install", help="install or update mihomoctl (default user scope)")
    install_parser.add_argument("--user", action="store_true", help="install for the current user (default)")
    install_parser.add_argument("--system", action="store_true",
                                help="system installation (requires root; explicit opt-in)")
    source = install_parser
    source.add_argument("--source", type=Path, default=None,
                        help="source tree, release .tar.gz/.zip, or wheel directory (default: this tree)")
    source.add_argument("--wheelhouse", type=Path, default=None,
                        help="directory with dependency wheels for offline installation")
    install_parser.add_argument("--manifest", type=Path, default=None,
                                help="explicit release-manifest.json path")
    install_parser.add_argument("--python", default=None,
                                help="interpreter for the installed launcher (default: /usr/bin/python3)")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--allow-same-version", action="store_true")
    install_parser.add_argument("--allow-downgrade", action="store_true")

    uninstall_parser = commands.add_parser("uninstall", help="remove installed code and launcher only")
    uninstall_parser.add_argument("--user", action="store_true")
    uninstall_parser.add_argument("--system", action="store_true")
    uninstall_parser.add_argument("--dry-run", action="store_true")

    rollback_parser = commands.add_parser("rollback", help="restore a backup created by install/uninstall")
    rollback_parser.add_argument("backup", type=Path)
    rollback_parser.add_argument("--user", action="store_true")
    rollback_parser.add_argument("--system", action="store_true")
    rollback_parser.add_argument("--dry-run", action="store_true")

    verify_parser = commands.add_parser("verify", help="verify the active installation")
    verify_parser.add_argument("--user", action="store_true")
    verify_parser.add_argument("--system", action="store_true")

    status_parser = commands.add_parser("status", help="show installation status as JSON")
    status_parser.add_argument("--user", action="store_true")
    status_parser.add_argument("--system", action="store_true")

    prune_parser = commands.add_parser("prune", help="delete old generations (keeps the active one)")
    prune_parser.add_argument("--keep", type=int, default=3)
    prune_parser.add_argument("--user", action="store_true")
    prune_parser.add_argument("--system", action="store_true")

    args = parser.parse_args(argv)
    installation, MihomoctlError, Scope = _install_engine()
    if getattr(args, "user", False) and getattr(args, "system", False):
        parser.error("--user and --system are mutually exclusive")
    try:
        if args.command == "rollback":
            # The scope is recorded inside the backup; honor it over flags.
            transaction = json.loads((args.backup / "transaction.json").read_text(encoding="utf-8"))
            scope = Scope(system=bool(args.system))
            result = installation.rollback(scope, args.backup, dry_run=args.dry_run)
        else:
            scope = _scope_from_args(args, installation, Scope)
            if args.command == "install":
                result = installation.install(
                    scope, args.source or REPO_ROOT, wheelhouse=args.wheelhouse,
                    manifest_path=args.manifest, python=args.python, dry_run=args.dry_run,
                    allow_same_version=args.allow_same_version,
                    allow_downgrade=args.allow_downgrade)
            elif args.command == "uninstall":
                result = installation.uninstall(scope, dry_run=args.dry_run)
            elif args.command == "verify":
                record = installation.verify_installed(scope)
                result = {"version": record["version"], "generation": record["generation"],
                          "install_root": record["install_root"], "bin_link": record["bin_link"],
                          "python": record["python"], "overall": "PASS"}
            elif args.command == "status":
                result = installation.installation_status(scope)
            else:
                result = {"removed": installation.prune_generations(scope, keep=max(args.keep, 0))}
        if isinstance(result, dict):
            for note in result.pop("notes", []):
                print("note: " + note)
            _emit(result)
        return 0
    except MihomoctlError as error:
        print("bootstrap: %s" % error.render(), file=sys.stderr)
        return error.exit_code
    except (OSError, ValueError) as exc:
        print("bootstrap: operation failed: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
