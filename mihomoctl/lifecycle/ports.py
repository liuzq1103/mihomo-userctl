"""Loopback listener observation via procfs (evidence: inferred)."""

import socket
import struct
import time
from pathlib import Path

from ..errors import ObservedStateError, StateError

PROC = Path("/proc")


def _v4(hexaddr):
    value = int(hexaddr, 16)
    return socket.inet_ntop(socket.AF_INET, struct.pack("<I", value))


def _v6(hexaddr):
    raw = b""
    for index in range(4):
        raw += struct.pack("<I", int(hexaddr[index * 8:(index + 1) * 8], 16))
    return socket.inet_ntop(socket.AF_INET6, raw)


def _normalize(address):
    if address == "localhost":
        return "127.0.0.1"
    try:
        return socket.inet_ntop(socket.AF_INET, socket.inet_aton(address))
    except OSError:
        return socket.inet_ntop(socket.AF_INET6, socket.inet_pton(socket.AF_INET6, address))


def listening_rows(address=None, port=None, proc=PROC):
    """All LISTEN rows matching address/port (either may be None)."""
    rows = []
    for table, family in (("tcp", socket.AF_INET), ("tcp6", socket.AF_INET6)):
        path = proc / "net" / table
        try:
            text = path.read_text()
        except OSError:
            if table == "tcp":
                raise StateError("listener-inspection-unavailable", "procfs net table missing") from None
            continue
        for line in text.splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10 or fields[3] != "0A":
                continue
            local_address, _, local_port = fields[1].partition(":")
            try:
                row = {
                    "address": _v4(local_address) if family == socket.AF_INET else _v6(local_address),
                    "port": int(local_port, 16),
                    "uid": int(fields[7]),
                    "inode": fields[9],
                }
            except (ValueError, OSError):
                continue
            if address is not None and row["address"] != _normalize(address):
                continue
            if port is not None and row["port"] != port:
                continue
            rows.append(row)
    return rows


def port_occupied(address, port, proc=PROC):
    return bool(listening_rows(address, port, proc))


def check_ports_free(endpoints, proc=PROC):
    """Preflight: every endpoint bind must currently be free.

    A free check is not a reservation; the kernel adjudicates at bind."""
    occupied = []
    for endpoint in endpoints:
        unavailable = bool(listening_rows(endpoint.address, endpoint.port, proc))
        if proc == PROC and not unavailable:
            family = socket.AF_INET6 if ':' in endpoint.address else socket.AF_INET
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind((endpoint.address, endpoint.port))
                except OSError:
                    unavailable = True
        if unavailable:
            occupied.append("%s:%d (%s)" % (endpoint.address, endpoint.port, endpoint.name))
    if occupied:
        raise ObservedStateError("port-conflict",
                                 "listening surface already occupied: " + ", ".join(occupied),
                                 remediation="choose free ports or stop the occupying service")
    return True


def wait_listening(endpoints, uid, timeout, expect_pid=None, proc=PROC):
    """Postflight: all endpoints listening, owned by ``uid`` (inferred),
    and — when given — socket inodes owned by the exact process.  Any
    unverified ownership keeps the endpoint pending (fail closed)."""
    from ..identity import owns_listener
    deadline = time.monotonic() + timeout

    def satisfied(endpoint):
        rows = [r for r in listening_rows(endpoint.address, endpoint.port, proc)
                if r["uid"] == uid]
        if not rows:
            return False
        if expect_pid is not None and not owns_listener(expect_pid, endpoint.address, endpoint.port):
            return False
        return True

    pending = list(endpoints)
    while time.monotonic() < deadline:
        pending = [e for e in pending if not satisfied(e)]
        if not pending:
            return True
        time.sleep(0.1)
    raise ObservedStateError("start-not-verified",
                             "endpoints did not come up (or ownership unverified) within %ss: %s"
                             % (timeout, [(e.address, e.port, e.name) for e in pending]))


def port_free_now(port):
    """Best-effort ephemeral candidate: bind then close.  This never
    reserves the port and callers must say so in output."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        sock.bind(("127.0.0.1", port))
    return True


def free_port():
    """Ask the kernel for one currently-free loopback port (bind 0).
    Not a reservation; callers must report it as a candidate only."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
