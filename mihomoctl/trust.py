"""File and directory trust validation.

Owner rules:
- Private data files/dirs: owned by the acting UID, mode 0600/0700.
- Trusted installed code: root-owned (system install) or user-owned;
  never group/other writable.  Root-owned code is explicitly trusted so
  wheel installs under system site-packages work for ordinary users.
- Executables: root-owned read-only binaries may be referenced and run by
  users; when validated/executed as root the ancestor chain must be
  root-owned or sticky-root (never user-replaceable).

Directory creation validates every existing ancestor (no symlink
traversal, no unsafe writability) before any mkdir call.
"""

import os
import stat
import sys
from pathlib import Path

from .errors import ConfigError

_IS_WINDOWS = sys.platform == "win32"


def _uid():
    return os.geteuid() if hasattr(os, "geteuid") else (os.getuid() if hasattr(os, "getuid") else 0)


def _lstat(path):
    return os.lstat(str(path))


def _safe_writable(info):
    """A directory whose contents we control must not be replaceable by
    others: reject group/other-writable unless it is root-owned + sticky."""
    if info.st_mode & 0o022:
        return bool(info.st_uid == 0 and info.st_mode & stat.S_ISVTX)
    return True


def _check_ancestors(path, code, owners):
    """Validate every existing ancestor of ``path`` (excluding ``path``):
    no symlinks, owner within ``owners`` (uid or root), safe writability.
    Non-existing tail components are fine (they will be created 0700)."""
    for ancestor in reversed([p for p in path.parents]):
        try:
            info = _lstat(ancestor)
        except OSError:
            continue  # not present yet; created later with 0700
        if stat.S_ISLNK(info.st_mode):
            raise ConfigError(code, "symlink in path ancestry rejected: %s" % ancestor)
        if not stat.S_ISDIR(info.st_mode):
            raise ConfigError(code, "path ancestor is not a directory: %s" % ancestor)
        if _IS_WINDOWS:
            continue
        if info.st_uid not in owners:
            raise ConfigError(code, "path ancestor has unexpected owner (uid %d): %s" % (info.st_uid, ancestor))
        if not _safe_writable(info):
            raise ConfigError(code, "path ancestor is group/other writable: %s" % ancestor)


# ---------------------------------------------------------------------------
# Private data (0600/0700, acting-UID owned)
# ---------------------------------------------------------------------------

def require_private_file(path, code="config-invalid"):
    """Enforce: regular file, no symlink, owned by us, mode 0600."""
    path = Path(path)
    _check_ancestors(path, code, owners={0, _uid()} if not _IS_WINDOWS else set())
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError(code, "missing or unreadable: %s (%s)" % (path, exc.strerror)) from None
    if stat.S_ISLNK(info.st_mode):
        raise ConfigError(code, "symlink rejected: %s" % path)
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(code, "not a regular file: %s" % path)
    if _IS_WINDOWS:
        return info  # ownership/mode checks are Linux-only contracts.
    if info.st_uid != _uid():
        raise ConfigError(code, "file is not owned by the current user: %s" % path)
    if stat.S_IMODE(info.st_mode) != 0o600:
        raise ConfigError(code, "file must have mode 600: %s" % path)
    return info


def require_private_dir(path, create=False, code="config-invalid"):
    """Enforce a 0700 owned directory; optionally create it (parents too).

    Creation validates all existing ancestors first (symlinks, ownership,
    writability) so mkdir never follows an attacker-placed symlink.
    Ancestors may be root-owned (/, /home, sticky /tmp are the normal
    case); the private directory itself must be owned by the acting UID
    with mode 0700."""
    path = Path(path)
    _check_ancestors(path, code, owners={0, _uid()})
    if create:
        try:
            # Path.mkdir(parents=True) applies mode only to the final component;
            # intermediate state/config roots must be private from creation too.
            missing = []
            cursor = path
            while not cursor.exists():
                missing.append(cursor)
                cursor = cursor.parent
            for component in reversed(missing):
                component.mkdir(mode=0o700)
        except OSError as exc:
            raise ConfigError(code, "cannot create directory %s (%s)" % (path, exc.strerror)) from None
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError(code, "missing directory: %s (%s)" % (path, exc.strerror)) from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConfigError(code, "not a directory: %s" % path)
    if _IS_WINDOWS:
        return info
    if info.st_uid != _uid():
        raise ConfigError(code, "directory is not owned by the current user: %s" % path)
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise ConfigError(code, "directory must not be group/other accessible: %s" % path)
    return info


# ---------------------------------------------------------------------------
# Trusted installed code (root-owned or user-owned, never g/o writable)
# ---------------------------------------------------------------------------

def require_trusted_code_file(path):
    path = Path(path)
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError("runtime-untrusted", "missing code file: %s" % path) from None
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError("runtime-untrusted", "not a regular file: %s" % path)
    if _IS_WINDOWS:
        return info
    if info.st_uid not in (0, _uid()):
        raise ConfigError("runtime-untrusted", "code is not owned by root or the current user: %s" % path)
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ConfigError("runtime-untrusted", "code must not be group/other writable: %s" % path)
    return info


def require_trusted_dir(path):
    path = Path(path)
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError("runtime-untrusted", "missing directory: %s" % path) from None
    if not stat.S_ISDIR(info.st_mode):
        raise ConfigError("runtime-untrusted", "not a directory: %s" % path)
    if _IS_WINDOWS:
        return info
    if info.st_uid not in (0, _uid()):
        raise ConfigError("runtime-untrusted", "directory not owned by root or the current user: %s" % path)
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ConfigError("runtime-untrusted", "directory must not be group/other writable: %s" % path)
    return info


# ---------------------------------------------------------------------------
# Executables (core binary adoption and execution)
# ---------------------------------------------------------------------------

def require_readable_core_config(path, system_scope=False, code="config-invalid"):
    """Managed core configuration trust.

    User scope: acting-UID owned, mode 0600.
    System scope: root-owned 0600 (root-private) or 0640 with the
    dedicated service group (core-readable); never user-owned."""
    path = Path(path)
    _check_ancestors(path, code, owners={0} if system_scope and not _IS_WINDOWS else ({0, _uid()} if not _IS_WINDOWS else set()))
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError(code, "missing core config: %s (%s)" % (path, exc.strerror)) from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise ConfigError(code, "core config must be a regular file: %s" % path)
    if _IS_WINDOWS:
        return info
    mode = stat.S_IMODE(info.st_mode)
    if system_scope:
        if info.st_uid != 0:
            raise ConfigError(code, "system core config must be root-owned: %s" % path)
        if mode not in (0o600, 0o640):
            raise ConfigError(code, "system core config must be 0600 or 0640: %s" % path)
        if mode == 0o640:
            group_ok = False
            try:
                import pwd
                entry = pwd.getpwnam("mihomoctl")
                group_ok = info.st_gid == entry.pw_gid
            except KeyError:
                group_ok = False
            if not group_ok:
                raise ConfigError(code, "system core config 0640 must use the mihomoctl service group: %s" % path)
        return info
    if info.st_uid != _uid():
        raise ConfigError(code, "core config is not owned by the current user: %s" % path)
    if mode != 0o600:
        raise ConfigError(code, "core config must have mode 600: %s" % path)
    return info

def require_executable_file(path, code="core-binary-invalid", as_root=False):
    """Binary trust: regular, executable, not group/other writable, owned by
    root or the acting user.

    ``as_root=True`` (system-scope validation/execution) additionally
    requires every ancestor to be root-owned or sticky-root so the binary
    cannot be swapped by a non-root user."""
    path = Path(path)
    try:
        info = _lstat(path)
    except OSError as exc:
        raise ConfigError(code, "missing binary: %s (%s)" % (path, exc.strerror)) from None
    if stat.S_ISLNK(info.st_mode):
        raise ConfigError(code, "binary symlinks are not accepted; reference the trusted real path")
    if not stat.S_ISREG(info.st_mode):
        raise ConfigError(code, "not a regular file: %s" % path)
    if not os.access(str(path), os.X_OK):
        raise ConfigError(code, "not executable: %s" % path)
    if _IS_WINDOWS:
        return info
    if info.st_uid not in (0, _uid()):
        raise ConfigError(code, "binary must be owned by root or the current user: %s" % path)
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise ConfigError(code, "binary must not be group/other writable: %s" % path)
    if as_root:
        _check_ancestors(path, code, owners={0})
    else:
        _check_ancestors(path, code, owners={0, _uid()})
    return info


def is_user_writable(path):
    """True when the acting user can write to path (used to refuse running
    user-writable binaries as root)."""
    path = Path(path)
    if _IS_WINDOWS:
        return True
    try:
        info = _lstat(path)
    except OSError:
        return True
    return info.st_uid == _uid() and (stat.S_IMODE(info.st_mode) & 0o200) != 0
