"""Read-only, same-UID process evidence; never launches an application."""
import os
import re


PROXY_NAMES = ("http_proxy", "https_proxy", "all_proxy", "no_proxy",
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
SOCKET = re.compile(r"socket:\[([0-9]+)\]$")


try:
    from . import reporting
except ImportError:  # Installed modules are executed from one runtime directory.
    import reporting


class DiagnosticError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


def safe_name(raw):
    return "".join(char if 32 <= ord(char) < 127 else "?" for char in raw.strip())[:64]


def read_status(root, pid):
    try:
        lines = (root / str(pid) / "status").read_text(errors="strict").splitlines()
    except (OSError, UnicodeError):
        raise DiagnosticError("process-unreadable") from None
    fields = {}
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            fields[key] = value.strip()
    try:
        uid = int(fields["Uid"].split()[0])
        ppid = int(fields["PPid"].split()[0])
    except (KeyError, ValueError, IndexError):
        raise DiagnosticError("process-status-invalid") from None
    return uid, ppid


def read_environment(root, pid):
    try:
        raw = (root / str(pid) / "environ").read_bytes()
    except OSError:
        raise DiagnosticError("process-environment-unreadable") from None
    values = {}
    for entry in raw.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        try:
            name = key.decode("ascii")
        except UnicodeError:
            continue
        if name in PROXY_NAMES:
            if name in values:
                raise DiagnosticError("process-environment-ambiguous")
            values[name] = value
    return values


def proxy_environment(values, expected):
    present = sum(bool(values.get(name)) for name in PROXY_NAMES)
    if present == 0:
        state = "direct"
        matching = None
    else:
        matching = present == len(PROXY_NAMES) and all(
            values.get(name) == expected.get(name, "").encode() for name in PROXY_NAMES)
        state = "proxied" if matching else "inconsistent"
    return {"present": present, "expected": len(PROXY_NAMES),
            "classification": state, "matches_current_config": matching}


def process_socket_inodes(root, pid):
    result = set()
    try:
        entries = list((root / str(pid) / "fd").iterdir())
    except OSError:
        raise DiagnosticError("process-sockets-unreadable") from None
    for entry in entries:
        try:
            match = SOCKET.fullmatch(os.readlink(entry))
        except OSError:
            continue
        if match:
            result.add(match[1])
    return result


def split_endpoint(value):
    address, raw_port = value.rsplit(":", 1)
    return address.upper(), int(raw_port, 16)


def is_loopback_hex(address):
    return address in ("0100007F", "00000000000000000000000001000000")


def connection_categories(root, pid, port):
    sockets = process_socket_inodes(root, pid)
    listener = 0
    non_loopback = 0
    for table in ("tcp", "tcp6"):
        try:
            rows = (root / str(pid) / "net" / table).read_text().splitlines()[1:]
        except OSError:
            if table == "tcp":
                raise DiagnosticError("process-network-unreadable") from None
            continue
        for row in rows:
            fields = row.split()
            if len(fields) < 10 or fields[3] != "01" or fields[9] not in sockets:
                continue
            try:
                local_address, local_port = split_endpoint(fields[1])
                remote_address, remote_port = split_endpoint(fields[2])
            except (ValueError, IndexError):
                continue
            if ((is_loopback_hex(local_address) and local_port == port)
                    or (is_loopback_hex(remote_address) and remote_port == port)):
                listener += 1
            elif not is_loopback_hex(remote_address) and set(remote_address) != {"0"}:
                non_loopback += 1
    return {"listener_established": listener,
            "other_non_loopback_established": non_loopback}


def expected_environment():
    try:
        http = os.environ["MIHOMO_HTTP_PROXY"]
        https = os.environ["MIHOMO_HTTPS_PROXY"]
        socks = os.environ["MIHOMO_ALL_PROXY"]
    except KeyError:
        raise DiagnosticError("validated-credentials-missing") from None
    bypass = "localhost,127.0.0.1,::1"
    return {"http_proxy": http, "https_proxy": https, "all_proxy": socks,
            "no_proxy": bypass, "HTTP_PROXY": http, "HTTPS_PROXY": https,
            "ALL_PROXY": socks, "NO_PROXY": bypass}


def inspect(root, pid, port, uid=None, expected=None):
    uid = os.getuid() if uid is None else uid
    owner, ppid = read_status(root, pid)
    if owner != uid:
        raise DiagnosticError("process-not-owned-by-current-user")
    try:
        name = safe_name((root / str(pid) / "comm").read_text(errors="strict"))
    except (OSError, UnicodeError):
        raise DiagnosticError("process-name-unreadable") from None
    parent = {"pid": ppid, "same_user": False}
    if ppid > 0:
        try:
            parent_uid, _ = read_status(root, ppid)
            if parent_uid == uid:
                parent["same_user"] = True
        except DiagnosticError:
            pass
    expected = expected_environment() if expected is None else dict(expected)
    return {"pid": pid, "name": name, "parent": parent,
            "proxy_environment": proxy_environment(read_environment(root, pid), expected),
            "connections": connection_categories(root, pid, port)}
