"""Private file operations shared by the current control plane."""

import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile


class InstallError(Exception):
    def __init__(self, reason):
        self.code = reason if reason in PATH_REASONS else 'controller-operation-unavailable'
        self.safe_detail = PATH_REASONS.get(reason, '')
        super().__init__(self.code)


PATH_REASONS = {
    'another-install-update-or-uninstall-is-running': 'another install, update or uninstall holds the operation lock; wait for it to finish',
    'invalid-inherited-lock': 'the inherited operation lock is invalid; retry without an inherited lock descriptor',
    'path-ancestor-not-owned-by-current-user-or-root': 'a parent directory belongs to another account; move the file into your own private directory',
    'paths-must-be-absolute-without-control-characters': 'use an absolute private path without control characters',
    'parent-path-components-not-supported': 'remove parent (..) components from the path',
    'symlink-path-not-supported': 'use a regular file and real directories, without symbolic links',
    'unsafe-writable-path-ancestor': 'a parent directory is writable by another user; remove group/other write permission',
    'path-not-owned-by-current-user': 'the path must belong to the acting account; do not use another account\'s files',
    'path-is-writable-by-group-or-others': 'group/other write permission is forbidden; for a script run chmod 600 <script-file>',
    'expected-directory': 'the selected path must be a real private directory',
    'metadata-must-have-mode-600': 'metadata must have mode 600',
    'unsafe-lock-directory': 'the operation lock directory must have mode 700',
    'unsafe-operation-lock': 'the operation lock must belong to the acting account with mode 600',
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_path(value, directory=False):
    path = Path(value)
    if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise InstallError("paths-must-be-absolute-without-control-characters")
    if ".." in path.parts:
        raise InstallError("parent-path-components-not-supported")
    for part in [path] + list(path.parents):
        if part.is_symlink():
            raise InstallError("symlink-path-not-supported")
        if part.exists() and part.is_dir() and part.stat().st_uid not in {0, os.getuid()}:
            raise InstallError('path-ancestor-not-owned-by-current-user-or-root')
        # Root-owned sticky /tmp is a valid ancestor of our private staging HOME;
        # writable non-sticky ancestors would allow replacement of owned children.
        if part.exists() and part.is_dir() and part.stat().st_mode & 0o022:
            if not (part.stat().st_uid == 0 and part.stat().st_mode & stat.S_ISVTX):
                raise InstallError("unsafe-writable-path-ancestor")
    ancestor = path if path.exists() else path.parent
    while not ancestor.exists():
        ancestor = ancestor.parent
    if ancestor.stat().st_uid != os.getuid():
        raise InstallError("path-not-owned-by-current-user")
    if ancestor.stat().st_mode & 0o022:
        raise InstallError("path-is-writable-by-group-or-others")
    if directory and path.exists() and not path.is_dir():
        raise InstallError("expected-directory")
    return path


def atomic_bytes(path, data, mode=600):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), int(str(mode), 8))
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        sync_dir(path.parent)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def sync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_file(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_json(path, data):
    atomic_bytes(path, (json.dumps(data, sort_keys=True, indent=2) + "\n").encode())


def owned_json(path):
    path = safe_path(path)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise InstallError("metadata-must-have-mode-600")
    return json.loads(path.read_text())


@contextlib.contextmanager
def locked(data):
    directory = safe_path(Path(data) / "mihomo-userctl-lock", True)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if directory.stat().st_mode & 0o077:
        raise InstallError("unsafe-lock-directory")
    lock = directory / "operation.lock"
    inherited = os.environ.get("MIHOMO_INSTALL_LOCK_FD")
    if inherited:
        try:
            fd = int(inherited)
            info, expected = os.fstat(fd), lock.lstat()
        except (ValueError, OSError):
            raise InstallError('invalid-inherited-lock') from None
        if (info.st_ino, info.st_dev) != (expected.st_ino, expected.st_dev) or \
                not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600:
            raise InstallError("invalid-inherited-lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError('another-install-update-or-uninstall-is-running') from None
        yield fd
        return
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_uid != os.getuid() or stat.S_IMODE(os.fstat(fd).st_mode) != 0o600:
            raise InstallError("unsafe-operation-lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise InstallError("another-install-update-or-uninstall-is-running") from None
        yield fd
    finally:
        os.close(fd)
