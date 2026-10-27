"""systemd backend: fixed unit ``mihomoctl.service`` for user and system scope.

- User scope: unit in ``~/.config/systemd/user/mihomoctl.service``.
- System scope: unit in ``/etc/systemd/system/mihomoctl.service`` running as
  the dedicated ``mihomoctl`` service account; core-readable config is
  root-owned 0640 with the service group.
- Installing a unit only writes owned files and reloads the manager;
  never enable, start or set linger.  Start/stop/restart operate only on
  the managed unit.  Type=simple (mihomo has no sd_notify); ExecStart is
  a plain argv; no secrets in unit text; Restart=on-failure with rate
  limiting; daemon runs with -d/-f files (SIGHUP reloadable).
"""

import os
import pwd
import subprocess
import time
from pathlib import Path

from ..config import Manager
from ..errors import ConfigError, ObservedStateError, PermissionScopeError, StateError
from ..trust import require_executable_file
from . import ports, runner

UNIT_NAME = "mihomoctl.service"
SERVICE_ACCOUNT = "mihomoctl"
SERVICE_GROUP = "mihomoctl"
UNIT_MARKER = "# mihomoctl managed unit v1"
TUN_DROPIN = "50-mihomoctl-tun.conf"
NAMESPACE_DROPIN = '60-mihomoctl-namespace.conf'
LEGACY_CORE_ENVIRONMENT = 'UnsetEnvironment=CLASH_HOME_DIR CLASH_CONFIG_FILE CLASH_CONFIG_STRING CLASH_AGE_SECRET_KEY CLASH_OVERRIDE_EXTERNAL_CONTROLLER CLASH_OVERRIDE_EXTERNAL_CONTROLLER_UNIX CLASH_OVERRIDE_EXTERNAL_CONTROLLER_TLS CLASH_OVERRIDE_SECRET CLASH_POST_UP CLASH_POST_DOWN LD_PRELOAD LD_LIBRARY_PATH'
CORE_ENVIRONMENT = 'UnsetEnvironment=CLASH_HOME_DIR CLASH_CONFIG_FILE CLASH_CONFIG_STRING CLASH_AGE_SECRET_KEY CLASH_OVERRIDE_EXTERNAL_UI_DIR CLASH_OVERRIDE_EXTERNAL_CONTROLLER CLASH_OVERRIDE_EXTERNAL_CONTROLLER_UNIX CLASH_OVERRIDE_EXTERNAL_CONTROLLER_TLS CLASH_OVERRIDE_EXTERNAL_CONTROLLER_PIPE CLASH_OVERRIDE_EXTERNAL_CONTROLLER_ROUTING_MARK CLASH_OVERRIDE_SECRET CLASH_POST_UP CLASH_POST_DOWN LD_PRELOAD LD_LIBRARY_PATH http_proxy https_proxy all_proxy no_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY NO_PROXY'


def namespace_dropin_text(path):
    """Strict administrator deployment format; never installs or enters it."""
    import re
    if not isinstance(path, str) or not re.fullmatch(r'/run/netns/[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', path):
        raise ConfigError('namespace-path-invalid', 'namespace must be a named /run/netns entry')
    return UNIT_MARKER + '\n[Service]\nNetworkNamespacePath=' + path + '\n'


def _namespace_entry(path):
    import stat
    from ..trust import _check_ancestors
    namespace_dropin_text(path)
    entry = Path(path)
    _check_ancestors(entry, 'namespace-untrusted', owners={0})
    if entry.is_symlink() or not entry.is_file():
        raise StateError('namespace-untrusted', 'namespace entry must be a regular root-owned namespace handle')
    info = entry.stat()
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise StateError('namespace-untrusted', 'namespace entry is writable or not root-owned')
    return info.st_dev, info.st_ino


def _namespace_matches(path, process='self'):
    try:
        expected = _namespace_entry(path)
        actual = Path('/proc') / str(process) / 'ns/net'
        info = actual.stat()
        return expected == (info.st_dev, info.st_ino)
    except OSError:
        return False


def unit_path(scope):
    if scope.system:
        return Path("/etc/systemd/system") / UNIT_NAME
    base = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    return base / "systemd/user" / UNIT_NAME


def dropin_dir(scope):
    return unit_path(scope).parent / (UNIT_NAME + ".d")


def _systemctl(scope, *args, timeout=30, check=True):
    command = ["systemctl"]
    if not scope.system:
        command.append("--user")
    command.extend(args)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise StateError("systemd-unavailable", "systemctl timed out") from None
    except OSError as exc:
        raise StateError("systemd-unavailable", str(exc.strerror or exc)) from None
    if check and result.returncode != 0:
        raise ObservedStateError("systemd-operation-failed",
                         "systemctl %s: exit %d" % (" ".join(args[:2]), result.returncode))
    return result


def systemd_available(scope):
    if scope.system:
        return Path("/run/systemd/system").is_dir()
    if not os.environ.get("XDG_RUNTIME_DIR"):
        return False
    return _user_manager_running(scope)


def _user_manager_running(scope):
    result = _systemctl(scope, "show-environment", check=False, timeout=10)
    return result.returncode == 0


def service_account_uid():
    try:
        entry = pwd.getpwnam(SERVICE_ACCOUNT)
    except KeyError:
        return None
    return entry.pw_uid


def ensure_service_account(create=True):
    """Return the dedicated account entry, creating a system account when
    missing (system scope only; caller must be root)."""
    try:
        return pwd.getpwnam(SERVICE_ACCOUNT)
    except KeyError:
        pass
    if not create:
        raise ConfigError("service-account-missing",
                          "dedicated account %r is required" % SERVICE_ACCOUNT)
    if os.geteuid() != 0:
        raise PermissionScopeError("service-account-missing",
                                   "creating %r requires root --system" % SERVICE_ACCOUNT)
    result = subprocess.run(["useradd", "--system", "--user-group",
                             "--home-dir", "/var/lib/mihomoctl/core-home",
                             "--shell", "/usr/sbin/nologin", SERVICE_ACCOUNT],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise StateError("service-account-create-failed", "useradd exit %d" % result.returncode)
    return pwd.getpwnam(SERVICE_ACCOUNT)


def unit_text(manager: Manager, scope):
    binary = manager.core.binary
    config = manager.core.config
    home = str(scope.core_home)
    lines = [
        UNIT_MARKER,
        "[Unit]",
        "Description=Managed Mihomo runtime (mihomoctl)",
        "After=network-online.target",
        "Wants=network-online.target",
        "StartLimitIntervalSec=60",
        "StartLimitBurst=5",
        "",
        "[Service]",
        "Type=simple",
        "ExecStart=%s -d %s -f %s" % (_quote(binary), _quote(home), _quote(config)),
        "ExecReload=/bin/kill -HUP $MAINPID",
        "Restart=on-failure",
        "RestartSec=3",
        "UMask=0077",
        # Complete CLASH flag vocabulary in the pinned v1.19.32 main.go.
        # systemd does not support prefix wildcards in UnsetEnvironment.
        CORE_ENVIRONMENT,
    ]
    if scope.system:
        account = ensure_service_account(create=True)
        lines.append("User=%s" % SERVICE_ACCOUNT)
        lines.append("Group=%s" % SERVICE_GROUP)
        lines.append("CapabilityBoundingSet=")
        lines.append("AmbientCapabilities=")
        lines.append("NoNewPrivileges=yes")
        lines.append("ProtectSystem=strict")
        lines.append("ProtectHome=yes")
        lines.append("ReadWritePaths=%s" % home)
    lines.append("")
    lines.append("[Install]")
    lines.append("WantedBy=" + ("multi-user.target" if scope.system else "default.target"))
    return "\n".join(lines) + "\n"


def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _record_unit_change(tx):
    if tx.runtime is None:
        # Unit-only operations never stop/start a runtime. Recovery restores
        # cached definitions while leaving any untouched process alone.
        tx.runtime = {'was_running':False,'phase':'prepared'}
    if not tx.runtime.get('unit_reload'):
        tx.runtime['unit_reload']=True
        tx._persist()


def install_unit(manager: Manager, scope, tx=None):
    """Write the managed unit (marked) and daemon-reload.  Never enable,
    start or set linger.  Refuses to replace an unowned/drifted file."""
    if tx is None:
        scope.require_mutation()
        return unit_transaction(scope,'service-install',lambda transaction:install_unit(manager,scope,tx=transaction))
    if not systemd_available(scope):
        raise StateError("systemd-unavailable",
                         "systemd user manager is not running; no silent fallback")
    path = unit_path(scope)
    text = unit_text(manager, scope)
    if path.is_symlink():
        raise StateError('unit-not-managed', 'managed unit cannot be a symlink')
    if path.exists() or path.is_symlink():
        current = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not current.startswith(UNIT_MARKER):
            raise StateError("unit-not-managed",
                             "%s exists and is not managed by mihomoctl" % path)
        legacy = text.replace(CORE_ENVIRONMENT, LEGACY_CORE_ENVIRONMENT)
        if current != text and current != legacy:
            raise StateError('unit-drifted', 'managed unit differs from the generated definition; inspect before replacing')
        if current != text:
            _record_unit_change(tx)
            tx.write_text(path,text,mode=0o644 if scope.system else 0o600)
    else:
        _record_unit_change(tx)
        tx.write_text(path, text, mode=0o644 if scope.system else 0o600)
    _record_unit_change(tx)
    _systemctl(scope, "daemon-reload")
    if scope.system:
        _prepare_system_paths(scope, manager)
    return {"unit": str(path), "installed": True}


def _prepare_system_paths(scope, manager):
    """System-scope ownership: core home writable by the service account,
    core config root-owned 0640 readable by the service group."""
    account = pwd.getpwnam(SERVICE_ACCOUNT)
    for root in (scope.config_root, scope.data_root, Path(manager.core.config).parent):
        root.mkdir(mode=0o750, parents=True, exist_ok=True)
        os.chown(str(root), 0, account.pw_gid)
        os.chmod(str(root), 0o750)
    home = Path(scope.core_home)
    home.mkdir(mode=0o755, parents=True, exist_ok=True)
    os.chown(str(home), account.pw_uid, account.pw_gid)
    os.chmod(str(home), 0o700)
    config = Path(manager.core.config)
    if config.exists():
        os.chown(str(config), 0, account.pw_gid)
        os.chmod(str(config), 0o640)


def uninstall_unit(scope, tx=None):
    """Remove only project-marked files; caller owns transaction/reload."""
    if tx is None:
        scope.require_mutation()
        return unit_transaction(scope, 'service-uninstall', lambda transaction: uninstall_unit(scope, tx=transaction))
    path = unit_path(scope)
    removed = []
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or not path.read_text(encoding="utf-8").startswith(UNIT_MARKER):
            raise StateError("unit-not-managed", "%s is not managed by mihomoctl" % path)
        _record_unit_change(tx)
        tx.delete(path, require_managed_marker=UNIT_MARKER)
        removed.append(str(path))
    dropins = dropin_dir(scope)
    if dropins.is_symlink():
        raise StateError('unit-not-managed', 'unit drop-in directory is a symlink')
    if dropins.is_dir():
        for item in sorted(dropins.iterdir()):
            if item.is_symlink():
                raise StateError('unit-not-managed', 'unit drop-in contains a symlink')
            if item.is_file() and item.read_text(encoding='utf-8').startswith(UNIT_MARKER):
                _record_unit_change(tx)
                tx.delete(item, require_managed_marker=UNIT_MARKER)
                removed.append(str(item))
    _record_unit_change(tx)
    _systemctl(scope, "daemon-reload")
    return {'unit': str(path), 'removed': removed}


def unit_transaction(scope, name, action):
    """Rollback files and refresh cached definitions under the same lock."""
    from ..transaction import Transaction, restore_failed_operation
    from ..locks import operation_lock
    with operation_lock(scope):
        tx = Transaction(scope, name)
        try:
            result = action(tx)
            tx.commit()
            return result
        except BaseException as original:
            if not tx.finished:
                restore_failed_operation(tx)
            raise original


def dropin_dir_owned(dropins):
    for item in dropins.iterdir():
        try:
            text = item.read_text(encoding="utf-8")
        except OSError:
            return False
        if not text.startswith(UNIT_MARKER):
            return False
    return True


class SystemdBackend:
    name = "systemd"

    def __init__(self, scope, manager: Manager, endpoints, controller):
        self.scope = scope
        self.manager = manager
        self.endpoints = endpoints
        self.controller = controller

    def _main_pid(self):
        result = _systemctl(self.scope, "show", UNIT_NAME,
                            "--property=ActiveState,MainPID,ControlGroup,FragmentPath,DropInPaths,NetworkNamespacePath,NeedDaemonReload", check=False)
        if result.returncode != 0:
            raise StateError("systemd-unavailable", "cannot query %s" % UNIT_NAME)
        props = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        return props

    def _require_owned_unit(self):
        from ..trust import _check_ancestors
        path = unit_path(self.scope)
        _check_ancestors(path, 'unit-not-managed', owners={0, os.geteuid()})
        if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o022 \
                or path.stat().st_uid not in {0, os.geteuid()}:
            raise StateError('unit-not-managed', 'managed unit is missing or unsafe')
        if path.read_text(encoding='utf-8') != unit_text(self.manager, self.scope):
            raise StateError('unit-not-managed', 'unit definition differs from the managed generated unit')
        props = self._main_pid()
        if props.get('NeedDaemonReload') != 'no':
            raise StateError('unit-definition-unverified', 'systemd has stale or unverifiable cached unit definitions',
                             remediation='inspect the managed unit and explicitly run systemctl daemon-reload in the selected scope')
        if props.get('FragmentPath') != str(path):
            raise StateError('unit-definition-unverified', 'systemd loaded a different unit fragment')
        import shlex
        namespace = None
        for filename in shlex.split(props.get('DropInPaths', '')):
            item = Path(filename)
            if item not in (dropin_dir(self.scope) / TUN_DROPIN, dropin_dir(self.scope) / NAMESPACE_DROPIN) or not self.scope.system:
                raise StateError('unit-definition-unverified', 'systemd loaded an unknown override')
            _check_ancestors(item, 'unit-definition-unverified', owners={0})
            if item.is_symlink() or not item.is_file() or item.stat().st_uid != 0 \
                    or item.stat().st_mode & 0o022:
                raise StateError('unit-definition-unverified', 'managed override is unsafe')
            text = item.read_text(encoding='utf-8')
            if item.name == TUN_DROPIN:
                from .tun import CAP_DROPIN_CONTENT
                if not self.manager.tun.enabled or text != CAP_DROPIN_CONTENT:
                    raise StateError('unit-definition-unverified', 'TUN capability override changed or lacks authorization')
            else:
                prefix = UNIT_MARKER + '\n[Service]\nNetworkNamespacePath='
                candidate = text[len(prefix):-1] if text.startswith(prefix) and text.endswith('\n') else ''
                if text != namespace_dropin_text(candidate):
                    raise StateError('unit-definition-unverified', 'namespace override differs from the strict managed format')
                _namespace_entry(candidate)
                if not _namespace_matches(candidate):
                    raise StateError('namespace-mismatch', 'run management commands inside the configured namespace')
                namespace = candidate
        if (props.get('NetworkNamespacePath') or None) != namespace:
            raise StateError('unit-definition-unverified', 'loaded namespace property differs from the trusted override')
        return props

    def running(self):
        props = self._main_pid()
        return props.get("ActiveState") == "active", props

    def start(self, health_check=None, runtime_transition=None):
        if not unit_path(self.scope).exists():
            raise StateError("unit-not-installed",
                             "run: mihomoctl service install",
                             )
        props = self._require_owned_unit()
        if props.get('ActiveState') not in ('inactive', 'failed') and self.running_identity() is None:
            raise ObservedStateError('service-identity-unverified', 'refusing to start a unit whose active core identity differs')
        require_executable_file(self.manager.core.binary, as_root=self.scope.system)
        surfaces = __import__('mihomoctl.endpoints', fromlist=['listening_surfaces']).listening_surfaces(self.endpoints, self.controller)
        if not self.running()[0]:
            ports.check_ports_free(surfaces)
        from . import runner
        candidate = Path(self.manager.core.config).read_text(encoding='utf-8')
        proof = runner.validate_config(self.manager.core.binary, candidate,
                               self.scope.core_home, as_uid=service_account_uid() if self.scope.system else None)
        if Path(self.manager.core.config).read_text(encoding='utf-8') != candidate:
            raise StateError('config-changed-after-validation', 'configuration changed before service start')
        proof.ensure_current()
        if runtime_transition:
            runtime_transition('unverified')
        try:
            _systemctl(self.scope, "start", UNIT_NAME, timeout=60)
        except BaseException:
            if runtime_transition and self._main_pid().get('ActiveState') in ('inactive', 'failed'):
                runtime_transition('starting')
            raise
        uid = service_account_uid() if self.scope.system else os.geteuid()
        expect_pid = None
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            expect_pid = self.running_identity()
            if expect_pid is not None or self._main_pid().get('ActiveState') in ('inactive', 'failed'):
                break
            time.sleep(.05)
        try:
            if expect_pid is None:
                raise ObservedStateError('service-identity-unverified', 'started unit has no matching managed core identity')
            ports.wait_listening(surfaces, uid, 30, expect_pid=expect_pid)
            if health_check is not None:
                ok, detail = health_check()
                if not ok:
                    raise ObservedStateError("start-not-verified", "post-start health gate failed: %s" % detail)
            if self.manager.tun.enabled:
                from .tun import synchronize_receipt
                synchronize_receipt(self.scope, self.manager)
            if runtime_transition:
                runtime_transition('starting')
        except BaseException as original:
            if self.running_identity() is not None:
                self.stop()
            elif self._main_pid().get('ActiveState') not in ('inactive', 'failed'):
                raise ObservedStateError('service-cleanup-unverified', 'started unit identity differs; refusing to stop an unknown service') from original
            if runtime_transition:
                runtime_transition('starting')
            raise
        return expect_pid

    def stop(self):
        props = self._require_owned_unit()
        if props.get('ActiveState') not in ('inactive', 'failed') and self.running_identity() is None:
            raise ObservedStateError('service-identity-unverified', 'refusing to stop a unit whose core identity differs')
        _systemctl(self.scope, "stop", UNIT_NAME, timeout=90)
        from ..endpoints import listening_surfaces
        leftover = [e for e in listening_surfaces(self.endpoints, self.controller) if ports.port_occupied(e.address, e.port)]
        if leftover:
            raise ObservedStateError("stop-port-still-occupied",
                             "unit stopped but ports remain occupied: %s"
                             % [(e.address, e.port) for e in leftover],
                             remediation="another process owns the port; no process was killed")
        return True

    @runner.validation_operation
    def restart(self, health_check=None, runtime_transition=None):
        props = self._require_owned_unit()
        if props.get("ActiveState") not in ("inactive", "failed") and self.running_identity() is None:
            raise ObservedStateError("service-identity-unverified", "refusing to restart a unit whose core identity differs")
        from . import runner
        candidate = Path(self.manager.core.config).read_text(encoding='utf-8')
        proof = runner.validate_config(self.manager.core.binary,
                               candidate,
                               self.scope.core_home,
                               as_uid=service_account_uid() if self.scope.system else None)
        if Path(self.manager.core.config).read_text(encoding='utf-8') != candidate:
            raise StateError('config-changed-after-validation', 'configuration changed before stopping the old core')
        proof.ensure_current()
        if runtime_transition:
            runtime_transition('stopping')
        self.stop()
        return self.start(health_check=health_check, **({'runtime_transition': runtime_transition} if runtime_transition else {}))

    def running_identity(self):
        from ..identity import read_identity
        try:
            props = self._require_owned_unit()
            if props.get('ActiveState') != 'active':
                return None
            identity = read_identity(int(props.get('MainPID') or 0), exe=str(Path(self.manager.core.binary).resolve()))
            expected_uid = service_account_uid() if self.scope.system else os.geteuid()
            if identity.uid != expected_uid or identity.config != self.manager.core.config:
                return None
            namespace = props.get('NetworkNamespacePath')
            if namespace and not _namespace_matches(namespace, process=identity.pid):
                return None
            from ..identity import alive
            if not alive(identity):
                return None
            if namespace and not _namespace_matches(namespace, process=identity.pid):
                return None
            return identity
        except (StateError, ValueError):
            return None

    def status(self):
        props = self._main_pid()
        active = props.get("ActiveState") == "active" and self.running_identity() is not None
        pid = int(props.get("MainPID") or 0)
        row = {"backend": "systemd", "running": active,
               "unit": UNIT_NAME, "state": props.get("ActiveState")}
        if active and pid > 0:
            row["pid"] = pid
            from ..identity import owns_listener
            from ..endpoints import listening_surfaces
            identity = self.running_identity()
            row['listening'] = identity is not None and all(owns_listener(identity, e.address, e.port) for e in listening_surfaces(self.endpoints, self.controller))
        return row
