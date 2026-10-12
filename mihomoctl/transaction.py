"""Staged mutations with real rollback.

Phases: lock -> stage (private staging) -> backup -> publish (atomic
replace) -> activate -> acceptance -> finalize.  Rollback replays the
journal in reverse and RESTORES prior content AND file metadata (mode,
uid, gid; symlinks recorded explicitly by type, never by content magic);
a rollback that itself fails is reported as a distinct ``rollback-failed``
error, never silently downgraded.

Publish hardening:
- destinations are range-checked against managed roots (scope roots and,
  for system scope, the managed unit paths);
- temp files come from mkstemp (0600 from creation, no umask window, no
  predictable names, no symlink-following copies), fsynced and replaced
  atomically;
- managed paths must never be symlinks at publish time.
"""

import errno
import hashlib
import json
import os
import shutil
import stat
import tempfile
import time
import uuid
from pathlib import Path

from .errors import RollbackFailedError, TransactionError
from .trust import require_private_dir

XDG_UNIT_HINT = "systemd/user"


class Transaction:
    def __init__(self, scope, name="operation", allow_paths=()):
        self.scope = scope
        self.name = name
        self.allow_paths = set(map(Path, allow_paths))
        self.id = "%s-%s" % (name, uuid.uuid4().hex[:12])
        self.staging = Path(tempfile.mkdtemp(prefix=self.id + "-",
                                             dir=self._ensure(self.scope.staging_root)))
        self.backup_root = self.scope.backups_root / self.id
        self.journal = []
        self.finished = False

    @staticmethod
    def _ensure(path):
        require_private_dir(path, create=True)
        return str(path)

    # -- destination range checks --------------------------------------
    def _check_destination(self, destination: Path):
        import sys
        if sys.platform == "win32":
            return
        if not destination.is_absolute() or '..' in destination.parts:
            raise TransactionError('destination-outside-managed-roots', 'non-canonical destination')
        from .trust import _check_ancestors
        _check_ancestors(destination, 'destination-unsafe', owners={0, os.geteuid()})
        if destination in self.allow_paths:
            return
        if destination.is_symlink():
            raise TransactionError("refuse-symlink-destination", str(destination))
        roots = [self.scope.config_root, self.scope.data_root,
                 self.scope.state_root, self.scope.cache_root]
        if self.scope.system:
            roots += [Path("/etc/mihomoctl"), Path("/etc/systemd/system"),
                      Path("/var/lib/mihomoctl"), Path("/run/mihomoctl")]
        else:
            config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
            roots.append(config_home / XDG_UNIT_HINT)
        for root in roots:
            try:
                destination.relative_to(root)
                return
            except ValueError:
                continue
        raise TransactionError("destination-outside-managed-roots", str(destination))

    # -- staging --------------------------------------------------------
    def stage(self, name, text, mode=0o600):
        path = self.staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        os.chmod(str(path), mode)
        return path

    def stage_bytes(self, name, data, mode=0o600):
        path = self.staging / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        os.chmod(str(path), mode)
        return path

    # -- publish --------------------------------------------------------
    def publish(self, staged: Path, destination: Path, mode=None, backup=True):
        destination = Path(destination)
        self._check_destination(destination)
        record = {"op": "publish", "path": str(destination)}
        existed = destination.exists() or destination.is_symlink()
        if existed:
            self._capture_metadata(record, destination)
            record["backup"] = str(self._backup(destination, record))
            record["existed"] = True
        else:
            record["created"] = True
        # Create every missing component privately; retain existing system unit
        # directory permissions rather than chmod'ing shared OS directories.
        missing = []
        cursor = destination.parent
        while not cursor.exists():
            missing.append(cursor)
            cursor = cursor.parent
        for component in reversed(missing):
            component.mkdir(mode=0o700)
        record['created_dirs'] = list(map(str, missing))
        target_mode = mode if mode is not None else int(record.get("mode", oct(0o600)), 8)
        data = staged.read_bytes()
        self.journal.append(record)
        _atomic_write_bytes(destination, data, target_mode)
        record['published_sha256'] = hashlib.sha256(data).hexdigest()
        if existed and os.geteuid() == 0:
            os.chown(str(destination), record['uid'], record['gid'])
        return destination

    def write_text(self, destination, text, mode=0o600, backup=True):
        staged = self.stage("publish-" + Path(destination).name, text, mode)
        return self.publish(staged, destination, mode=mode, backup=backup)

    def write_bytes(self, destination, data, mode=0o600, backup=True):
        staged = self.stage_bytes("publish-" + Path(destination).name, data, mode)
        return self.publish(staged, destination, mode=mode, backup=backup)

    def delete(self, path, require_managed_marker=None):
        """Remove a file inside the transaction (rollback restores content
        and metadata)."""
        path = Path(path)
        self._check_destination(path)
        if not (path.exists() or path.is_symlink()):
            return False
        if require_managed_marker is not None:
            try:
                text = path.read_text(encoding="utf-8")
            except OSError:
                raise TransactionError("refuse-delete", str(path)) from None
            if not text.startswith(require_managed_marker):
                raise TransactionError("refuse-delete",
                                       "%s is not managed by mihomoctl" % path)
        record = {"op": "delete", "path": str(path)}
        self._capture_metadata(record, path)
        record["backup"] = str(self._backup(path, record))
        self.journal.append(record)
        path.unlink()
        return True

    @staticmethod
    def _capture_metadata(record, path: Path):
        info = os.lstat(str(path))
        if stat.S_ISLNK(info.st_mode):
            record["type"] = "symlink"
            record["symlink_target"] = os.readlink(str(path))
        elif stat.S_ISDIR(info.st_mode):
            record["type"] = "dir"
        elif stat.S_ISREG(info.st_mode):
            record["type"] = "file"
        else:
            raise TransactionError("refuse-unusual-file", str(path))
        record["mode"] = oct(stat.S_IMODE(info.st_mode))
        record["uid"] = info.st_uid
        record["gid"] = info.st_gid

    def _backup(self, path: Path, record):
        self._ensure(self.backup_root)
        relative = str(path).replace(os.sep, "_").lstrip("/")[-180:]
        saved = self.backup_root / ("%d-%s" % (len(self.journal), relative))
        if record.get("type") == "symlink":
            # The target lives in the journal record; no content file.
            return saved
        if record.get("type") == "dir":
            shutil.copytree(str(path), str(saved))
            return saved
        data = path.read_bytes()
        fd = os.open(str(saved), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return saved

    # -- completion -----------------------------------------------------
    def commit(self):
        """Finalize: persist the journal for audit, then clean staging.
        Backups are retained (GC is an explicit separate operation)."""
        self._ensure(self.backup_root)
        document = json.dumps({"id": self.id, "name": self.name,
                               "at": int(time.time()), "journal": self.journal}, indent=1) + "\n"
        _atomic_write_bytes(self.backup_root / 'journal.json', document.encode(), 0o600)
        self.finished = True
        shutil.rmtree(str(self.staging), ignore_errors=True)

    def rollback(self):
        """Restore every journaled path: content AND metadata.  A failure
        to fully restore is a distinct rollback failure."""
        failures = []
        for record in reversed(self.journal):
            try:
                path = Path(record["path"])
                backup = Path(record["backup"]) if record.get("backup") else None
                kind = record.get("type", "file")
                created = bool(record.get("created"))
                if record["op"] == "publish" and created:
                    if path.exists() or path.is_symlink():
                        if path.is_dir() and not path.is_symlink():
                            shutil.rmtree(str(path))
                        else:
                            path.unlink()
                    for directory in record.get('created_dirs', []):
                        try:
                            Path(directory).rmdir()
                        except FileNotFoundError:
                            pass
                        except OSError as exc:
                            if exc.errno not in (errno.ENOTEMPTY, errno.EEXIST):
                                raise
                    continue
                if record["op"] == "delete":
                    # restore from backup (or recreate the symlink)
                    self._restore(path, backup, record)
                    continue
                # publish over an existing target: restore prior state
                if kind == "symlink" or record.get("symlink_target") is not None:
                    if path.exists() or path.is_symlink():
                        path.unlink()
                    os.symlink(record["symlink_target"], str(path))
                elif kind == "dir":
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(str(path))
                    elif path.exists() or path.is_symlink():
                        path.unlink()
                    if backup is not None and backup.is_dir():
                        shutil.copytree(str(backup), str(path))
                else:
                    if backup is None or not backup.exists():
                        if path.exists() or path.is_symlink():
                            path.unlink()
                    else:
                        self._restore(path, backup, record)
            except (OSError, ValueError, KeyError) as exc:
                failures.append("%s (%s)" % (record.get("path", "?"), exc.__class__.__name__))
        shutil.rmtree(str(self.staging), ignore_errors=True)
        self.finished = True
        if failures:
            raise RollbackFailedError("rollback-failed",
                                      "could not restore: %s; backups kept at %s"
                                      % (sorted(set(failures)), self.backup_root))

    @staticmethod
    def _restore(path: Path, backup: Path, record):
        if record.get("type") == "symlink":
            if path.exists() or path.is_symlink():
                path.unlink()
            os.symlink(record["symlink_target"], str(path))
            return
        data = backup.read_bytes()
        mode = int(record.get("mode", oct(0o600)), 8)
        _atomic_write_bytes(path, data, mode)
        uid, gid = record.get("uid"), record.get("gid")
        if uid is not None and gid is not None and hasattr(os, "geteuid"):
            try:
                current = os.stat(str(path))
                if (current.st_uid, current.st_gid) != (uid, gid) and os.geteuid() == 0:
                    os.chown(str(path), uid, gid)
            except OSError:
                pass  # ownership restore best-effort for non-root


def _atomic_write_bytes(destination: Path, data: bytes, mode):
    """mkstemp (0600 at creation) + write + fsync + atomic replace.
    Never follows symlinks, never exposes a umask window."""
    fd, temporary = tempfile.mkstemp(prefix="." + destination.name + "-",
                                     dir=str(destination.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if os.path.islink(str(destination)):
            raise TransactionError("refuse-symlink-destination", str(destination))
        os.replace(temporary, str(destination))
        if hasattr(os, 'O_DIRECTORY'):
            parent_fd = os.open(str(destination.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def run_transaction(scope, name, action, allow_paths=()):
    """Run ``action(tx)``; on any exception roll back for real and re-raise
    (rollback failure replaces the error as the highest-priority report).

    All mutations share the scope's default operation lock so installs,
    updates, core activation and TUN transactions are mutually exclusive."""
    from .locks import operation_lock
    with operation_lock(scope):
        tx = Transaction(scope, name, allow_paths=allow_paths)
        try:
            result = action(tx)
            tx.commit()
        except BaseException as exc:
            if not tx.finished:
                try:
                    tx.rollback()
                except RollbackFailedError as rollback_exc:
                    raise rollback_exc from exc
            raise
        return result


def restore_backup(scope, backup):
    """Explicit rollback of this scope's file journal, refusing later drift."""
    from .locks import operation_lock
    from .trust import require_private_file
    scope.require_mutation()
    backup = Path(backup).absolute()
    if backup.parent != scope.backups_root or backup.is_symlink():
        raise TransactionError('rollback-backup-untrusted', 'backup must belong to this scope')
    require_private_dir(backup)
    journal_file = backup / 'journal.json'
    require_private_file(journal_file)
    document = json.loads(journal_file.read_text(encoding='utf-8'))
    if document.get('name') != 'migrate' or document.get('id') != backup.name:
        raise TransactionError('rollback-kind-unsupported', 'only explicit migration journals use this rollback entry')
    shell_paths = {Path.home() / name for name in ('.bashrc', '.zshrc', '.profile')} if not scope.system else set()
    with operation_lock(scope):
        tx = Transaction(scope, 'migration-rollback', allow_paths=shell_paths)
        tx.backup_root = backup
        try:
            tx.journal = document.get('journal', [])
            if not isinstance(tx.journal, list) or not tx.journal:
                raise TransactionError('rollback-journal-invalid')
            for record in tx.journal:
                if not isinstance(record, dict) or record.get('op') != 'publish' or \
                        record.get('type', 'file') != 'file' or not isinstance(record.get('path'), str):
                    raise TransactionError('rollback-journal-invalid')
                path = Path(record['path'])
                tx._check_destination(path)
                saved = record.get('backup')
                if saved:
                    if Path(saved).parent != backup:
                        raise TransactionError('rollback-journal-invalid', 'backup member escapes the journal directory')
                    require_private_file(Path(saved))
                elif not record.get('created'):
                    raise TransactionError('rollback-journal-invalid', 'prior contents are missing')
                for directory in record.get('created_dirs', []):
                    if not Path(directory).is_absolute() or Path(directory) not in path.parents:
                        raise TransactionError('rollback-journal-invalid', 'created directory is unrelated to destination')
            # Compare only the final publication of a repeatedly written path.
            final = {record['path']: record for record in tx.journal}
            for filename, record in final.items():
                path = Path(filename)
                if not path.is_file() or path.is_symlink() or \
                        hashlib.sha256(path.read_bytes()).hexdigest() != record.get('published_sha256'):
                    raise TransactionError('rollback-current-drifted', 'a migrated file changed after publication')
            tx.rollback()
        finally:
            shutil.rmtree(str(tx.staging), ignore_errors=True)
        return {'restored': True, 'backup': str(backup), 'kind': 'migration'}
