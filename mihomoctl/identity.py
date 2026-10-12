"""Process identity: PID + start time + UID + executable.

Before any signal is delivered the identity is re-read and compared;
PID reuse or unobservable identity fails closed.  Never use process-name
matching to select a victim.
"""

import os
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import StateError

PROC = Path("/proc")


def _read_start_time(pid):
    try:
        text = (PROC / str(pid) / "stat").read_text()
    except OSError:
        raise StateError("process-unreadable", "pid %s" % pid) from None
    # comm may contain spaces/parens; fields restart after the last ')'.
    try:
        tail = text.rsplit(")", 1)[1].split()
        if tail[0] in ('Z', 'X'):
            raise StateError('process-exited', 'pid %s is no longer live' % pid)
        return int(tail[19])  # field 22 overall (0-based index 19 after state)
    except (IndexError, ValueError):
        raise StateError("process-status-invalid", "pid %s" % pid) from None


def _read_uid(pid):
    try:
        for line in (PROC / str(pid) / "status").read_text().splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
    except OSError:
        pass
    raise StateError("process-unreadable", "pid %s" % pid)


def _read_exe(pid):
    try:
        return os.readlink(str(PROC / str(pid) / "exe"))
    except OSError:
        raise StateError("process-unreadable", "pid %s executable" % pid) from None


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    uid: int
    start_time: int
    exe: str
    config: str = None

    def to_json(self):
        return {"pid": self.pid, "uid": self.uid, "start_time": self.start_time, "exe": self.exe,
                'config': self.config}


def _read_config(pid):
    try:
        args = (PROC / str(pid) / 'cmdline').read_bytes().split(b'\0')
        indices = [i for i, arg in enumerate(args) if arg == b'-f']
        if len(indices) != 1:
            return None
        return os.fsdecode(args[indices[0] + 1])
    except (OSError, IndexError):
        raise StateError('process-unreadable', 'process configuration identity unavailable') from None


def exited(pid):
    try:
        return (PROC / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0] in ('Z', 'X')
    except FileNotFoundError:
        return True
    except (OSError, IndexError):
        return False


def read_identity(pid, exe=None):
    pid = int(pid)
    if pid <= 1:
        raise StateError("process-invalid", "refusing to signal pid %s" % pid)
    first = (_read_start_time(pid), _read_uid(pid), _read_exe(pid), _read_config(pid))
    second = (_read_start_time(pid), _read_uid(pid), _read_exe(pid), _read_config(pid))
    if first != second:
        raise StateError('process-identity-mismatch', 'process changed during identity read')
    identity = ProcessIdentity(pid, first[1], first[0], first[2], first[3])
    if exe is not None and identity.exe != exe:
        raise StateError("process-identity-mismatch",
                         "pid %s exe changed (expected %s)" % (pid, exe))
    return identity


def alive(identity):
    """True when the exact same process (PID + start time) still exists."""
    try:
        current = read_identity(identity.pid)
    except StateError:
        return False
    return (current.uid == identity.uid and current.start_time == identity.start_time
            and current.exe == identity.exe and current.config == identity.config)


def exists_any(pid):
    return (PROC / str(pid)).exists()


def stop(identity, term_seconds=10, kill_seconds=10):
    """Stop exactly the identified process: SIGTERM, wait, then SIGKILL —
    re-verifying identity before each signal.  Never signals a reused PID."""
    if not alive(identity):
        return False
    _signal(identity, signal.SIGTERM)
    deadline = time.monotonic() + term_seconds
    while time.monotonic() < deadline:
        if not alive(identity):
            return True
        time.sleep(0.05)
    if alive(identity):
        _signal(identity, signal.SIGKILL)
        deadline = time.monotonic() + kill_seconds
        while time.monotonic() < deadline:
            if not alive(identity):
                return True
            time.sleep(0.05)
    if exists_any(identity.pid):
        raise StateError("stop-unverified", "pid %d did not exit" % identity.pid)
    return True


def _signal(identity, sig):
    fd = None
    try:
        if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
            fd = os.pidfd_open(identity.pid)
        if not alive(identity):
            raise StateError('process-identity-mismatch', 'refusing to signal changed process')
        if fd is not None:
            signal.pidfd_send_signal(fd, sig)
        else:
            os.kill(identity.pid, sig)
    except ProcessLookupError:
        return
    finally:
        if fd is not None:
            os.close(fd)


def owns_listener(identity, address, port):
    """Check that a listening socket inode belongs to the identified process.

    Evidence level is inferred (procfs matching), not kernel-confirmed.
    """
    from .lifecycle.ports import listening_rows
    if not alive(identity):
        return False
    inodes = set()
    base = PROC / str(identity.pid) / "fd"
    try:
        entries = list(base.iterdir())
    except OSError:
        return False
    for entry in entries:
        try:
            target = os.readlink(str(entry))
        except OSError:
            continue
        if target.startswith("socket:[") and target.endswith("]"):
            inodes.add(target[8:-1])
    rows = listening_rows(address, port)
    return bool(rows) and all(row['uid'] == identity.uid and str(row.get('inode')) in inodes for row in rows) and alive(identity)
