"""Process backend: direct supervised child, no systemd.

Start is lock-protected; preflight checks all binds are free, postflight
checks socket/process ownership plus proxy and controller authentication.
State records PID, UID, start time, executable and config identity.
Stopping re-reads identity before every signal; PID reuse fails closed.
"""

import json
import os
import subprocess
import time
from pathlib import Path

from .. import identity as ident
from ..config import Manager
from ..endpoints import Endpoint
from ..endpoints import listening_surfaces
from ..errors import ObservedStateError, StateError, RollbackFailedError
from ..trust import require_executable_file, require_private_dir, require_private_file
from . import ports, runner

START_TIMEOUT = 30
STOP_TIMEOUT = 20


class ProcessBackend:
    name = "process"

    def __init__(self, scope, manager: Manager, endpoints, controller):
        self.scope = scope
        self.manager = manager
        self.endpoints = endpoints
        self.controller = controller
        self.surfaces = listening_surfaces(endpoints, controller)

    # -- state ---------------------------------------------------------
    def read_state(self):
        path = self.scope.runtime_state
        if self.scope.state_root.exists() or self.scope.state_root.is_symlink():
            require_private_dir(self.scope.state_root, code='runtime-state-untrusted')
        if not path.exists() and not path.is_symlink():
            return None
        require_private_file(path, code='runtime-state-untrusted')
        try:
            if path.stat().st_size > 65536:
                raise StateError('runtime-state-invalid', 'runtime receipt is too large')
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise StateError('runtime-state-invalid', 'runtime receipt cannot be decoded; inspect it before changing lifecycle state') from None
        if not isinstance(data, dict) or data.get('backend') != 'process' \
                or any(type(data.get(key)) is not int for key in ('pid', 'uid', 'start_time')) \
                or data['pid'] <= 1 or data['start_time'] <= 0 or data['uid'] != os.geteuid() \
                or not isinstance(data.get('exe'), str) or not Path(data['exe']).is_absolute():
            raise StateError('runtime-state-invalid', 'runtime receipt does not describe this user process backend')
        if data.get('config') != self.manager.core.config or data.get('binary') != self.manager.core.binary \
                or data['exe'] != str(Path(self.manager.core.binary).resolve()):
            raise StateError('runtime-state-mismatch', 'runtime receipt differs from the selected core or config; no process was signaled')
        return data

    def _write_state(self, identity):
        path = self.scope.runtime_state
        require_private_dir(path.parent, create=True)
        payload = {
            "backend": "process",
            "pid": identity.pid,
            "uid": identity.uid,
            "start_time": identity.start_time,
            "exe": identity.exe,
            "binary": self.manager.core.binary,
            "config": self.manager.core.config,
            "started_at": int(time.time()),
        }
        from ..credentials import write_atomic
        write_atomic(path, json.dumps(payload, sort_keys=True) + '\n')
        return payload

    def _clear_state(self):
        try:
            self.scope.runtime_state.unlink()
        except FileNotFoundError:
            pass

    def running_identity(self):
        """Return the live ProcessIdentity if the recorded process still
        matches exactly, else None.  Never guesses by name."""
        state = self.read_state()
        if not state:
            return None
        try:
            recorded = ident.ProcessIdentity(int(state["pid"]), int(state["uid"]),
                                              int(state["start_time"]), state["exe"], state.get('config'))
        except (KeyError, TypeError, ValueError):
            return None
        if not ident.alive(recorded):
            if ident.exists_any(recorded.pid) and not ident.exited(recorded.pid):
                raise ObservedStateError('pid-reuse-suspected', 'live process differs from the private receipt; refusing lifecycle mutation')
            return None
        return recorded

    # -- lifecycle -----------------------------------------------------
    def start(self, health_check=None):
        if self.running_identity() is not None:
            raise ObservedStateError("already-running", "managed process backend is active")
        binary = self.manager.core.binary
        require_executable_file(binary, as_root=False)
        ports.check_ports_free(self.surfaces)
        runner.validate_config(binary, Path(self.manager.core.config).read_text(encoding='utf-8'), self.scope.core_home)
        home = self.scope.core_home
        require_private_dir(home, create=True)
        logs = self.scope.logs_dir
        require_private_dir(logs, create=True)
        log_path = logs / "mihomo.log"
        fd = os.open(str(log_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        log = os.fdopen(fd, 'ab', 0)
        try:
            process = subprocess.Popen(
                [binary, "-d", str(home), "-f", str(self.manager.core.config)],
                stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                env=runner.child_environment(), start_new_session=True)
        except OSError as exc:
            log.close()
            raise StateError("start-failed", str(exc.strerror or exc)) from None
        log.close()
        identity = None
        try:
            identity = ident.read_identity(process.pid, exe=str(Path(binary).resolve()))
            if identity.config != self.manager.core.config:
                raise StateError('process-identity-mismatch', 'child config differs from manager')
            ports.wait_listening(self.surfaces, identity.uid,
                                 START_TIMEOUT, expect_pid=identity)
            self._write_state(identity)
            if health_check is not None:
                ok, detail = health_check()
                if not ok:
                    raise ObservedStateError('start-not-verified', 'post-start health gate failed: %s' % detail)
        except BaseException as original:
            try:
                _terminate_child(process, identity)
                self._clear_state()
            except BaseException as cleanup:
                raise RollbackFailedError('start-cleanup-failed', 'managed child or runtime receipt could not be cleaned safely',
                    remediation='inspect PID %d and the managed state directory; no unknown process was signaled' % process.pid) from cleanup
            raise original
        return identity

    def restart(self, health_check=None):
        # Reject invalid candidates before disturbing the running old instance.
        self.running_identity()
        runner.validate_config(self.manager.core.binary,
                               Path(self.manager.core.config).read_text(encoding='utf-8'),
                               self.scope.core_home)
        self.stop()
        return self.start(health_check=health_check)

    def stop(self):
        state = self.read_state()
        if not state:
            return False
        try:
            recorded = ident.ProcessIdentity(int(state["pid"]), int(state.get("uid", -1)),
                                              int(state.get("start_time", -1)),
                                              state.get("exe", ""), state.get('config'))
        except (KeyError, TypeError, ValueError):
            self._clear_state()
            return False
        if ident.exists_any(recorded.pid) and not ident.exited(recorded.pid) and not ident.alive(recorded):
            raise ObservedStateError("pid-reuse-suspected",
                             "pid %d exists but identity drifted; refusing to signal" % recorded.pid,
                             remediation="inspect the process manually; state file preserved")
        stopped = False
        if ident.alive(recorded):
            stopped = ident.stop(recorded)
        self._clear_state()
        # Never kill foreign sockets: only report leftover listeners.
        deadline = time.monotonic() + 1
        while True:
            leftover = [e for e in self.surfaces if ports.port_occupied(e.address, e.port)]
            if not leftover or time.monotonic() >= deadline:
                break
            time.sleep(.02)
        if leftover:
            raise ObservedStateError("stop-port-still-occupied",
                             "process stopped but ports remain occupied: %s"
                             % [(e.address, e.port) for e in leftover],
                             remediation="another process owns the port; no process was killed")
        return stopped

    def status(self):
        state = self.read_state()
        if not state:
            return {"backend": "process", "running": False, "detail": "no-state"}
        recorded = None
        try:
            recorded = ident.ProcessIdentity(int(state["pid"]), int(state.get("uid", -1)),
                                              int(state.get("start_time", -1)),
                                              state.get("exe", ""), state.get('config'))
        except (KeyError, TypeError, ValueError):
            pass
        if recorded is not None and ident.exited(recorded.pid):
            return {"backend": "process", "running": False, "detail": "crashed",
                    "last_identity": {k: state.get(k) for k in ("pid", "start_time")}}
        if recorded is None or not ident.alive(recorded):
            return {"backend": "process", "running": False, "detail": "stale-state"}
        listening = all(ident.owns_listener(recorded, e.address, e.port) for e in self.surfaces)
        return {"backend": "process", "running": True, "pid": recorded.pid,
                "identity": recorded.to_json(), "listening": listening}


def _wait_uid(pid, attempts=50):
    for _ in range(attempts):
        try:
            return ident._read_uid(pid)
        except StateError:
            time.sleep(0.02)
    raise ObservedStateError("start-not-verified", "uid")


def _wait_start_time(pid, attempts=50):
    for _ in range(attempts):
        try:
            return ident._read_start_time(pid)
        except StateError:
            time.sleep(0.02)
    raise ObservedStateError("start-not-verified", "start-time")


def _resolved_exe(pid, attempts=50):
    for _ in range(attempts):
        try:
            return ident._read_exe(pid)
        except StateError:
            time.sleep(0.02)
    raise ObservedStateError("start-not-verified", "exe")


def _terminate_child(process, identity):
    if process.poll() is not None:
        return
    if identity is None:
        raise StateError('process-identity-unverified', 'child identity could not be captured; refusing an unverified signal')
    if ident.alive(identity):
        ident.stop(identity)
    elif not ident.exited(identity.pid):
        raise StateError('process-identity-mismatch', 'child identity changed; refusing an unverified signal')
    process.wait(timeout=10)
