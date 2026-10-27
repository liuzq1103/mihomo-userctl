"""User-level controller component; no global proxy or daemon."""
import os
import hashlib
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
from contextvars import ContextVar

runtime_application = ContextVar('mihomoctl_runtime_application', default=None)
from mihomoctl.lifecycle.runner import validation_operation
try:
    from . import probes as acceptance, files
except ImportError:
    import probes as acceptance
    import files
try:
    from .controller_types import ControlError
    from .controller_config import private
except ImportError:
    from controller_types import ControlError
    from controller_config import private

def find_core():
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if core:
        return core
    local = Path.home() / ".local/bin/mihomo"
    if local.is_file() and os.access(local, os.X_OK) and local.stat().st_uid == os.getuid():
        return str(local)
    raise ControlError("mihomo-executable-missing")


def validate_candidate(config, home_dir, updated):
    app = runtime_application.get()
    if app is not None:
        from mihomoctl.lifecycle.runner import validate_config
        from mihomoctl.lifecycle.systemd import service_account_uid
        from mihomoctl.trust import require_executable_file
        from mihomoctl.endpoints import parse_endpoints
        from mihomoctl.yamlutil import strict_load
        manager = app.load_manager()
        require_executable_file(manager.core.binary, as_root=app.system)
        parse_endpoints(strict_load(updated), system_scope=app.system, allowed_addresses=manager.allow_non_loopback)
        return validate_config(manager.core.binary, updated, app.scope.core_home,
                               as_uid=service_account_uid() if app.system else None)
    home = Path(home_dir or str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo"))
    core = find_core()
    private(home, True)
    from mihomoctl.lifecycle.runner import validate_config
    from mihomoctl.errors import MihomoctlError
    try:
        return validate_config(core, updated, home)
    except MihomoctlError as error:
        failure = ControlError('mihomo-config-validation-failed' if error.code == 'core-config-invalid' else error.code, error.exit_code)
        failure.safe_detail = getattr(error, 'safe_detail', '')
        raise failure from None


def ensure_candidate_current(proof):
    from mihomoctl.errors import MihomoctlError
    try:
        proof.ensure_current()
    except MihomoctlError as error:
        failure=ControlError(error.code,error.exit_code)
        failure.safe_detail=getattr(error,'safe_detail','')
        raise failure from None


@validation_operation
def apply_policy(config, original, updated, home_dir=None, after_write=None, activate=False):
    if original == updated and after_write is None and not activate:
        return {"state": "unchanged", "service": "unchanged"}
    app = runtime_application.get()
    if activate and app is None:
        raise ControlError('runtime-application-unavailable', detail='save and activation require a managed runtime')
    if app is not None:
        from mihomoctl.endpoints import assert_security_envelope
        from mihomoctl.transaction import run_transaction
        from mihomoctl.yamlutil import strict_load
        app.scope.require_mutation()
        assert_security_envelope(strict_load(original), strict_load(updated))
        phase = {'value': 'validate'}
        active_tx = []
        activation_verified = [False]
        def action(tx):
            active_tx.append(tx)
            proof=validate_candidate(config, home_dir, updated)
            private(config)
            if config.read_text(encoding='utf-8') != original:
                raise ControlError('config-changed-during-policy-edit')
            if activate:
                manager, endpoints, controller, _profile, _cfg = app.resolve()
                tx.runtime = {'was_running': bool(app._backend(manager, endpoints, controller).status().get('running')), 'phase': 'prepared'}
                tx._persist()
            ensure_candidate_current(proof)
            phase['value'] = 'save'
            tx.write_text(config, updated, mode=0o640 if app.system else 0o600)
            if after_write is not None:
                after_write(tx)
            receipt = {'state': 'restart-required', 'service': 'unchanged',
                       'sha256': hashlib.sha256(updated.encode()).hexdigest()}
            import json
            tx.write_text(config.with_name(config.name + '.userctl-state.json'), json.dumps(receipt))
            if activate:
                phase['value'] = 'activate'
                ensure_candidate_current(proof)
                action = 'restart' if tx.runtime['was_running'] else 'start'
                observed = app.lifecycle(action, _locked=True, _transaction=tx)
                if not isinstance(observed, dict) or observed.get('overall') != 'PASS' \
                        or observed.get('runtime', {}).get('running') is not True:
                    from mihomoctl.errors import ObservedStateError
                    raise ObservedStateError('activation-not-verified', 'post-activation runtime was not confirmed')
                activation_verified[0] = True
                tx.delete(config.with_name(config.name + '.userctl-state.json'))
                receipt.update(state='ready', action=action, overall='PASS', config_state='committed',
                               activation_state='verified', runtime_state='running',
                               applied_sha256=hashlib.sha256(config.read_bytes()).hexdigest())
            phase['value'] = 'commit'
            return receipt
        try:
            return run_transaction(app.scope, 'policy-activate' if activate else 'policy-apply', action)
        except BaseException as error:
            state = {'phase': phase['value'],
                     'config': 'unverified', 'runtime': 'unverified', 'activation': 'failed'}
            try:
                current=config.read_bytes()
                if current == original.encode():
                    state['config'] = 'restored'
                elif active_tx and active_tx[0].finished and phase['value'] == 'commit':
                    state['config'] = 'committed'
                else:
                    state['config'] = 'changed'
                manager, endpoints, controller, _profile, _cfg = app.resolve()
                status = app._backend(manager, endpoints, controller).status()
                if status.get('running') is True:
                    observed=app.status()
                    state['runtime']='running' if (isinstance(observed,dict) and observed.get('overall')=='PASS'
                        and observed.get('runtime',{}).get('running') is True) else 'unverified'
                elif status.get('running') is False:
                    uncertain=status.get('detail')=='stale-state' or status.get('state') not in (None,'inactive','failed')
                    state['runtime']='unverified' if uncertain else 'stopped'
                if active_tx and active_tx[0].runtime and active_tx[0].runtime.get('phase')=='unverified':
                    state['runtime']='unverified'
                    state['activation']='unverified'
                if state['config']=='committed' and activation_verified[0]:
                    state['activation']='verified' if state['runtime']=='running' else 'unverified'
            except Exception:
                pass
            error.operation_state = state
            error.safe_detail = (getattr(error, 'safe_detail', '') + '; ' if getattr(error, 'safe_detail', '') else '') + \
                'phase={phase}; config={config}; runtime={runtime}; activation={activation}'.format(**state)
            raise
    proof=validate_candidate(config, home_dir, updated)
    private(config)
    if config.read_bytes().decode("utf-8") != original:
        raise ControlError("config-changed-during-policy-edit")
    ensure_candidate_current(proof)
    try:
        files.atomic_bytes(config, updated.encode())
    except OSError:
        try:
            active = config.read_bytes()
            if active == updated.encode():
                files.atomic_bytes(config, original.encode())
            elif active != original.encode():
                raise ControlError("config-write-failed-concurrent-edit-preserved")
        except OSError:
            raise ControlError("config-write-failed-rollback-incomplete-use-private-backup") from None
        raise ControlError("config-write-failed-original-restored") from None
    result = {"state": "restart-required", "service": "unchanged"}
    # A receipt survives closing the TUI before restarting. It contains no credentials.
    receipt = dict(result, sha256=hashlib.sha256(updated.encode()).hexdigest())
    try:
        files.write_json(config.with_name(config.name + ".userctl-state.json"), receipt)
    except OSError:
        result["warning"] = "restart-receipt-unavailable"
    return result


def pending_state(config):
    path = config.with_name(config.name + ".userctl-state.json")
    if not path.exists():
        return {}
    import json
    private(path)
    if path.stat().st_size > 4096:
        raise ControlError("configuration-receipt-invalid")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError("configuration-receipt-invalid")
    private(config)
    if hashlib.sha256(config.read_bytes()).hexdigest() != value.get("sha256"):
        return {}
    return {key: item for key, item in value.items() if key not in ('backup', 'backup_sha256')}
