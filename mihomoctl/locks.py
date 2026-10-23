"""flock-based operation locks (one mutation at a time per scope)."""

import fcntl
import os
import re
import stat
from contextlib import contextmanager
from pathlib import Path

from .errors import LockError
from .trust import require_private_dir


def _generation_fd(scope, name):
    require_private_dir(scope.runtime_root, create=True)
    path = scope.runtime_root / ('generation-' + name + '.lock')
    fd = os.open(str(path), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        os.close(fd)
        raise LockError('installation-lease-invalid')
    return fd


@contextmanager
def console_generation_lease(scope):
    """Keep an installed interactive session's lazy imports alive until exit."""
    generation = Path(__file__).resolve().parents[2]
    from .installation import InstallPaths
    paths = InstallPaths(scope)
    fd = None
    # Every UI launch recovers once. Installed sessions acquire their lease
    # under that same lock, before another installer can start.
    with operation_lock(scope):
        if generation.parent == paths.generations and re.fullmatch(r'[a-f0-9]{32}', generation.name):
            if not generation.exists():
                raise LockError('installation-updated-relaunch', 'run mihomoctl again to use the current version')
            fd = _generation_fd(scope, generation.name)
            try:
                fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                fd = None
                raise LockError('installation-in-progress') from None
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)


@contextmanager
def idle_generations(scope, include_active=True):
    """Caller holds operation_lock; block deletion of another open console."""
    from .installation import InstallPaths, current_target
    paths, descriptors = InstallPaths(scope), []
    active = current_target(paths)
    try:
        if paths.generations.exists():
            for generation in sorted(paths.generations.iterdir()):
                if not re.fullmatch(r'[a-f0-9]{32}', generation.name):
                    continue
                if not include_active and 'generations/' + generation.name == active:
                    continue
                lease = scope.runtime_root / ('generation-' + generation.name + '.lock')
                if not lease.exists() and not lease.is_symlink():
                    continue
                fd = _generation_fd(scope, generation.name)
                descriptors.append((fd, generation, lease))
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    raise LockError('installation-console-open',
                                    'close other mihomoctl terminal interfaces, then retry') from None
        yield
    finally:
        for fd, generation, lease in descriptors:
            os.close(fd)
            if not generation.exists() and lease.exists():
                from .trust import require_private_file
                require_private_file(lease)
                lease.unlink()


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
        if name == 'operation':
            from .transaction import recover_transactions
            from .installation import recover_pending
            recover_pending(scope)
            recover_transactions(scope)
            from .retention import resume_cleanup
            resume_cleanup(scope)
        yield
    finally:
        os.close(fd)
