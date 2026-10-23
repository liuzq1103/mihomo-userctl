"""Discard completed history; never follow links into unmanaged storage."""
import hashlib
import json
import re
import shutil
from pathlib import Path

from .trust import require_private_dir, require_private_file


def cleanup_after_commit(scope, core=False):
    """A committed operation is distinct from unfinished, retryable cleanup."""
    from .credentials import write_atomic
    from .errors import TransactionError, MihomoctlError
    directory = scope.state_root / 'cleanup'
    require_private_dir(directory, create=True)
    marker = directory / 'pending.json'
    write_atomic(marker, json.dumps({'format': 1, 'core': core}) + '\n')
    try:
        resume_cleanup(scope)
    except (MihomoctlError, OSError, ValueError) as error:
        raise TransactionError('operation-committed-cleanup-pending',
            'changes are committed; cleanup will retry on the next operation') from error


def resume_cleanup(scope):
    marker = scope.state_root / 'cleanup/pending.json'
    if not marker.exists() and not marker.is_symlink():
        return
    require_private_file(marker)
    if marker.stat().st_size > 1024:
        from .errors import TransactionError
        raise TransactionError('cleanup-marker-invalid')
    document = json.loads(marker.read_text(encoding='utf-8'))
    if not isinstance(document, dict) or document.get('format') != 1 or type(document.get('core')) is not bool:
        from .errors import TransactionError
        raise TransactionError('cleanup-marker-invalid')
    discard_config_history(scope)
    if document['core']:
        discard_core_history(scope)
    marker.unlink()


def discard_config_history(scope):
    if not scope.config_root.exists():
        return
    from .trust import require_trusted_dir
    require_trusted_dir(scope.config_root)
    for path in scope.config_root.rglob('*.before-*'):
        if not re.fullmatch(r'.+\.before-(policy|controller)-[a-f0-9]{16}', path.name):
            continue
        require_private_file(path)
        path.unlink()
    from .transaction import recover_transactions
    recover_transactions(scope)


def discard_core_history(scope):
    manifest = scope.cores_root / 'manifest.json'
    if not manifest.exists():
        return
    require_private_file(manifest)
    document = json.loads(manifest.read_text(encoding='utf-8'))
    rows = document.get('installs', [])
    if not rows:
        return
    active = None
    if scope.manager_path.exists():
        from .config import load_manager
        active = Path(load_manager(scope).core.binary)
    keep = active or Path(rows[-1]['binary'])
    kept = []
    # Replacement may append a second receipt for the same managed path.
    # Consider its final receipt once, rather than deleting the same file twice.
    unique = {row['binary']: row for row in rows}
    for row in unique.values():
        path = Path(row.get('binary', ''))
        if path == keep:
            kept.append(row)
            continue
        # A receipt and a matching binary digest prove that this exact file is
        # ours. Foreign/adopted binaries and modified files are never removed.
        if (path.parent.parent != scope.cores_root or path.name != 'mihomo'
                or not re.fullmatch(r'v\d+\.\d+\.\d+', path.parent.name)):
            continue
        if not path.exists() and not path.is_symlink():
            continue  # An already removed old binary needs no further cleanup.
        if scope.system:
            from .trust import require_trusted_dir, _check_ancestors
            _check_ancestors(path, 'core-storage-unsafe', owners={0})
            require_trusted_dir(path.parent)
        else:
            require_private_dir(path.parent)
        from .trust import require_executable_file
        require_executable_file(path, as_root=scope.system)
        if hashlib.sha256(path.read_bytes()).hexdigest() == row.get('binary_sha256'):
            path.unlink()
            if not any(path.parent.iterdir()):
                path.parent.rmdir()
    from .credentials import write_atomic
    write_atomic(manifest, json.dumps(dict(document, installs=kept), sort_keys=True) + '\n')
