"""Explicit system-scope TUN transactions; never adopt or delete foreign devices."""
import json
import os
import socket
import subprocess
import time
from pathlib import Path

from ..config import load_manager, render_manager
from ..errors import ObservedStateError, PermissionScopeError, RollbackFailedError, StateError
from ..trust import require_private_file, require_readable_core_config
from ..yamlutil import strict_load
from . import runner, systemd

CAP_DROPIN_CONTENT = systemd.UNIT_MARKER + '\n[Service]\nCapabilityBoundingSet=CAP_NET_ADMIN\nAmbientCapabilities=CAP_NET_ADMIN\n'


def _require_system(scope):
    if not scope.system:
        raise PermissionScopeError('tun-requires-system', 'TUN requires an explicit administrator --system operation')
    scope.require_mutation()


def _device(device):
    result = subprocess.run(['ip', '-j', '-d', 'link', 'show', 'dev', device], capture_output=True, text=True, timeout=10)
    if result.returncode:
        return None
    try:
        rows = json.loads(result.stdout)
        return rows[0] if len(rows) == 1 else None
    except (ValueError, IndexError):
        raise StateError('tun-device-unverified', 'cannot inspect network device') from None


def _device_exists(device):
    return _device(device) is not None


def _device_route_present(device):
    for family in ('-4', '-6'):
        result = subprocess.run(['ip', '-j', family, 'route', 'show', 'table', 'all'], capture_output=True, text=True, timeout=10)
        if result.returncode:
            raise StateError('tun-route-unverified', 'cannot inspect routing tables')
        try:
            if any(row.get('dev') == device for row in json.loads(result.stdout)):
                return True
        except ValueError:
            raise StateError('tun-route-unverified', 'cannot decode routing tables') from None
    return False


def _receipt(scope):
    require_private_file(scope.tun_receipt, code='tun-authorization-invalid')
    try:
        data = json.loads(scope.tun_receipt.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        raise StateError('tun-authorization-invalid', 'cannot read TUN authorization') from None
    if not isinstance(data, dict):
        raise StateError('tun-authorization-invalid', 'TUN authorization must be an object')
    return data


def _owns_tun_fd(identity, device, proc=Path('/proc')):
    """Kernel iff evidence belongs to the exact, twice-verified core PID."""
    from ..identity import alive
    if not alive(identity):
        return False
    try:
        entries = list((proc / str(identity.pid) / 'fdinfo').iterdir())
        if len(entries) > 65536:
            return False
        for entry in entries:
            if not entry.name.isdecimal():
                continue
            try:
                if os.readlink(str(proc / str(identity.pid) / 'fd' / entry.name)) != '/dev/net/tun':
                    continue
                with entry.open(encoding='utf-8') as stream:
                    contents = stream.read(4097)
                if len(contents) > 4096:
                    continue
                if any(line.partition(':')[0] == 'iff' and line.partition(':')[2].strip() == device
                       for line in contents.splitlines()):
                    return alive(identity)
            except OSError:
                continue
    except OSError:
        pass
    return False


def _kernel_device_owner(scope, manager, observed):
    from ..endpoints import parse_endpoints
    cfg = _read_config(scope, manager.core.config)
    endpoints, controller = parse_endpoints(cfg, system_scope=scope.system, allowed_addresses=manager.allow_non_loopback)
    backend = systemd.SystemdBackend(scope, manager, endpoints, controller)
    backend._require_owned_unit()
    identity = backend.running_identity()
    same_namespace = False
    if identity is not None:
        try:
            ours, theirs = Path('/proc/self/ns/net').stat(), (Path('/proc') / str(identity.pid) / 'ns/net').stat()
            same_namespace = (ours.st_dev, ours.st_ino) == (theirs.st_dev, theirs.st_ino)
        except OSError:
            pass
    if identity is None or not same_namespace or observed.get('linkinfo', {}).get('info_data', {}).get('persist') is not False \
            or not _owns_tun_fd(identity, manager.tun.device):
        raise ObservedStateError('tun-ownership-unverified', 'exact managed core identity and nonpersistent TUN file-descriptor evidence are required')
    return identity


def _verify_owned(scope, manager, routes=True):
    receipt = _receipt(scope)
    observed = _device(manager.tun.device)
    dropin = systemd.dropin_dir(scope) / systemd.TUN_DROPIN
    if not receipt.get('enabled') or receipt.get('device') != manager.tun.device or not observed \
            or observed.get('linkinfo', {}).get('info_kind') != 'tun':
        raise ObservedStateError('tun-ownership-unverified', 'device identity differs from the managed authorization')
    from ..trust import _check_ancestors
    _check_ancestors(dropin, 'tun-authorization-invalid', owners={0})
    if dropin.is_symlink() or not dropin.is_file() or dropin.stat().st_uid != 0 \
            or dropin.stat().st_mode & 0o022 or dropin.read_text(encoding='utf-8') != CAP_DROPIN_CONTENT:
        raise ObservedStateError('tun-capability-drifted', 'managed capability definition changed or is missing')
    if routes and not _device_route_present(manager.tun.device):
        raise ObservedStateError('tun-route-unverified', 'managed transparent routes are absent')
    identity = _kernel_device_owner(scope, manager, observed)
    return receipt, observed, identity


def synchronize_receipt(scope, manager, tx=None):
    """Call only under the operation lock after an explicit managed action."""
    receipt, observed, identity = _verify_owned(scope, manager)
    current = receipt.get('ifindex') == observed['ifindex'] and receipt.get('runtime_identity') == identity.to_json()
    if not current:
        receipt.update(ifindex=observed['ifindex'], runtime_identity=identity.to_json(), at=time.time())
        text = json.dumps(receipt, sort_keys=True) + '\n'
        if tx is not None:
            tx.write_text(scope.tun_receipt, text)
        else:
            from ..credentials import write_atomic
            write_atomic(scope.tun_receipt, text)
    return not current


def _read_config(scope, path):
    require_readable_core_config(path, system_scope=scope.system)
    return strict_load(Path(path).read_text(encoding='utf-8'))


def _with_tun(cfg, device):
    import copy
    updated = copy.deepcopy(cfg)
    updated['tun'] = {'enable': True, 'device': device, 'stack': 'system',
                      'auto-route': True, 'auto-redirect': False, 'auto-detect-interface': True}
    return updated


def _without_tun(cfg):
    import copy
    updated = copy.deepcopy(cfg)
    updated.pop('tun', None)
    return updated


def _render_yaml(cfg):
    import yaml
    return yaml.safe_dump(cfg, sort_keys=True, allow_unicode=False)


def status(scope):
    manager = load_manager(scope)
    authorized = False
    if scope.tun_receipt.exists():
        receipt = _receipt(scope)
        authorized = bool(receipt.get('enabled') and receipt.get('device') == manager.tun.device)
    if manager.tun.enabled:
        receipt, observed, identity = _verify_owned(scope, manager)
        return {'enabled': True, 'device': manager.tun.device, 'authorized': True, 'scope': scope.name,
                'ifindex': observed['ifindex'], 'receipt_ifindex': receipt.get('ifindex'),
                'receipt_current': receipt.get('ifindex') == observed['ifindex'] and receipt.get('runtime_identity') == identity.to_json(),
                'dropin': str(systemd.dropin_dir(scope) / systemd.TUN_DROPIN)}
    return {'enabled': manager.tun.enabled, 'device': manager.tun.device, 'authorized': authorized,
            'scope': scope.name, 'dropin': str(systemd.dropin_dir(scope) / systemd.TUN_DROPIN)}


def _change(scope, enabled):
    from ..app import Application
    from ..transaction import Transaction
    from ..locks import operation_lock
    _require_system(scope)
    if not systemd.systemd_available(scope):
        raise StateError('systemd-unavailable', 'system scope requires systemd')

    recovery_state = {}
    def action(tx):
        app = Application(system=True, config_dir=str(scope.config_root))
        manager, endpoints, controller, _, cfg = app.resolve()
        if manager.tun.enabled == enabled:
            if enabled:
                refreshed = synchronize_receipt(scope, manager, tx=tx)
                if not all(c.status in ('PASS', 'SKIPPED') for c in app.health()):
                    raise ObservedStateError('tun-health-unverified', 'managed runtime is not healthy')
            elif scope.tun_receipt.exists() or (systemd.dropin_dir(scope) / systemd.TUN_DROPIN).exists():
                raise ObservedStateError('tun-authorization-drifted', 'disabled TUN retains authorization or capabilities')
            return {'enabled': enabled, 'changed': False, 'receipt_refreshed': refreshed if enabled else False}
        backend = systemd.SystemdBackend(scope, manager, endpoints, controller)
        was_running = backend.status()['running']
        if not was_running:
            raise StateError('tun-runtime-stopped', 'start the managed service before changing TUN')
        device = manager.tun.device
        observed = _device(device)
        if enabled and observed:
            raise ObservedStateError('tun-device-exists', 'network device already exists; refusing to adopt it')
        if not enabled:
            _verify_owned(scope, manager)
        import copy
        recovery_state.update(manager=copy.deepcopy(manager), endpoints=endpoints, controller=controller,
                              receipt=_receipt(scope) if manager.tun.enabled else None)
        candidate = _with_tun(cfg, device) if enabled else _without_tun(cfg)
        account = systemd.ensure_service_account(create=False)
        candidate_text = _render_yaml(candidate)
        runner.validate_config(manager.core.binary, candidate_text, scope.core_home, as_uid=account.pw_uid)
        dropin = systemd.dropin_dir(scope) / systemd.TUN_DROPIN
        if enabled and dropin.exists():
            raise ObservedStateError('tun-dropin-exists', 'capability file already exists without managed authorization')
        tx.write_text(Path(manager.core.config), candidate_text, mode=0o640)
        manager.tun.enabled = enabled
        tx.write_text(scope.manager_path, render_manager(manager))
        if enabled:
            tx.write_text(dropin, CAP_DROPIN_CONTENT, mode=0o644)
            tx.write_text(scope.tun_receipt, json.dumps({'enabled': True, 'device': device, 'authorized_by_uid': 0}) + '\n')
        else:
            tx.delete(dropin, require_managed_marker=systemd.UNIT_MARKER)
            tx.delete(scope.tun_receipt)
        recovery_state['activation_attempted'] = True
        systemd._systemctl(scope, 'daemon-reload')
        backend.restart(health_check=lambda: (all(c.status in ('PASS', 'SKIPPED') for c in app.health()), 'local health'))
        observed = _device(device)
        if enabled:
            if not observed or observed.get('linkinfo', {}).get('info_kind') != 'tun' or not _device_route_present(device):
                raise ObservedStateError('tun-activation-unverified', 'TUN device and transparent routes must both be observed')
            receipt = _receipt(scope)
            receipt.update(enabled=True, device=device, ifindex=observed['ifindex'], authorized_by_uid=0, at=time.time())
            tx.write_text(scope.tun_receipt, json.dumps(receipt, sort_keys=True) + '\n')
        elif observed:
            raise ObservedStateError('tun-disable-unverified', 'device remains after managed service restart; no device was deleted')
        return {'enabled': enabled, 'changed': True, 'device': device, 'dropin': str(dropin)}
    # Keep file rollback, cached-definition recovery and runtime restoration
    # under one lock, including a failure during final journal publication.
    with operation_lock(scope):
        tx = Transaction(scope, 'tun-enable' if enabled else 'tun-disable')
        try:
            result = action(tx)
            tx.commit()
            return result
        except BaseException as original:
            try:
                if not tx.finished:
                    tx.rollback()
                if recovery_state.get('activation_attempted'):
                    systemd._systemctl(scope, 'daemon-reload')
                    old = recovery_state['manager']
                    systemd.SystemdBackend(scope, old, recovery_state['endpoints'], recovery_state['controller']).restart()
                    if old.tun.enabled:
                        observed = _device(old.tun.device)
                        if not observed or observed.get('linkinfo', {}).get('info_kind') != 'tun' or not _device_route_present(old.tun.device):
                            raise StateError('tun-recovery-unverified')
                        receipt = _receipt(scope)
                        receipt['ifindex'] = observed['ifindex']
                        from ..credentials import write_atomic
                        write_atomic(scope.tun_receipt, json.dumps(receipt, sort_keys=True) + '\n')
                    elif _device(old.tun.device):
                        raise StateError('tun-recovery-unverified', 'new TUN device remains after recovery')
            except BaseException as recovery:
                raise RollbackFailedError('rollback-failed', 'prior TUN configuration or service could not be restored') from recovery
            raise original


def enable(scope):
    return _change(scope, True)


def disable(scope):
    return _change(scope, False)
