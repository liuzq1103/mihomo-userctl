"""flock-based operation locks (one mutation at a time per scope)."""

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path

from .errors import LockError
from .trust import require_private_dir


@contextmanager
def operation_lock(scope, name="operation"):
    require_private_dir(scope.runtime_root, create=True)
    path = Path(scope.runtime_root) / (name + ".lock")
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.geteuid():
            raise LockError("operation-in-progress", "lock file ownership mismatch")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            raise LockError("operation-in-progress",
                            "another mihomoctl operation holds the lock") from None
        yield
    finally:
        os.close(fd)
