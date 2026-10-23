"""Verified, relocatable Linux bundles with no target Python installation."""
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import MihomoctlError

MANIFEST = 'bundle-manifest.json'
MAX_BYTES = 768 * 1024 * 1024
MAX_FILES = 30000


def bundle_root():
    root = Path(__file__).resolve().parents[2]
    return root if (root / MANIFEST).is_file() else None


def is_bundle(source):
    source = Path(source)
    if source.is_dir():
        return (source / MANIFEST).is_file()
    if source.name.endswith('.tar.gz') and source.is_file():
        try:
            with tarfile.open(source, 'r:gz') as archive:
                size = 0
                for index, entry in enumerate(archive):
                    size += max(entry.size, 0)
                    if index >= MAX_FILES or size > MAX_BYTES:
                        break
                    if entry.name.rstrip('/').endswith('/' + MANIFEST):
                        return True
        except (OSError, tarfile.TarError):
            pass
    return False


@contextmanager
def source_tree(source):
    from .installation import InstallationError
    from .release_artifacts import safe_member
    source = Path(source).absolute()
    if source.is_dir():
        yield source
        return
    with tempfile.TemporaryDirectory(prefix='mihomoctl-bundle-') as temporary:
        destination = Path(temporary)
        count, size, roots, seen = 0, 0, set(), set()
        with tarfile.open(source, 'r:gz') as archive:
            for entry in archive:
                safe_member(entry.name)
                count += 1
                size += entry.size
                if (count > MAX_FILES or size > MAX_BYTES or entry.name in seen
                        or not (entry.isfile() or entry.isdir())):
                    raise InstallationError('unsafe-portable-archive')
                seen.add(entry.name)
                parts = Path(entry.name).parts
                roots.add(parts[0])
                target = destination / entry.name
                if entry.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    with archive.extractfile(entry) as stream, target.open('xb') as output:
                        shutil.copyfileobj(stream, output)
                    target.chmod(0o700 if entry.mode & 0o111 else 0o600)
        if len(roots) != 1:
            raise InstallationError('invalid-portable-root')
        yield destination / roots.pop()


def verify_bundle(root, *, check_platform=True):
    from .installation import InstallationError, digest_file
    from .release_artifacts import safe_member, unique_object
    from .trust import require_trusted_dir, require_trusted_code_file, _check_ancestors
    root = Path(root).absolute()
    _check_ancestors(root, 'runtime-untrusted', owners={0, os.geteuid()})
    require_trusted_dir(root)
    manifest = root / MANIFEST
    require_trusted_code_file(manifest)
    if manifest.stat().st_size > 8 * 1024 * 1024:
        raise InstallationError('portable-manifest-invalid')
    document = json.loads(manifest.read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    if (not isinstance(document, dict) or document.get('format') != 1 or document.get('kind') != 'portable'
            or not re.fullmatch(r'\d+\.\d+\.\d+', document.get('version', ''))
            or document.get('target') != 'linux-x86_64'
            or not isinstance(document.get('files'), dict) or not document['files']):
        raise InstallationError('portable-manifest-invalid')
    if check_platform and (platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64')):
        raise InstallationError('portable-platform-unsupported', 'Linux x86_64 required')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise InstallationError('portable-symlink-refused')
        if path.is_file() and path != root / 'record.json':
            name = path.relative_to(root).as_posix()
            require_trusted_code_file(path)
            if name != MANIFEST:
                actual.add(name)
    if actual != set(document['files']):
        raise InstallationError('portable-inventory-mismatch')
    for name, record in document['files'].items():
        safe_member(name)
        if (not isinstance(record, dict) or record.get('mode') not in (0o644, 0o755)
                or digest_file(root / name) != record.get('sha256')
                or bool((root / name).stat().st_mode & 0o111) != (record['mode'] == 0o755)):
            raise InstallationError('portable-digest-mismatch', name)
    for name in ('runtime/bin/python3', 'bin/mihomoctl', 'mihomoctl', 'install.sh',
                 'lib/mihomoctl/cli.py', 'core/mihomo.gz', 'core/pin.json'):
        if name not in actual:
            raise InstallationError('portable-component-missing', name)
    return document


def _smoke(root):
    from .installation import InstallationError
    code = ('import sys; sys.path.insert(0, sys.argv[1]); '
            'import yaml, textual; from mihomoctl import __version__; '
            'assert __version__ == sys.argv[2]')
    version = json.loads((root / MANIFEST).read_text())['version']
    try:
        subprocess.run([str(root / 'runtime/bin/python3'), '-I', '-B', '-c', code,
                        str(root / 'lib'), version], check=True, timeout=60,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise InstallationError('portable-runtime-unavailable',
                                'bundled runtime failed verification on this system') from exc


def install_bundle(scope, source, *, dry_run=False, allow_same_version=False, allow_downgrade=False):
    from . import installation as engine
    from .locks import operation_lock, idle_generations
    from .trust import require_private_dir
    scope.require_mutation()
    if scope.system:
        raise engine.InstallationError('portable-user-scope-required')
    with source_tree(source) as root:
        manifest = verify_bundle(root)
        _smoke(root)
        paths = engine.InstallPaths(scope)
        with operation_lock(scope), idle_generations(scope):
            previous = engine.current_target(paths)
            previous_record = engine.verify_installed(scope) if previous else None
            conflict = engine._old_installation_conflict(scope, paths)
            if conflict:
                raise engine.InstallationError('legacy-installation-present', conflict[0], conflict[1])
            if previous_record:
                old, new = engine.parse_version(previous_record['version']), engine.parse_version(manifest['version'])
                if old == new and not allow_same_version:
                    raise engine.InstallationError('same-version-already-installed', manifest['version'])
                if old > new and not allow_downgrade:
                    raise engine.InstallationError('downgrade-refused')
            expected = str(paths.install_root / 'current/bin/mihomoctl')
            if ((paths.bin_link.exists() and not paths.bin_link.is_symlink())
                    or (paths.bin_link.is_symlink() and os.readlink(paths.bin_link) != expected)):
                raise engine.InstallationError('launcher-path-occupied')
            result = {'version': manifest['version'], 'source_kind': 'portable-bundle',
                      'install_root': str(paths.install_root), 'bin_link': str(paths.bin_link),
                      'extras': ['tui'], 'historical_rollback': False}
            if dry_run:
                return dict(result, dry_run=True)
            for directory in (paths.install_root, paths.generations):
                require_private_dir(directory, create=True)
            generation = paths.generations / uuid.uuid4().hex
            recovery = engine._backup_dir(paths, 'install')
            transaction = {'kind': 'install', 'scope': scope.name,
                           'install_root': str(paths.install_root), 'bin_link': str(paths.bin_link),
                           'generation': generation.name, 'previous': previous,
                           'previous_bin': os.readlink(paths.bin_link) if paths.bin_link.is_symlink() else None}
            engine._write_private_json(recovery / 'transaction.json', transaction)
            engine._write_private_json(paths.pending, {'kind': 'install', 'backup': str(recovery)})
            committed = False
            try:
                shutil.copytree(root, generation)
                generation.chmod(0o700)
                # Never inherit an install record from an input bundle.
                (generation / 'record.json').unlink(missing_ok=True)
                verify_bundle(generation)
                python = generation / 'runtime/bin/python3'
                record = {'schema': 1, 'protocol': engine.PROTOCOL, 'version': manifest['version'],
                          'generation': generation.name, 'scope': scope.name,
                          'install_root': str(paths.install_root), 'bin_link': str(paths.bin_link),
                          'python': str(python), 'entry_point': engine.ENTRY_POINT,
                          'source_kind': 'portable-bundle', 'extras': ['tui'],
                          'file_digests': {p.relative_to(generation).as_posix(): engine.digest_file(p)
                                           for p in engine._walk_generation(generation) if p.is_file()}}
                engine._write_private_json(generation / 'record.json', record)
                engine._enforce_generation_ownership(generation, scope)
                _smoke(generation)
                engine._make_readonly(generation)
                engine._switch_current(paths, 'generations/' + generation.name)
                engine._ensure_launcher(paths)
                engine.verify_installed(scope)
                engine._write_private_json(recovery / 'result.json', {'committed': True})
                committed = True
                engine.finish_committed(scope, recovery, 'install')
                return dict(result, generation=generation.name, python=str(python), replaced=previous)
            except BaseException as failure:
                if not committed:
                    engine._recover_backup(scope, recovery, lock=False)
                    if recovery.exists():
                        engine._rmtree_rw(recovery)
                else:
                    raise engine.InstallationError('installation-committed-cleanup-pending',
                        'the new version is installed; cleanup will retry on the next operation') from failure
                raise


def prepare_core(scope):
    """Install the included core locally, without fetching or activating it."""
    from . import coreinstall
    from .errors import SupplyChainError
    from .trust import require_private_dir
    from .transaction import run_transaction
    root = bundle_root()
    if root is None:
        raise SupplyChainError('bundled-core-unavailable', 'use a complete portable bundle')
    verify_bundle(root)
    pin = json.loads((root / 'core/pin.json').read_text())
    expected = coreinstall.digests.lookup(pin['version'], pin['asset'])
    data = (root / 'core/mihomo.gz').read_bytes()
    if not expected or hashlib.sha256(data).hexdigest() != expected['sha256']:
        raise SupplyChainError('digest-mismatch')
    core = coreinstall._verify_gzip(data, pin['version'])
    destination = scope.cores_root / pin['version'] / 'mihomo'
    digest = hashlib.sha256(core).hexdigest()
    present = False
    if destination.is_file() and not destination.is_symlink():
        from .trust import require_executable_file
        require_executable_file(destination)
        present = hashlib.sha256(destination.read_bytes()).hexdigest() == digest
    def publish(tx):
        require_private_dir(scope.cores_root, create=True)
        require_private_dir(destination.parent, create=True)
        if not present:
            tx.write_bytes(destination, core, mode=0o755)
        output = coreinstall._run_version(destination)
        if not coreinstall._version_matches(output, pin['version']):
            raise SupplyChainError('core-version-mismatch')
        receipt = coreinstall._read_receipt(scope)
        receipt['installs'] = [row for row in receipt['installs'] if row.get('binary') != str(destination)]
        receipt['installs'].append({'version': pin['version'], 'binary': str(destination),
                   'sha256': expected['sha256'], 'binary_sha256': digest, 'provenance': 'bundled-maintainer-pin'})
        tx.write_text(scope.cores_root / 'manifest.json', json.dumps(receipt) + '\n')
    run_transaction(scope, 'bundled-core', publish)
    from .retention import cleanup_after_commit
    from .locks import operation_lock
    with operation_lock(scope):
        cleanup_after_commit(scope, core=True)
    return destination
