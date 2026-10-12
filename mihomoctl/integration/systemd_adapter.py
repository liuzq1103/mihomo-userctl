"""Owned EnvironmentFile/drop-in transactions; consumer lifecycle stays external."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

from ..errors import StateError, RollbackFailedError
from ..trust import require_private_file
from . import MARKER

DROPIN_NAME = '90-mihomoctl-proxy.conf'


def env_file(scope, binding_name):
    return scope.integration_dir / (binding_name + '.env')


def _receipt_file(scope, binding):
    return scope.integration_dir / (binding.name + '.receipt.json')


def dropin_path(scope, target):
    base = Path('/etc/systemd/system') if scope.system else Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
    return base / (target + '.d') / DROPIN_NAME


def render_env(proxy_env):
    return MARKER + '\n' + ''.join('%s=%s\n' % (key, value) for key, value in sorted(proxy_env.variables().items()))


def render_dropin(scope, binding_name):
    path = str(env_file(scope, binding_name)).replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
    return MARKER + '\n[Service]\nEnvironmentFile="' + path + '"\n'


def _owned(scope, binding):
    paths = (env_file(scope, binding.name), dropin_path(scope, binding.target))
    receipt_path = _receipt_file(scope, binding)
    if not receipt_path.exists():
        if any(p.exists() or p.is_symlink() for p in paths):
            raise StateError('integration-file-not-managed', 'existing artifacts have no ownership receipt')
        return None
    require_private_file(receipt_path, code='integration-receipt-invalid')
    try:
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    except ValueError:
        raise StateError('integration-receipt-invalid', 'cannot decode artifact receipt') from None
    if receipt.get('target') != binding.target:
        raise StateError('integration-target-drifted', 'remove the old binding before changing its target')
    for path in paths:
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != receipt.get('artifacts', {}).get(str(path)):
            raise StateError('integration-artifact-drifted', 'owned artifact changed; inspect it before replacing or removing it')
        if path == paths[0]:
            require_private_file(path, code='integration-environment-unsafe')
    return receipt


def install(scope, binding, proxy_env, tx=None):
    scope.require_mutation()
    if tx is None:
        return _transaction(scope, 'integration-install', lambda transaction: install(scope, binding, proxy_env, tx=transaction))
    _owned(scope, binding)
    target_env, target_dropin = env_file(scope, binding.name), dropin_path(scope, binding.target)
    contents = {target_env: render_env(proxy_env), target_dropin: render_dropin(scope, binding.name)}
    hashes = {}
    for path, text in contents.items():
        tx.write_text(path, text, mode=0o644 if scope.system and path == target_dropin else 0o600)
        hashes[str(path)] = hashlib.sha256(text.encode()).hexdigest()
    tx.write_text(_receipt_file(scope, binding), json.dumps({'format': 1, 'binding': binding.name,
        'target': binding.target, 'artifacts': hashes}, sort_keys=True) + '\n')
    _daemon_reload(scope)
    return {'binding': binding.name, 'target': binding.target, 'artifacts': hashes,
            'restart_required': True, 'note': 'operator-managed restart required; no consuming unit was started'}


def remove(scope, binding):
    scope.require_mutation()
    def action(tx):
        receipt = _owned(scope, binding)
        if receipt is None:
            return {'binding': binding.name, 'removed': []}
        paths = (env_file(scope, binding.name), dropin_path(scope, binding.target), _receipt_file(scope, binding))
        for path in paths:
            tx.delete(path, require_managed_marker=MARKER if path != paths[2] else None)
        _daemon_reload(scope)
        return {'binding': binding.name, 'removed': list(map(str, paths))}
    return _transaction(scope, 'integration-remove', action)


def _transaction(scope, name, action):
    from ..transaction import Transaction
    from ..locks import operation_lock
    # Acquire before the recovery handler: lock contention must never reload
    # definitions belonging to another operation's incomplete transaction.
    with operation_lock(scope):
        tx = Transaction(scope, name)
        try:
            result = action(tx)
            tx.commit()
            return result
        except BaseException as original:
            if not tx.finished:
                tx.rollback()
            try:
                _daemon_reload(scope)
            except BaseException as recovery:
                raise RollbackFailedError('rollback-failed', 'restored integration files could not be reloaded') from recovery
            raise original


def check(scope, binding, proxy_env=None):
    expected = [(env_file(scope, binding.name), render_env(proxy_env) if proxy_env else None)]
    if binding.target:
        expected.append((dropin_path(scope, binding.target), render_dropin(scope, binding.name)))
    rows = []
    for path, text in expected:
        if path.is_symlink() or not path.is_file():
            state = 'missing' if not path.is_symlink() else 'unsafe'
            rows.append({'path': str(path), 'state': state})
            continue
        current = path.read_bytes()
        rows.append({'path': str(path), 'state': 'current' if text is not None and current == text.encode() else 'drifted',
                     'sha256': hashlib.sha256(current).hexdigest()})
    live = 'unavailable'
    if binding.target:
        command = ['systemctl'] + ([] if scope.system else ['--user']) + ['is-active', binding.target]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            live = result.stdout.strip() if result.stdout.strip() in ('active', 'inactive', 'failed', 'activating', 'deactivating') else 'unknown'
        except (OSError, subprocess.TimeoutExpired):
            pass
    return {'binding': binding.name, 'target': binding.target, 'artifacts': rows, 'target_state': live,
            'live_environment': 'UNVERIFIED', 'note': 'environment inheritance is not proof of actual proxy use'}


def _daemon_reload(scope):
    command = ['systemctl'] + ([] if scope.system else ['--user']) + ['daemon-reload']
    try:
        result = subprocess.run(command, capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        raise StateError('systemd-unavailable', 'cannot reload unit definitions') from None
    if result.returncode:
        raise StateError('daemon-reload-failed', 'systemd rejected the definition reload')
