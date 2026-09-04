#!/usr/bin/env python3
"""Redacted JSON formatting and same-user Linux process inspection."""

import argparse
import json
import os
from pathlib import Path
import re
import sys


SCHEMA = "mihomo-userctl.diagnostics/v1"
PROXY_NAMES = ("http_proxy", "https_proxy", "all_proxy", "no_proxy",
               "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")
SOCKET = re.compile(r"socket:\[([0-9]+)\]$")


class DiagnosticError(Exception):
    def __init__(self, code, message=None):
        self.code = code
        self.message = message or code
        super().__init__(self.message)


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise DiagnosticError("invalid-options")


def emit_json(command, overall, payload=None, error=None):
    document = {"schema": SCHEMA, "command": command, "overall": overall}
    if payload:
        document.update(payload)
    if error:
        document["error"] = {"code": error}
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))


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


def inspect(root, pid, port, uid=None):
    uid = os.getuid() if uid is None else uid
    owner, ppid = read_status(root, pid)
    if owner != uid:
        raise DiagnosticError("process-not-owned-by-current-user")
    try:
        name = safe_name((root / str(pid) / "comm").read_text(errors="strict"))
    except (OSError, UnicodeError):
        raise DiagnosticError("process-name-unreadable") from None
    parent = {"pid": ppid, "same_user": False, "name": None}
    if ppid > 0:
        try:
            parent_uid, _ = read_status(root, ppid)
            if parent_uid == uid:
                parent["same_user"] = True
                parent["name"] = safe_name((root / str(ppid) / "comm").read_text(errors="strict"))
        except (DiagnosticError, OSError, UnicodeError):
            pass
    return {"pid": pid, "name": name, "parent": parent,
            "proxy_environment": proxy_environment(read_environment(root, pid), expected_environment()),
            "connections": connection_categories(root, pid, port)}


def text_process(item):
    env = item["proxy_environment"]
    connections = item["connections"]
    parent = item["parent"]
    print("pid={} name={} parent={} parent_same_user={} proxy_vars={}/{} proxy_state={} "
          "listener_connections={} non_loopback_connections={}".format(
              item["pid"], item["name"], parent["pid"], str(parent["same_user"]).lower(),
              env["present"], env["expected"], env["classification"],
              connections["listener_established"], connections["other_non_loopback_established"]))


def handle_process(args, root=Path("/proc")):
    if not re.fullmatch(r"[1-9][0-9]*", args.target):
        raise DiagnosticError("invalid-pid")
    item = inspect(root, int(args.target), args.port)
    if args.json:
        emit_json("inspect-process", "PASS", {"process": item})
    else:
        text_process(item)
    return 0


def handle_name(args, root=Path("/proc")):
    if (not args.target or len(args.target) > 64 or "/" in args.target
            or any(ord(char) < 32 or ord(char) == 127 for char in args.target)):
        raise DiagnosticError("invalid-process-name")
    matches = []
    unverified = 0
    uid = os.getuid()
    try:
        candidates = sorted((entry for entry in root.iterdir() if entry.name.isdigit()),
                            key=lambda entry: int(entry.name))
    except OSError:
        raise DiagnosticError("proc-unavailable") from None
    for entry in candidates:
        try:
            owner, _ = read_status(root, int(entry.name))
            if owner != uid:
                continue
            if (entry / "comm").read_text(errors="strict").rstrip("\n") != args.target:
                continue
            try:
                matches.append(inspect(root, int(entry.name), args.port, uid=uid))
            except DiagnosticError:
                unverified += 1
        except (DiagnosticError, OSError, UnicodeError):
            continue
    if args.json:
        overall = "UNVERIFIED" if unverified else "PASS" if matches else "FAIL"
        emit_json("inspect-name", overall, {"processes": matches,
                                            "unverified_matches": unverified})
    else:
        for item in matches:
            text_process(item)
        if unverified:
            print("mihomo-userctl: one or more matching current-user processes could not be verified", file=sys.stderr)
        elif not matches:
            print("mihomo-userctl: no current-user process matched that exact name", file=sys.stderr)
    return 2 if unverified else 0 if matches else 1


def handle_format(args):
    if args.kind == "status":
        payload = {"service": {"active": args.service == "up", "enabled": args.enabled},
                   "listener": {"listening": args.listener == "up",
                                "endpoint": "127.0.0.1:" + str(args.port)}}
        overall = "PASS" if args.service == args.listener == "up" else "FAIL"
    elif args.kind == "ready":
        payload = {"ready": args.ready == "up",
                   "listener": {"endpoint": "127.0.0.1:" + str(args.port)}}
        overall = "PASS" if args.ready == "up" else "FAIL"
    else:
        checks = []
        for raw in args.check:
            name, status = raw.split("=", 1)
            if not re.fullmatch(r"[a-z0-9-]+", name) or status not in ("PASS", "FAIL", "UNVERIFIED", "SKIPPED"):
                raise DiagnosticError("invalid-internal-check")
            checks.append({"name": name, "status": status})
        overall = "FAIL" if any(row["status"] == "FAIL" for row in checks) else (
            "UNVERIFIED" if any(row["status"] == "UNVERIFIED" for row in checks) else "PASS")
        payload = {"checks": checks, "service": {"active": args.service == "up",
                   "enabled": args.enabled}, "listener": {"listening": args.listener == "up",
                   "endpoint": "127.0.0.1:" + str(args.port)}}
    emit_json(args.kind, overall, payload)
    return 0 if overall == "PASS" else 1 if overall == "FAIL" else 2


def parser():
    root = Parser(add_help=True)
    sub = root.add_subparsers(dest="command", required=True)
    fmt = sub.add_parser("format")
    fmt.add_argument("kind", choices=("status", "ready", "doctor"))
    fmt.add_argument("--service", choices=("up", "down"))
    fmt.add_argument("--enabled", default="unknown")
    fmt.add_argument("--listener", choices=("up", "down"))
    fmt.add_argument("--ready", choices=("up", "down"))
    fmt.add_argument("--port", type=int)
    fmt.add_argument("--check", action="append", default=[])
    error = sub.add_parser("error")
    error.add_argument("kind", choices=("status", "ready", "doctor", "test-url",
                                        "inspect-process", "inspect-name"))
    error.add_argument("code")
    for name in ("inspect-process", "inspect-name"):
        child = sub.add_parser(name)
        child.add_argument("target")
        child.add_argument("--port", required=True, type=int)
        child.add_argument("--json", action="store_true")
    return root


def main(argv=None):
    values = list(argv if argv is not None else sys.argv[1:])
    command = values[0] if values and values[0] in (
        "inspect-process", "inspect-name") else "diagnostics"
    try:
        args = parser().parse_args(argv)
        command = args.command
        if args.command == "error":
            if not re.fullmatch(r"[a-z0-9-]+", args.code):
                raise DiagnosticError("invalid-internal-error")
            emit_json(args.kind, "UNVERIFIED", error=args.code)
            return 2
        if args.command == "format":
            if not 1024 <= (args.port or 0) <= 65535:
                raise DiagnosticError("invalid-internal-port")
            return handle_format(args)
        if not 1024 <= args.port <= 65535:
            raise DiagnosticError("invalid-port")
        return handle_process(args) if args.command == "inspect-process" else handle_name(args)
    except DiagnosticError as error:
        wants_json = "--json" in (argv if argv is not None else sys.argv[1:])
        if wants_json:
            emit_json(command, "UNVERIFIED", error=error.code)
        print("mihomo-userctl: " + error.message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
