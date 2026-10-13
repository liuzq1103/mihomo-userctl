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
    pass


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
        fd = int(inherited)
        if os.fstat(fd).st_ino != lock.stat().st_ino or os.fstat(fd).st_dev != lock.stat().st_dev:
            raise InstallError("invalid-inherited-lock")
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
