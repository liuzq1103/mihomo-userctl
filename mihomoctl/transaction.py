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
        self.runtime = None
        self._persist()

    def _persist(self, state='pending'):
        self._ensure(self.backup_root)
        document = {'id': self.id, 'name': self.name, 'state': state,
                    'staging': str(self.staging), 'journal': self.journal,
                    'runtime': self.runtime,
                    'allow_paths': sorted(map(str, self.allow_paths))}
        _atomic_write_bytes(self.backup_root / 'journal.json',
                            (json.dumps(document) + '\n').encode(), 0o600)

    def _cleanup(self):
        for path in (self.staging, self.backup_root):
            if path.exists():
                shutil.rmtree(path)

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
            if not destination.is_file() or destination.is_symlink():
                raise TransactionError('refuse-non-file-destination', 'file publication requires a regular destination')
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
        record['published_sha256'] = hashlib.sha256(data).hexdigest()
        self.journal.append(record)
        self._persist()
        _atomic_write_bytes(destination, data, target_mode)
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
        if path.is_dir() and not path.is_symlink():
            raise TransactionError('refuse-directory-delete', 'transaction deletion requires a file')
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
        self._persist()
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
        """Commit durably before removing temporary recovery data."""
        self._persist('committed')
        self.finished = True
        self._cleanup()

    def rollback(self, finish=True):
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
        if failures:
            raise RollbackFailedError("rollback-failed",
                                      "could not restore: %s; unfinished transaction retained"
                                      % sorted(set(failures)))
        self._persist('restored')
        if finish:
            self.finished = True
            self._cleanup()

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
            current = os.stat(str(path))
            if (current.st_uid, current.st_gid) != (uid, gid) and os.geteuid() == 0:
                os.chown(str(path), uid, gid)
            restored = os.stat(str(path))
            if (restored.st_uid, restored.st_gid) != (uid, gid):
                raise OSError('ownership restoration incomplete')


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
                if tx.runtime is not None and getattr(exc,'code','') in ('start-cleanup-failed','service-cleanup-unverified'):
                    tx.runtime['phase']='unverified'
                    tx._persist()
                try:
                    restore_failed_operation(tx)
                except RollbackFailedError as rollback_exc:
                    raise rollback_exc from exc
            raise
        from .retention import cleanup_after_commit
        cleanup_after_commit(scope)
        return result


def _runtime_backend(tx):
    from .app import Application
    app = Application(system=tx.scope.system, config_dir=str(tx.scope.config_root))
    manager, endpoints, controller, _profile, _cfg = app.resolve()
    return app, app._backend(manager, endpoints, controller)


def restore_failed_operation(tx):
    """Restore files and any runtime changed by this unfinished operation."""
    if tx.runtime is not None and tx.runtime.get('phase') == 'unverified':
        raise RollbackFailedError('rollback-failed', 'runtime cessation is unverified; recovery journal retained; inspect the managed runtime')
    if tx.runtime is not None and tx.runtime.get('phase') == 'prepared' and not tx.runtime.get('unit_reload'):
        tx.rollback()
        return
    if tx.runtime is not None and tx.runtime.get('phase') != 'prepared':
        _app, backend = _runtime_backend(tx)
        if backend.status().get('running'):
            backend.stop()
    tx.rollback(finish=tx.runtime is None)
    if tx.runtime is not None:
        _restore_runtime(tx)
        tx.finished = True
        tx._cleanup()


def _restore_runtime(tx):
    if tx.runtime and tx.runtime.get('phase') == 'unverified':
        raise RollbackFailedError('rollback-failed', 'runtime identity remains unverified; recovery journal retained')
    if tx.runtime and tx.runtime.get('unit_reload'):
        from .lifecycle.systemd import _systemctl
        try:
            _systemctl(tx.scope, 'daemon-reload')
        except Exception:
            raise RollbackFailedError('rollback-failed', 'restored unit reload remains unverified; recovery journal retained') from None
    if tx.runtime and tx.runtime['was_running']:
        try:
            app, backend = _runtime_backend(tx)
            if not backend.status().get('running'):
                tx.runtime['phase'] = 'starting'
                tx._persist('restored')
                observed = app.lifecycle('start', _locked=True, _transaction=tx)
            else:
                observed = app.status()
                # A live identity and owned listeners do not prove that the
                # restored credentials are accepted after an interrupted
                # recovery. Keep the restored journal until local auth gates
                # are confirmed, without stopping or replacing this process.
                _data, _checks, health = app._health_result()
                if health != 'PASS':
                    raise RollbackFailedError('rollback-failed', 'previous runtime authentication remains unverified; recovery journal retained')
        except RollbackFailedError:
            raise
        except Exception:
            raise RollbackFailedError('rollback-failed', 'previous runtime restoration failed; recovery journal retained') from None
        if not isinstance(observed, dict) or observed.get('overall') != 'PASS' \
                or observed.get('runtime', {}).get('running') is not True:
            raise RollbackFailedError('rollback-failed', 'previous runtime restoration remains unverified; recovery journal retained')


def restore_backup(scope, backup):
    raise TransactionError('historical-rollback-disabled', 'historical rollback is not supported')


def recover_transactions(scope):
    """Recover write-ahead journals under the caller's operation lock."""
    from .trust import require_private_file
    root = scope.backups_root
    if not root.exists():
        return
    require_private_dir(root)
    for directory in sorted(root.iterdir()):
        require_private_dir(directory)
        journal = directory / 'journal.json'
        if not journal.exists():
            raise TransactionError('transaction-recovery-required', 'unfinished transaction has no journal')
        require_private_file(journal)
        if journal.stat().st_size > 16 * 1024 * 1024:
            raise TransactionError('transaction-journal-invalid')
        document = json.loads(journal.read_text(encoding='utf-8'))
        if not isinstance(document, dict) or document.get('id') != directory.name:
            raise TransactionError('transaction-journal-invalid')
        state = document.get('state')
        if state is None:  # Completed journals written by the old release.
            if (set(document) != {'id','name','at','journal'} or type(document.get('at')) is not int
                    or not isinstance(document.get('journal'), list)):
                raise TransactionError('transaction-recovery-required', 'incomplete modern journal retained for inspection')
            shutil.rmtree(directory)
            continue
        if state not in ('pending', 'committed', 'restored'):
            raise TransactionError('transaction-journal-invalid')
        tx = Transaction.__new__(Transaction)
        tx.scope, tx.id, tx.name = scope, directory.name, document.get('name')
        tx.backup_root, tx.finished = directory, False
        tx.runtime = document.get('runtime')
        if tx.runtime is not None and (tx.name not in ('policy-activate', 'core-install', 'core-activate', 'port-retry','service-install','service-uninstall')
                or not isinstance(tx.runtime, dict) or type(tx.runtime.get('was_running')) is not bool
                or set(tx.runtime) - {'was_running','phase','unit_reload'}
                or 'unit_reload' in tx.runtime and (type(tx.runtime['unit_reload']) is not bool or tx.name not in ('core-install','core-activate','service-install','service-uninstall'))
                or 'phase' in tx.runtime and tx.runtime['phase'] not in ('prepared', 'stopping', 'starting', 'unverified')):
            raise TransactionError('transaction-journal-invalid')
        tx.staging = Path(document.get('staging', ''))
        if (tx.staging.parent != scope.staging_root or tx.staging.is_symlink()
                or not tx.staging.name.startswith(tx.id + '-')):
            raise TransactionError('transaction-journal-invalid')
        # Only migration has ever been authorized to edit these exact files.
        tx.allow_paths = ({Path.home() / name for name in ('.bashrc', '.zshrc', '.profile')}
                          if tx.name == 'migrate' and not scope.system else set())
        tx.journal = document.get('journal')
        if not isinstance(tx.journal, list):
            raise TransactionError('transaction-journal-invalid')
        for record in tx.journal:
            if not isinstance(record, dict) or record.get('op') not in ('publish', 'delete'):
                raise TransactionError('transaction-journal-invalid')
            path = Path(record.get('path', ''))
            tx._check_destination(path)
            saved = record.get('backup')
            if saved:
                saved = Path(saved)
                if saved.parent != directory or saved.is_symlink():
                    raise TransactionError('transaction-journal-invalid')
                if state == 'pending' and record.get('type') != 'symlink':
                    require_private_file(saved)
            for created in record.get('created_dirs', []):
                if Path(created) not in path.parents:
                    raise TransactionError('transaction-journal-invalid')
        if state == 'pending':
            # Refuse to overwrite an unrelated manual edit made after a crash.
            final = {record['path']: record for record in tx.journal}
            for filename, record in final.items():
                path = Path(filename)
                if path.is_file() and not path.is_symlink():
                    digest = hashlib.sha256(path.read_bytes()).hexdigest()
                    expected = {record.get('published_sha256')}
                    for step in tx.journal:
                        if step['path'] == filename and step.get('backup'):
                            saved = Path(step['backup'])
                            if saved.is_file():
                                expected.add(hashlib.sha256(saved.read_bytes()).hexdigest())
                    if digest not in expected:
                        raise TransactionError('transaction-current-drifted', 'manual edit preserved; recovery required')
            restore_failed_operation(tx)
        else:
            if state == 'restored':
                _restore_runtime(tx)
            tx._cleanup()
