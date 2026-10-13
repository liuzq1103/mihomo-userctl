#!/usr/bin/env python3
"""Per-process Paseo proxy injection. No global environment or forced process cleanup."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit

try:
    from . import acceptance as a, diagnostics as d
except ImportError:
    import acceptance as a
    import diagnostics as d


PROC = Path("/proc")
MANDATORY = ("127.0.0.1", "localhost", "::1", "relay.paseo.sh")
DIRECT = ("open.bigmodel.cn", "api.z.ai", "api.deepseek.com", "api.minimaxi.com", "api.minimax.io")
ALLOWED = ("bigmodel.cn", "z.ai", "deepseek.com", "minimaxi.com", "minimax.io")
PROTECTED = ("openai.com", "chatgpt.com", "github.com", "google.com")
TARGETS = ("https://chatgpt.com/", "https://api.openai.com/", "https://auth.openai.com/")
MARKER = "# Managed by mihomo-userctl paseo; format=1"
START_TIMEOUT = 60


class Error(d.DiagnosticError):
    pass


def config_home():
    return Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))


def private_file(path, exact=False):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
            or info.st_mode & 0o022 or (exact and stat.S_IMODE(info.st_mode) != 0o600)):
        raise Error("unsafe-paseo-file")
    if info.st_size > 2 * 1024 * 1024:
        raise Error("paseo-file-too-large")
    return path.read_text(encoding="utf-8")


def jsonc(text):
    """Strip comments/trailing commas with a lexer, preserving strings and URLs."""
    pattern = r'"(?:\\.|[^"\\])*"|//[^\n\r]*|/\*[\s\S]*?\*/'
    text = re.sub(pattern, lambda m: m[0] if m[0].startswith('"') else " ", text)
    text = re.sub(r'("(?:\\.|[^"\\])*")|,(\s*[}\]])',
                  lambda m: m[1] if m[1] is not None else m[2], text)
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        raise Error("paseo-json-invalid") from None


def domain(value):
    if not isinstance(value, str):
        raise Error("direct-domain-invalid")
    host = value.lower().rstrip(".")
    if host in MANDATORY:
        return host
    if (not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host)
            or "." not in host or any(not x or len(x) > 63 or x.startswith("-") or x.endswith("-")
                                     for x in host.split("."))):
        raise Error("direct-domain-invalid")
    if any(host == p or host.endswith("." + p) or p.endswith("." + host) for p in PROTECTED):
        raise Error("direct-domain-conflicts-with-proxy-policy")
    return host


def settings():
    path = config_home() / "mihomo/paseo-proxy.json"
    result = {"direct_domains": list(DIRECT), "opencode_allowed_domains": list(ALLOWED),
              "opencode_config_files": []}
    if path.exists() or path.is_symlink():
        value = jsonc(private_file(path, exact=True))
        if not isinstance(value, dict) or set(value) - set(result):
            raise Error("paseo-config-invalid")
        result.update(value)
    for key in result:
        if not isinstance(result[key], list) or not all(isinstance(x, str) for x in result[key]):
            raise Error("paseo-config-invalid")
    for key in ("direct_domains", "opencode_allowed_domains"):
        result[key] = sorted(set(domain(x) for x in result[key]))
    return result


def proxy_environment():
    cfg = settings()
    hosts = set(MANDATORY) | set(cfg["direct_domains"])
    pending = set()
    files = [config_home() / "opencode/opencode.json", config_home() / "opencode/opencode.jsonc"]
    extra = cfg["opencode_config_files"] + ([os.environ["OPENCODE_CONFIG"]]
                                           if os.environ.get("OPENCODE_CONFIG") else [])
    for name in extra:
        path = Path(name).expanduser()
        if not path.is_absolute():
            raise Error("opencode-config-path-must-be-absolute")
        if not path.exists():
            raise Error("opencode-config-missing")
        files.append(path)
    sources = [jsonc(private_file(p)) for p in dict.fromkeys(files) if p.exists() or p.is_symlink()]
    if os.environ.get("OPENCODE_CONFIG_CONTENT"):
        sources.append(jsonc(os.environ["OPENCODE_CONFIG_CONTENT"]))
    for source in sources:
        if not isinstance(source, dict) or not isinstance(source.get("provider", {}), dict):
            raise Error("opencode-config-invalid")
        for provider in source.get("provider", {}).values():
            if not isinstance(provider, dict):
                raise Error("opencode-provider-invalid")
            options = provider.get("options", {})
            if not isinstance(options, dict):
                raise Error("opencode-provider-invalid")
            value = options.get("baseURL")
            if value is None:
                continue
            if not isinstance(value, str):
                raise Error("opencode-base-url-invalid")
            value = re.sub(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}",
                           lambda m: os.environ.get(m[1], ""), value)
            try:
                url = urlsplit(value)
                host = url.hostname
                if url.scheme not in ("http", "https") or not host or "{" in value:
                    raise ValueError
                # Only retain the hostname; credentials/path/query never enter reports.
                host = host.lower().rstrip(".")
                _ = url.port
            except ValueError:
                raise Error("opencode-base-url-invalid") from None
            approved = any(host == x or host.endswith("." + x) for x in cfg["opencode_allowed_domains"])
            if approved or host in hosts:
                hosts.add(domain(host))
            elif not any(host == p or host.endswith("." + p) for p in PROTECTED):
                pending.add(host)
    env = d.expected_environment()
    bypass = ",".join(MANDATORY + tuple(sorted(hosts - set(MANDATORY))))
    env.update(NO_PROXY=bypass, no_proxy=bypass)
    return env, sorted(pending)


def launch_environment(expected, home):
    env = a.clean_environment()
    env.pop("PASEO_HOST", None)
    env.update(expected)
    env["PASEO_HOME"] = str(home)
    return env


def selected_home(value=None):
    path = Path(value or os.environ.get("PASEO_HOME", str(Path.home() / ".paseo"))).expanduser()
    if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise Error("paseo-home-must-be-absolute")
    path = path.resolve()
    if path.exists() and (not path.is_dir() or path.stat().st_uid != os.getuid()):
        raise Error("paseo-home-not-owned")
    return path


def executable(value=None):
    found = shutil.which(value or "paseo")
    if not found:
        raise Error("paseo-not-on-path")
    return str(Path(found).absolute())


def command(binary, home, action, *args, env=None, timeout=10):
    clean = a.clean_environment() if env is None else dict(env)
    clean.pop("PASEO_HOST", None)
    clean["PASEO_HOME"] = str(home)
    return a.run_command([binary, "daemon", action, "--home", str(home), *args], timeout, clean)


def status(binary, home):
    result = command(binary, home, "status", "--json")
    if result is None or result.returncode:
        raise Error("paseo-status-unavailable")
    try:
        value = json.loads(result.stdout)
        if not isinstance(value, dict) or Path(value["home"]).resolve() != home:
            raise ValueError
        if value.get("localDaemon") not in ("stopped", "running", "not_ready"):
            raise ValueError
        pid = value.get("pid")
        if value["localDaemon"] == "stopped" and pid is not None:
            raise ValueError
        if value["localDaemon"] != "stopped" and (type(pid) is not int or pid <= 1):
            raise ValueError
        return value
    except (ValueError, KeyError, TypeError):
        raise Error("paseo-status-unsupported") from None


def identity(root, pid):
    owner, parent = d.read_status(root, pid)
    if owner != os.getuid():
        raise Error("paseo-process-not-owned")
    ticks = d.process_identity(root, pid)
    if d.read_status(root, pid) != (owner, parent) or d.process_identity(root, pid) != ticks:
        raise Error("paseo-process-changed")
    return parent, ticks


def argv(root, pid, expected_identity):
    if identity(root, pid) != expected_identity:
        raise Error("paseo-process-changed")
    with (root / str(pid) / "cmdline").open("rb") as stream:
        value = stream.read(8192).split(b"\0")
    if identity(root, pid) != expected_identity:
        raise Error("paseo-process-changed")
    return value


def matches_role(args, role):
    title = b"Paseo Supervisor" if role == "supervisor" else b"Paseo Daemon"
    if args and args[0].strip() == title:
        return True
    return any(b"/@getpaseo/server/" in x and
               (b"supervisor-entrypoint." in x if role == "supervisor" else
                b"supervisor" not in x and x.endswith((b".js", b".ts", b".mjs"))) for x in args)


def snapshot(binary, home, expected, root=None):
    root = PROC if root is None else root
    observed = status(binary, home)
    result = {"running": observed["localDaemon"] != "stopped", "inspection": "PASS",
              "environment": "PASS", "processes": [], "identities": {}, "ready": False}
    if not result["running"]:
        return result
    try:
        pid = observed["pid"]
        sid = identity(root, pid)
        if not matches_role(argv(root, pid, sid), "supervisor"):
            raise Error("paseo-supervisor-identity-unverified")
        candidates = []
        reported = observed.get("workerPid")
        if reported is not None and (type(reported) is not int or reported <= 1):
            raise Error("paseo-worker-identity-unverified")
        for entry in root.iterdir():
            if not entry.name.isdigit():
                continue
            child = int(entry.name)
            selected_child = child == reported
            try:
                owner, parent = d.read_status(root, child)
                if parent != pid or owner != os.getuid():
                    continue
                selected_child = True
                cid = identity(root, child)
                args = argv(root, child, cid)
                if matches_role(args, "worker"):
                    candidates.append((child, cid))
            except (d.DiagnosticError, OSError):
                if selected_child and entry.exists():
                    raise Error("paseo-worker-inspection-incomplete") from None
        if len(candidates) != 1 or (reported is not None and candidates[0][0] != reported):
            raise Error("paseo-worker-identity-unverified")
        for child, role, ident in [(pid, "supervisor", sid), (candidates[0][0], "worker", candidates[0][1])]:
            if identity(root, child) != ident:
                raise Error("paseo-process-changed")
            match = d.proxy_environment(d.read_environment(root, child), expected)
            if identity(root, child) != ident:
                raise Error("paseo-process-changed")
            result["identities"][child] = ident
            result["processes"].append({"pid": child, "role": role, "proxy_environment": match})
            if match["classification"] != "proxied":
                result["environment"] = "FAIL"
        fresh = status(binary, home)
        if fresh.get("pid") != pid or identity(root, pid) != sid:
            raise Error("paseo-process-changed")
        result["ready"] = fresh.get("localDaemon") == "running" and fresh.get("connectedDaemon") == "reachable"
    except (d.DiagnosticError, OSError):
        result["inspection"] = "UNVERIFIED"
    return result


def target_probe(url, port, proxy=None):
    env = a.clean_environment()
    args = ["curl", "--disable", "--head", "--globoff", "--proto", "=https", "--silent", "--show-error",
            "--noproxy", "" if proxy else "*", "--max-time", "5", "--output", os.devnull,
            "--write-out", "%{http_code}\t%{http_connect}\t%{remote_ip}\t%{remote_port}\t%{time_total}", url]
    if proxy:
        env["https_proxy"] = proxy
    proc = a.run_command(args, 7, env)
    row = {"target": urlsplit(url).hostname, "path": "listener" if proxy else "direct",
           "status": "UNVERIFIED", "tls": "UNVERIFIED"}
    if proc is None:
        return row
    fields = proc.stdout.strip().split("\t")
    if (len(fields) != 5 or not all(re.fullmatch(r"\d{3}", x) for x in fields[:2])
            or not fields[3].isdigit() or not re.fullmatch(r"\d+(?:\.\d+)?", fields[4])):
        return row
    http, connect = int(fields[0]), int(fields[1])
    peer = fields[2] == "127.0.0.1" and int(fields[3]) == port
    reached = proc.returncode == 0 and 100 <= http <= 599 and http != 407
    row.update(http=http, connect=connect, curl_rc=proc.returncode, seconds=float(fields[4]),
               peer="listener" if peer else "other", tls="PASS" if reached else "UNVERIFIED")
    if proxy:
        row["status"] = "PASS" if reached and peer and connect == 200 else "FAIL"
    else:
        row["status"] = "PASS" if reached and not peer else "FAIL"
    return row


def network(expected):
    try:
        port = int(os.environ["MIHOMO_PORT"])
        service = os.environ["MIHOMO_SERVICE"]
        url = os.environ["MIHOMO_READY_URL"]
        if not 1024 <= port <= 65535 or not re.fullmatch(r"[A-Za-z0-9_.@-]+", service) or not a.public_https_url(url):
            raise ValueError
        for key, scheme in (("HTTP_PROXY", "http"), ("HTTPS_PROXY", "http"), ("ALL_PROXY", "socks5h")):
            parsed = urlsplit(expected[key])
            if (parsed.scheme != scheme or parsed.hostname != "127.0.0.1" or parsed.port != port
                    or not parsed.username or not parsed.password or parsed.path not in ("", "/")
                    or parsed.query or parsed.fragment):
                raise ValueError
    except (ValueError, KeyError):
        raise Error("configuration-or-credentials-invalid") from None
    checks = [a.service_active_check(service, 5), a.listener_check(port, 5)]
    targets = []
    if all(x.status == "PASS" for x in checks):
        checks += [a.http_no_auth(url, port, 5), a.socks_no_auth(port, 5),
                   a.curl_check("http-auth", url, port, 5, None, expected["HTTPS_PROXY"])]
        if all(x.status == "PASS" for x in checks):
            for target in TARGETS:
                targets.extend([target_probe(target, port), target_probe(target, port, expected["HTTPS_PROXY"])])
    states = [x.status for x in checks] + [x["status"] for x in targets if x["path"] == "listener"]
    state = d.combine_status(states)
    return state, [{"name": x.check, "status": x.status, "evidence": x.evidence} for x in checks], targets


def public_snapshot(value):
    return {k: v for k, v in value.items() if k != "identities"}


def preflight(binary, home, expected, pending):
    state, checks, targets = network(expected)
    daemon = snapshot(binary, home, expected)
    state = d.combine_status([state, daemon["inspection"], daemon["environment"]])
    if daemon["running"] and not daemon["ready"] and state == "PASS":
        state = "UNVERIFIED"
    overall = {"PASS": "SAFE_TO_LAUNCH", "FAIL": "BLOCKED", "UNVERIFIED": "UNVERIFIED"}[state]
    reasons = []
    if daemon["environment"] == "FAIL":
        reasons.append("daemon-proxy-environment-drift; run mihomoctl paseo restart in a maintenance window")
    if daemon["inspection"] != "PASS":
        reasons.append("daemon-inspection-incomplete")
    if overall != "SAFE_TO_LAUNCH" and not reasons:
        reasons.append("proxy-or-daemon-not-ready")
    direct = [x for x in targets if x["path"] == "direct"]
    necessity = "DEMONSTRATED" if any(x["status"] == "FAIL" and x.get("http") == 0 for x in direct) else "NOT_DEMONSTRATED"
    payload = {"launch_safe": overall == "SAFE_TO_LAUNCH", "checks": checks, "targets": targets,
               "daemon": public_snapshot(daemon), "reasons": reasons, "injection_necessity": necessity,
               "pending_direct_domains": pending, "model_request": "UNVERIFIED", "remote_transport": "UNVERIFIED"}
    return overall, payload, daemon


def report(action, overall, payload, json_output=False):
    if json_output:
        d.emit_json("paseo-" + action, overall, payload)
    else:
        print(overall)
        for reason in payload.get("reasons", []):
            print(reason)
        for row in payload.get("daemon", {}).get("processes", []):
            print("pid={} role={} environment={}".format(row["pid"], row["role"], row["proxy_environment"]["classification"]))
        for row in payload.get("targets", []):
            print("{} {} {} http={} connect={} peer={}".format(row["path"], row["target"], row["status"],
                  row.get("http", "unknown"), row.get("connect", "unknown"), row.get("peer", "unknown")))
        if payload.get("pending_direct_domains"):
            print("Configure direct_domains if direct access is intended: " + ",".join(payload["pending_direct_domains"]))
    return {"SAFE_TO_LAUNCH": 0, "BLOCKED": 1, "UNVERIFIED": 2}[overall]


def owned_directory(path):
    if not path.is_absolute():
        raise Error("paseo-directory-must-be-absolute")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise Error("unsafe-paseo-directory")
        if ancestor.exists():
            info = ancestor.stat()
            if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise Error("unsafe-paseo-directory")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
        raise Error("unsafe-paseo-directory")


@contextlib.contextmanager
def lifecycle_lock(home):
    root = Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "mihomo-userctl"
    owned_directory(root)
    name = hashlib.sha256(str(home).encode()).hexdigest()[:24]
    fd = os.open(root / ("paseo-" + name + ".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600 or not stat.S_ISREG(info.st_mode):
            raise Error("unsafe-paseo-lock")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error("paseo-operation-in-progress") from None
        yield
    finally:
        os.close(fd)


def same_process(pid, ident):
    try:
        return identity(PROC, pid) == ident and (PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except (d.DiagnosticError, OSError):
        if (PROC / str(pid)).exists():
            raise Error("paseo-process-exit-unverified") from None
        return False


def stop(binary, home, daemon):
    current = status(binary, home)
    if current.get("pid") not in daemon["identities"] or not all(same_process(p, i) for p, i in daemon["identities"].items()):
        raise Error("paseo-process-changed")
    result = command(binary, home, "stop", "--timeout", "15", timeout=20)
    if result is None or result.returncode:
        raise Error("paseo-stop-not-confirmed")
    deadline = time.monotonic() + 3
    while any(same_process(p, i) for p, i in daemon["identities"].items()):
        if time.monotonic() >= deadline:
            raise Error("paseo-stop-not-confirmed")
        time.sleep(0.1)
    if status(binary, home)["localDaemon"] != "stopped":
        raise Error("paseo-replaced-after-stop")


def wait_ready(binary, home, expected, old=None, child=None):
    deadline = time.monotonic() + START_TIMEOUT
    while time.monotonic() < deadline:
        if child is not None and child.poll() is not None:
            raise Error("paseo-foreground-exited")
        daemon = snapshot(binary, home, expected)
        if daemon["running"] and daemon["inspection"] == "PASS" and daemon["ready"]:
            if child is not None:
                # daemon run must own the supervisor; an externally started instance is not ours.
                supervisor = next(x["pid"] for x in daemon["processes"] if x["role"] == "supervisor")
                current, seen = supervisor, set()
                while current > 1 and current != child.pid and current not in seen:
                    seen.add(current)
                    current = identity(PROC, current)[0]
                if current != child.pid:
                    raise Error("paseo-foreground-supervisor-not-owned")
            if daemon["environment"] != "PASS":
                raise Error("paseo-new-environment-mismatch")
            if old and set(old["identities"].items()) & set(daemon["identities"].items()):
                raise Error("paseo-old-process-retained")
            state, _, _ = network(expected)
            if state != "PASS":
                raise Error("paseo-post-start-probe-failed")
            return daemon
        time.sleep(0.25)
    raise Error("paseo-start-not-verified")


def unit_path():
    return config_home() / "systemd/user/paseo.service"


def unit_quote(value, exec_arg=False):
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise Error("unit-value-invalid")
    value = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    if exec_arg:
        value = value.replace("$", "$$")
    return '"' + value + '"'


def unit_text(binary, home):
    if os.environ.get("OPENCODE_CONFIG_CONTENT"):
        raise Error("unit-requires-file-based-opencode-config")
    ctl = os.environ.get("MIHOMO_USERCTL_BIN") or shutil.which("mihomoctl")
    if not ctl or not Path(ctl).is_absolute():
        raise Error("stable-mihomoctl-path-required")
    service = os.environ["MIHOMO_SERVICE"]
    if not service.endswith(".service"):
        service += ".service"
    args = " ".join(unit_quote(x, True) for x in (ctl, "paseo", "run", "--home", str(home), "--binary", binary))
    stop_args = " ".join(unit_quote(x, True) for x in (binary, "daemon", "stop", "--home", str(home), "--timeout", "15"))
    env = ["PATH=" + os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "XDG_CONFIG_HOME=" + str(config_home())]
    for key in ("MIHOMO_USERCTL_CONFIG", "MIHOMO_USERCTL_CREDENTIALS", "OPENCODE_CONFIG", "XDG_STATE_HOME"):
        if os.environ.get(key):
            env.append(key + "=" + os.environ[key])
    return (MARKER + "\n# home=" + str(home) + "\n[Unit]\nDescription=Paseo with validated per-process Mihomo proxy\n"
            "Requires=" + service + "\nAfter=" + service + "\nStartLimitIntervalSec=0\n\n[Service]\nType=simple\n"
            "Environment=" + " ".join(unit_quote(x) for x in env) + "\nExecStart=" + args + "\nExecStop=" + stop_args + "\n"
            "Restart=on-failure\nRestartSec=10\nTimeoutStopSec=30\nKillMode=control-group\n\n[Install]\nWantedBy=default.target\n")


def managed_unit(home, strict=False):
    path = unit_path()
    if not path.exists() and not path.is_symlink():
        return False
    text = private_file(path)
    if not text.startswith(MARKER + "\n# home="):
        raise Error("paseo-unit-not-managed-for-this-home")
    if not text.startswith(MARKER + "\n# home=" + str(home) + "\n"):
        if strict:
            raise Error("paseo-unit-not-managed-for-this-home")
        return False
    return True


def unit_owns_daemon(daemon):
    result = a.run_command(["systemctl", "--user", "show", "paseo.service", "--property=ControlGroup", "--value"], 5)
    group = result.stdout.strip() if result is not None and result.returncode == 0 else ""
    if not group.startswith("/") or group == "/" or "\n" in group:
        return False
    for row in daemon["processes"]:
        pid = row["pid"]
        if identity(PROC, pid) != daemon["identities"][pid]:
            return False
        entries = (PROC / str(pid) / "cgroup").read_text().splitlines()
        if not any(line.rsplit(":", 1)[-1] == group or line.rsplit(":", 1)[-1].startswith(group + "/") for line in entries):
            return False
        if identity(PROC, pid) != daemon["identities"][pid]:
            return False
    return True


def install_unit(binary, home, dry_run):
    text = unit_text(binary, home)
    if dry_run:
        print(text, end="")
        return 0
    owned_directory(unit_path().parent)
    if unit_path().exists() or unit_path().is_symlink():
        managed_unit(home, strict=True)
        if private_file(unit_path()) == text:
            result = a.run_command(["systemctl", "--user", "daemon-reload"], 10)
            if result is None or result.returncode:
                raise Error("paseo-unit-written-daemon-reload-failed")
            return 0
    fd, temporary = tempfile.mkstemp(prefix=".paseo-", dir=unit_path().parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, unit_path())
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    result = a.run_command(["systemctl", "--user", "daemon-reload"], 10)
    if result is None or result.returncode:
        raise Error("paseo-unit-written-daemon-reload-failed")
    print("Installed paseo.service; not enabled or started. Activate manually in a maintenance window.")
    return 0


def foreground(binary, home, expected):
    env = launch_environment(expected, home)
    child = subprocess.Popen([binary, "daemon", "run", "--home", str(home)], env=env,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    previous = {}
    stopping = False

    def shutdown(_signum, _frame):
        nonlocal stopping
        if not stopping:
            stopping = True
            # CLI run handles signals for its own spawned supervisor. Never stop a replacement home.
            if child.poll() is None:
                child.send_signal(signal.SIGTERM)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous[signum] = signal.signal(signum, shutdown)
        wait_ready(binary, home, expected, child=child)
        return child, previous, shutdown
    except BaseException:
        shutdown(None, None)
        try:
            child.wait(timeout=25)
        except subprocess.TimeoutExpired:
            pass  # No forced cleanup; systemd owns its cgroup in managed deployments.
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        raise


def doctor(binary, home, expected, offline):
    daemon = snapshot(binary, home, expected)
    result = {"status": "PASS", "reason": "daemon-environment-current", "daemon": public_snapshot(daemon),
              "dependency_evidence": "configuration-only" if offline else "configuration-and-network"}
    if not daemon["running"]:
        result.update(status="SKIPPED", reason="daemon-not-running")
        return result
    cfg = home / "config.json"
    value = jsonc(private_file(cfg)) if cfg.exists() or cfg.is_symlink() else {}
    if not isinstance(value, dict) or not isinstance(value.get("agents", {}), dict):
        raise Error("paseo-provider-config-invalid")
    providers = value.get("agents", {}).get("providers", {})
    if not isinstance(providers, dict):
        raise Error("paseo-provider-config-invalid")
    dependent = any((key == "codex" or value.get("extends") == "codex") and value.get("enabled") is not False
                    for key, value in {"codex": {}, **providers}.items() if isinstance(value, dict))
    if not dependent:
        result.update(status="SKIPPED", reason="no-configured-openai-provider-dependency")
    elif daemon["inspection"] != "PASS":
        result.update(status="UNVERIFIED", reason="daemon-inspection-incomplete")
    elif daemon["environment"] != "PASS":
        result.update(status="FAIL", reason="daemon-proxy-environment-drift; run mihomoctl paseo restart in a maintenance window")
        if not offline:
            result["targets"] = [target_probe(url, int(os.environ["MIHOMO_PORT"]), proxy)
                                 for url in TARGETS for proxy in (None, expected["HTTPS_PROXY"])]
    return result


def codex_context(root):
    """Only the selected, validated Paseo process tree gets the expanded bypass list."""
    binary = shutil.which("paseo")
    if not binary or not Path(binary).is_file():
        return None
    try:
        home = selected_home()
        expected, _ = proxy_environment()
        daemon = snapshot(binary, home, expected, root)
        if daemon["inspection"] == "PASS" and daemon["running"] and daemon["environment"] == "PASS":
            return daemon["identities"], expected
    except (d.DiagnosticError, OSError, ValueError):
        pass
    return None


def descendant_environment(root, pid, context, default):
    if context is None:
        return default
    identities, expected = context
    seen = set()
    current = pid
    try:
        while current > 1 and current not in seen:
            seen.add(current)
            parent, ticks = identity(root, current)
            if current in identities:
                return expected if identities[current] == (parent, ticks) else default
            current = parent
    except (d.DiagnosticError, OSError):
        pass
    return default


def parser():
    root = d.Parser(description=__doc__)
    root.add_argument("action", choices=("preflight", "exec", "start", "restart", "run", "install-unit", "doctor"))
    root.add_argument("--home")
    root.add_argument("--binary", help=argparse.SUPPRESS)
    root.add_argument("--json", action="store_true")
    root.add_argument("--offline", action="store_true")
    root.add_argument("--dry-run", action="store_true")
    return root


def main(argv=None):
    values = list(sys.argv[1:] if argv is None else argv)
    action = values[0] if values and values[0] in ("preflight", "exec", "start", "restart", "run", "install-unit", "doctor") else "preflight"
    json_output = "--json" in values
    child = None
    previous = {}
    try:
        child_args = None
        if "--" in values:
            index = values.index("--")
            child_args, values = values[index + 1:], values[:index]
        args = parser().parse_args(values)
        if ((args.action == "exec") != (child_args is not None) or child_args == []
                or (args.dry_run and args.action != "install-unit")
                or (args.offline and args.action != "doctor")
                or (args.json and args.action not in ("preflight", "doctor"))):
            raise Error("invalid-options")
        home = selected_home(args.home)
        binary = executable(args.binary)
        expected, pending = proxy_environment()
        if args.action == "doctor":
            result = doctor(binary, home, expected, args.offline)
            print(json.dumps(result, sort_keys=True))
            return {"PASS": 0, "SKIPPED": 0, "FAIL": 1, "UNVERIFIED": 2}[result["status"]]
        if args.action == "install-unit":
            if args.dry_run:
                return install_unit(binary, home, True)
            with lifecycle_lock(home):
                return install_unit(binary, home, args.dry_run)
        if args.action in ("preflight", "exec"):
            overall, payload, _ = preflight(binary, home, expected, pending)
            if args.action == "exec" and overall == "SAFE_TO_LAUNCH":
                os.execvpe(child_args[0], child_args, launch_environment(expected, home))
            return report(args.action, overall, payload, args.json)
        with lifecycle_lock(home):
            state, _, _ = network(expected)
            if state != "PASS":
                return report(args.action, "UNVERIFIED" if state == "UNVERIFIED" else "BLOCKED",
                              {"reasons": ["proxy-not-ready; daemon not changed"]})
            daemon = snapshot(binary, home, expected)
            if daemon["inspection"] != "PASS":
                raise Error("daemon-inspection-incomplete; daemon not changed")
            if args.action != "restart" and daemon["running"]:
                if args.action == "run" or daemon["environment"] != "PASS" or not daemon["ready"]:
                    return report(args.action, "BLOCKED", {"reasons": ["daemon-already-running-or-drifted; use mihomoctl paseo restart in a maintenance window"]})
                return 0
            unit = managed_unit(home)
            if unit and args.action != "run":
                # Do not race systemd's Restart= policy by manually replacing its supervisor.
                if daemon["running"]:
                    if not unit_owns_daemon(daemon):
                        raise Error("unmanaged-daemon-running; migrate to paseo.service manually")
                pass  # Invoke systemd after releasing the lock needed by its run wrapper.
            elif args.action == "run":
                child, previous, _ = foreground(binary, home, expected)
            else:
                if daemon["running"]:
                    stop(binary, home, daemon)
                result = command(binary, home, "start", "--timeout", str(START_TIMEOUT),
                                 env=launch_environment(expected, home), timeout=START_TIMEOUT + 5)
                if result is None or result.returncode:
                    raise Error("paseo-start-failed")
                wait_ready(binary, home, expected, old=daemon)
                return 0
        if child is not None:
            code = child.wait()
            return code if code >= 0 else 128 - code
        result = a.run_command(["systemctl", "--user", args.action, "paseo.service"], 30)
        if result is None or result.returncode:
            raise Error("paseo-systemd-operation-failed")
        verified = wait_ready(binary, home, expected, old=daemon if args.action == "restart" else None)
        if not unit_owns_daemon(verified):
            raise Error("paseo-new-unit-process-ownership-unverified")
        return 0
    except (d.DiagnosticError, OSError, ValueError) as exc:
        code = exc.code if isinstance(exc, d.DiagnosticError) else "paseo-runtime-error"
        if action == "doctor":
            result = {"status": "SKIPPED" if code == "paseo-not-on-path" else "UNVERIFIED", "reason": code}
            print(json.dumps(result))
            return 0 if result["status"] == "SKIPPED" else 2
        return report(action, "UNVERIFIED", {"launch_safe": False, "reasons": [code], "model_request": "UNVERIFIED"}, json_output)
    finally:
        for signum, handler in previous.items():
            signal.signal(signum, handler)


if __name__ == "__main__":
    sys.exit(main())
