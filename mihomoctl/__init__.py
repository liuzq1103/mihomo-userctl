"""Mihomo lifecycle and explicit proxy environment management."""
import os
from pathlib import Path
import stat
import sys

__version__ = '1.2.0'
SCHEMA = 'mihomoctl/v1'


def _validate_runtime():
    """Reject writable executable modules before importing the application.

    Administrative invocation must still originate from a trusted installed
    entry point: no Python package can protect an interpreter that has already
    been instructed to execute an attacker-controlled package initializer.
    """
    if sys.platform != 'linux':
        return
    uid = os.geteuid()
    root = Path(__file__).absolute().parent
    owners = {0} if uid == 0 else {0, uid}
    paths = list(root.rglob('*.py')) + [root]
    checked = set()
    for path in paths:
        for item in (path, *path.parents):
            if item in checked:
                continue
            checked.add(item)
            info = item.lstat()
            sticky = stat.S_ISDIR(info.st_mode) and info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if stat.S_ISLNK(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o022 and not sticky:
                if '--json' in sys.argv:
                    print('{"schema":"mihomoctl/v1","command":"mihomoctl","scope":"system"' if '--system' in sys.argv else '{"schema":"mihomoctl/v1","command":"mihomoctl","scope":"user"', end='')
                    print(',"overall":"UNVERIFIED","data":{},"checks":[],"errors":[{"code":"runtime-untrusted"}]}')
                else:
                    print('mihomoctl: runtime-untrusted; use trusted installed code with safe ownership and permissions', file=sys.stderr)
                raise SystemExit(2)


_validate_runtime()
