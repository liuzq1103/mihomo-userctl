#!/usr/bin/env python3
"""Redacted JSON formatting and same-user Linux process inspection."""

import argparse
import os
from pathlib import Path
import re
import shutil
import sys
from urllib.parse import urlsplit

try:
    from . import reporting
except ImportError:  # Installed modules are executed from one runtime directory.
    import reporting


SCHEMA = reporting.DIAGNOSTICS_SCHEMA
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
    reporting.diagnostics(command, overall, payload, error)


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


def inspect(root, pid, port, uid=None):
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
        emit_json(args.report_command, "PASS", {"process": item})
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
        emit_json(args.report_command, overall, {"processes": matches,
                                                 "unverified_matches": unverified})
    else:
        for item in matches:
            text_process(item)
        if unverified:
            print("mihomo-userctl: one or more matching current-user processes could not be verified", file=sys.stderr)
        elif not matches:
            print("mihomo-userctl: no current-user process matched that exact name", file=sys.stderr)
    return 2 if unverified else 0 if matches else 1


def process_identity(root, pid):
    """Start ticks distinguish PID reuse while taking a best-effort snapshot."""
    try:
        raw = (root / str(pid) / "stat").read_text()
        return int(raw.rsplit(")", 1)[1].split()[19])
    except (OSError, ValueError, IndexError, UnicodeError):
        raise DiagnosticError("process-identity-unreadable") from None


def codex_snapshot(root=Path("/proc")):
    """Inspect only same-user Codex candidates; never emit argv or environment values."""
    expected = expected_environment()
    uid = os.getuid()
    rows, unavailable = [], 0
    try:
        candidates = sorted((p for p in root.iterdir() if p.name.isdigit()),
                            key=lambda p: int(p.name))
    except OSError:
        raise DiagnosticError("proc-unavailable") from None
    for entry in candidates:
        pid = int(entry.name)
        try:
            owner, _ = read_status(root, pid)
        except DiagnosticError:
            # A vanished process is normal; an inaccessible live entry is incomplete coverage.
            unavailable += int(entry.exists())
            continue
        if owner != uid:
            continue
        try:
            identity = process_identity(root, pid)
            name = (entry / "comm").read_text().rstrip("\n")
        except (DiagnosticError, OSError, UnicodeError):
            unavailable += int(entry.exists())
            continue
        argv = None
        if name != "codex":
            # Linux comm can be changed or truncated. Match the executable without reading argv.
            try:
                executable = os.readlink(entry / "exe")
                if executable.endswith(" (deleted)"):
                    executable = executable[:-10]
            except OSError:
                # Zombies cannot serve requests. Every other live, unclassified
                # same-UID process must be counted, not silently treated as safe.
                try:
                    state = (entry / "stat").read_text().rsplit(")", 1)[1].split()[0]
                except (OSError, UnicodeError, IndexError):
                    state = None
                if state != "Z":
                    unavailable += int(entry.exists())
                continue
            if Path(executable).name != "codex":
                # The npm entry is a node script; inspect only same-UID argv,
                # bounded, and classify it without returning paths or arguments.
                if Path(executable).name not in ("node", "nodejs", "bash", "sh"):
                    continue
                try:
                    if read_status(root, pid)[0] != uid or process_identity(root, pid) != identity:
                        raise DiagnosticError("process-changed")
                    with (entry / "cmdline").open("rb") as stream:
                        argv = stream.read(4096).split(b"\0")
                    script = argv[1] if len(argv) > 1 else b""
                    if script.rsplit(b"/", 1)[-1] not in (b"codex", b"codex.js"):
                        continue
                    argv = argv[1:]
                except (DiagnosticError, OSError):
                    unavailable += int(entry.exists())
                    continue
        try:
            if read_status(root, pid)[0] != uid or process_identity(root, pid) != identity:
                raise DiagnosticError("process-changed")
            env = proxy_environment(read_environment(root, pid), expected)
            # Read only a bounded prefix, and never include command arguments in reports.
            if argv is None:
                with (entry / "cmdline").open("rb") as stream:
                    argv = stream.read(4096).split(b"\0")
            if not argv or not argv[0]:
                raise DiagnosticError("process-arguments-unreadable")
            role = "app-server" if len(argv) > 1 and argv[1] == b"app-server" else "cli-or-helper"
            if process_identity(root, pid) != identity or read_status(root, pid)[0] != uid:
                raise DiagnosticError("process-changed")
            rows.append({"pid": pid, "role": role, "proxy_environment": env})
        except (DiagnosticError, OSError):
            rows.append({"pid": pid, "role": "unknown", "proxy_environment": None})
    return rows, unavailable


def handle_codex(args, root=Path("/proc")):
    processes, unavailable = codex_snapshot(root)
    executable_found = shutil.which("codex") is not None
    current = proxy_environment({key: os.environ[key].encode() for key in PROXY_NAMES
                                 if key in os.environ}, expected_environment())
    issues = []
    if not executable_found:
        issues.append("codex-not-on-path")
    if current["classification"] != "proxied":
        issues.append("current-shell-not-configured-for-proxy")
    if any(p["proxy_environment"] is not None and
           p["proxy_environment"]["classification"] != "proxied" for p in processes):
        issues.append("existing-process-environment-differs")
    if unavailable or any(p["proxy_environment"] is None for p in processes):
        issues.append("process-inspection-incomplete")
    actions = ["Use mihomoctl codex for a terminal launch; a verified Remote hook needs no wrapper.",
               "For connection errors, save work, close your own Codex clients, then reconnect through the intended proxy entry.",
               "If a process remains, verify its owner and client association before stopping that specific process.",
               "Do not delete credentials, sessions or sockets, or run broad pkill commands.",
               "Confirm one authorized model reply; HTTP readiness does not test WebSocket or model traffic."]
    # This is an offline snapshot, not proof of a request route or a complete process inventory.
    payload = {"executable_found": executable_found, "current_environment": current,
               "processes": processes, "unverified_entries": unavailable, "issues": issues,
               "model_request": "UNVERIFIED", "websocket": "UNVERIFIED",
               "local_transport": "DIRECT_EXPECTED", "remote_transport": "UNVERIFIED",
               "next_steps": actions}
    if args.json:
        emit_json("diagnose-codex", "UNVERIFIED", payload)
    else:
        print("Codex local check (no network request; model/WebSocket path UNVERIFIED)")
        print("local_transport=DIRECT_EXPECTED remote_transport=UNVERIFIED model_request=UNVERIFIED")
        print("executable={} current_proxy_environment={} candidates={}".format(
            "found" if executable_found else "missing", current["classification"], len(processes)))
        for item in processes:
            env = item["proxy_environment"]
            print("pid={} role={} proxy_environment={}".format(
                item["pid"], item["role"], env["classification"] if env else "unreadable"))
        for issue in issues:
            print("Check: " + issue)
        print("Process candidates are not proof of reuse or direct model traffic; custom launchers may be missed.")
        for action in actions:
            print("Next: " + action)
    return 2


def preflight_error(code):
    """Keep normal and early-error reports on the same public shape."""
    return {"launch_safe": False, "proxy": {key: "UNVERIFIED" for key in
            ("config", "service", "listener", "authentication", "http_outbound")},
            "codex": {key: "UNVERIFIED" for key in
            ("executable", "current_environment", "existing_cli", "app_server", "inspection")},
            "processes": [], "unverified_entries": 0, "checks": [],
            "invoking_environment": None,
            "reasons": [code], "levels": {key: "UNVERIFIED" for key in
            ("CONTROL_PLANE_INSTALLED", "PROXY_READY", "CODEX_RUNTIME_CLEAN", "CODEX_E2E_VERIFIED")},
            "local_transport": "DIRECT_EXPECTED", "remote_transport": "UNVERIFIED",
            "model_request": "UNVERIFIED"}


def combine_status(statuses):
    statuses = list(statuses)
    return "UNVERIFIED" if "UNVERIFIED" in statuses else "FAIL" if "FAIL" in statuses else "PASS"


def codex_preflight(root=Path("/proc")):
    """One policy shared by inspection and launch. No model traffic or mutations."""
    # Only the preflight entry loads network probes; its shell wrapper validates
    # this module first. Offline diagnosis retains its previous dependencies.
    try:
        from . import acceptance
    except ImportError:
        import acceptance
    expected = expected_environment()
    try:
        port = int(os.environ["MIHOMO_PORT"])
        service = os.environ["MIHOMO_SERVICE"]
        url = os.environ["MIHOMO_READY_URL"]
        if (not 1024 <= port <= 65535 or not re.fullmatch(r"[A-Za-z0-9_.@-]+", service)
                or not acceptance.public_https_url(url)):
            raise ValueError
        for key, scheme in (("http_proxy", "http"), ("https_proxy", "http"),
                            ("all_proxy", "socks5h")):
            endpoint = urlsplit(expected[key])
            if (endpoint.scheme != scheme or endpoint.hostname != "127.0.0.1"
                    or endpoint.port != port or not endpoint.username or not endpoint.password
                    or endpoint.path not in ("", "/") or endpoint.query or endpoint.fragment):
                raise ValueError
    except (KeyError, ValueError):
        raise DiagnosticError("configuration-or-credentials-invalid") from None
    payload = preflight_error("pending")
    payload["reasons"] = []
    proxy, codex = payload["proxy"], payload["codex"]
    proxy["config"] = "PASS"
    payload["levels"]["CONTROL_PLANE_INSTALLED"] = "PASS"
    executable = shutil.which("codex")
    codex["executable"] = "PASS" if executable else "FAIL"
    # Ordinary shells intentionally remain direct. Report their state, but
    # evaluate the freshly prepared launch environment, not the parent shell.
    payload["invoking_environment"] = proxy_environment(
        {k: os.environ[k].encode() for k in PROXY_NAMES if k in os.environ}, expected)
    launch_env = dict(os.environ)
    for key in list(launch_env):
        if key.startswith("MIHOMO_") or key in PROXY_NAMES:
            launch_env.pop(key)
    launch_env.update(expected)
    codex["current_environment"] = "PASS" if proxy_environment(
        {k: launch_env[k].encode() for k in PROXY_NAMES}, expected)["classification"] == "proxied" else "FAIL"

    measured = [acceptance.service_active_check(service, 5), acceptance.listener_check(port, 5)]
    proxy["service"], proxy["listener"] = (item.status for item in measured)
    if all(item.status == "PASS" for item in measured):
        auth = [acceptance.http_no_auth(url, port, 5), acceptance.socks_no_auth(port, 5)]
        outbound = acceptance.curl_check("http-auth", url, port, 5, None, expected["https_proxy"])
        measured.extend(auth + [outbound])
        proxy["authentication"] = combine_status(item.status for item in auth)
        proxy["http_outbound"] = outbound.status
    else:
        proxy["authentication"] = proxy["http_outbound"] = "SKIPPED"
    payload["checks"] = [{"name": item.check, "status": item.status, "evidence": item.evidence}
                         for item in measured]
    for key, state in proxy.items():
        if state in ("FAIL", "UNVERIFIED"):
            payload["reasons"].append("proxy-" + key.replace("_", "-") + "-" + state.lower())
    payload["levels"]["PROXY_READY"] = combine_status(proxy.values())

    try:
        processes, unavailable = codex_snapshot(root)
    except DiagnosticError:
        processes, unavailable = [], 1
    payload["processes"], payload["unverified_entries"] = processes, unavailable
    incomplete = bool(unavailable) or any(item["proxy_environment"] is None for item in processes)
    codex["inspection"] = "UNVERIFIED" if incomplete else "PASS"
    for field, role in (("existing_cli", "cli-or-helper"), ("app_server", "app-server")):
        matching = [item for item in processes if item["role"] == role]
        codex[field] = combine_status("UNVERIFIED" if item["proxy_environment"] is None else
            "PASS" if item["proxy_environment"]["classification"] == "proxied" else "FAIL"
            for item in matching)
        if incomplete and codex[field] == "PASS":
            codex[field] = "UNVERIFIED"
    for item in processes:
        env = item["proxy_environment"]
        if env is not None and env["classification"] != "proxied":
            payload["reasons"].append("stale-" + env["classification"] + "-" + item["role"])
    if incomplete:
        payload["reasons"].append("process-inspection-incomplete")
    if not executable:
        payload["reasons"].append("codex-not-on-path")
    payload["levels"]["CODEX_RUNTIME_CLEAN"] = combine_status(codex.values())
    state = combine_status(list(proxy.values()) + list(codex.values()))
    overall = {"PASS": "SAFE_TO_LAUNCH", "FAIL": "BLOCKED", "UNVERIFIED": "UNVERIFIED"}[state]
    payload["launch_safe"] = overall == "SAFE_TO_LAUNCH"
    payload["reasons"] = sorted(set(payload["reasons"]))
    return overall, payload, executable, launch_env


def report_preflight(overall, payload, json_output=False, stream=None, error=None):
    if json_output:
        emit_json("codex-preflight", overall, payload, error=error)
    else:
        stream = stream or sys.stdout
        for title in ("proxy", "codex"):
            print(title.title(), file=stream)
            for key, value in payload[title].items():
                print("  {:20s} {}".format(key, value), file=stream)
        print("Overall\n  " + overall, file=stream)
        for reason in payload["reasons"]:
            print("Reason: " + reason, file=stream)
        for item in payload["processes"]:
            env = item["proxy_environment"]
            print("  PID={} role={} proxy_environment={}".format(item["pid"], item["role"],
                  env["classification"] if env else "unreadable"), file=stream)
        print("local_transport=DIRECT_EXPECTED remote_transport=UNVERIFIED model_request=UNVERIFIED", file=stream)
        if not payload["launch_safe"]:
            print("Codex was not launched. Run mihomoctl doctor and mihomoctl diagnose codex.\n"
                  "For stale processes, save work, normally close or reconnect your own clients,\n"
                  "then run mihomoctl codex again. A new CLI cannot update an old app-server.\n"
                  "No process was stopped; no credentials, sessions or sockets were removed.", file=stream)
    return {"SAFE_TO_LAUNCH": 0, "BLOCKED": 1, "UNVERIFIED": 2}[overall]


def handle_preflight(args):
    try:
        overall, payload, executable, env = codex_preflight()
    except (DiagnosticError, OSError, ValueError) as error:
        code = error.code if isinstance(error, DiagnosticError) else "inspection-error"
        overall, payload = "UNVERIFIED", preflight_error(code)
    launching = args.launch is not None
    if launching and payload["launch_safe"]:
        try:
            os.execve(executable, [executable] + args.launch, env)
        except OSError:
            overall, payload = "UNVERIFIED", preflight_error("codex-exec-failed")
    return report_preflight(overall, payload, args.json,
                            sys.stderr if launching else sys.stdout)


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
    error.add_argument("kind", choices=("status", "ready", "doctor", "diagnose",
                                        "diagnose-url", "diagnose-process", "diagnose-name", "diagnose-codex",
                                        "test-url", "inspect-process", "inspect-name", "codex-preflight"))
    error.add_argument("code")
    codex = sub.add_parser("codex")
    codex.add_argument("--port", required=True, type=int)
    codex.add_argument("--json", action="store_true")
    codex.add_argument("--report-command", choices=("diagnose-codex",), default="diagnose-codex")
    preflight = sub.add_parser("codex-preflight")
    preflight.add_argument("--json", action="store_true")
    preflight.add_argument("--launch", nargs=argparse.REMAINDER, default=None, help=argparse.SUPPRESS)
    for name, canonical, legacy in (("process", "diagnose-process", "inspect-process"),
                                    ("name", "diagnose-name", "inspect-name")):
        child = sub.add_parser(name)
        child.add_argument("target")
        child.add_argument("--port", required=True, type=int)
        child.add_argument("--json", action="store_true")
        child.add_argument("--report-command", choices=(canonical, legacy), default=canonical)
    return root


def main(argv=None):
    values = list(argv if argv is not None else sys.argv[1:])
    command = ("diagnose-" + values[0] if values and values[0] in ("process", "name", "codex")
               else "diagnostics")
    try:
        args = parser().parse_args(argv)
        command = getattr(args, "report_command", args.command)
        if args.command == "error":
            if not re.fullmatch(r"[a-z0-9-]+", args.code):
                raise DiagnosticError("invalid-internal-error")
            if args.kind == "codex-preflight":
                return report_preflight("UNVERIFIED", preflight_error(args.code), True, error=args.code)
            emit_json(args.kind, "UNVERIFIED", error=args.code)
            return 2
        if args.command == "codex-preflight":
            return handle_preflight(args)
        if args.command == "format":
            if not 1024 <= (args.port or 0) <= 65535:
                raise DiagnosticError("invalid-internal-port")
            return handle_format(args)
        if not 1024 <= args.port <= 65535:
            raise DiagnosticError("invalid-port")
        if args.command == "codex":
            return handle_codex(args)
        return handle_process(args) if args.command == "process" else handle_name(args)
    except DiagnosticError as error:
        wants_json = "--json" in (argv if argv is not None else sys.argv[1:])
        if wants_json:
            emit_json(command, "UNVERIFIED", error=error.code)
        print("mihomo-userctl: " + error.message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
