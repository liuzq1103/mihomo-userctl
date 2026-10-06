#!/usr/bin/env python3
"""Per-user Mihomo controller. No daemon, global proxy or shell evaluation."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import zipfile
from urllib.parse import quote, urlencode

try:
    from . import acceptance, install_support as files
except ImportError:
    import acceptance
    import install_support as files

SCHEMA = "mihomo-userctl.controller/v1"
COMMANDS = ("controller", "nodes", "groups", "select", "latency", "connections", "traffic", "ui", "dashboard", "tui")
LIMIT = 8 * 1024 * 1024
TEST_URL = "https://www.gstatic.com/generate_204"


class ControlError(Exception):
    def __init__(self, code, rc=2):
        self.code, self.rc = code, rc
        super().__init__(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ControlError("invalid-options")


def private(path, directory=False):
    path = files.safe_path(path, directory)
    info = path.stat()
    if (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != (0o700 if directory else 0o600)
            or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))):
        raise ControlError("controller-path-must-be-private-owned-regular")
    return path


def read_config(path):
    try:
        import yaml
    except ImportError:
        raise ControlError("controller-requires-PyYAML-see-control-plane-guide") from None
    private(path)
    if path.stat().st_size > LIMIT:
        raise ControlError("config-too-large")
    text = path.read_text(encoding="utf-8")
    try:
        # Reject ambiguous merges, aliases and duplicate keys before any edit.
        if any(isinstance(t, (yaml.tokens.AnchorToken, yaml.tokens.AliasToken, yaml.tokens.DocumentEndToken)) for t in yaml.scan(text)):
            raise ControlError("config-anchors-or-document-end-not-supported")
        node = yaml.compose(text, Loader=yaml.SafeLoader)
        def check(n):
            if isinstance(n, yaml.MappingNode):
                names = []
                for key, value in n.value:
                    if not isinstance(key, yaml.ScalarNode) or key.value in names or key.value == "<<":
                        raise ControlError("config-duplicate-or-complex-key")
                    names.append(key.value)
                    check(value)
            elif isinstance(n, yaml.SequenceNode):
                for child in n.value:
                    check(child)
        check(node)
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or not isinstance(node, yaml.MappingNode):
            raise ControlError("config-must-be-mapping")
        return text, data, node
    except (yaml.YAMLError, RecursionError):
        raise ControlError("config-yaml-invalid") from None


def patch_config(text, node, changes):
    # Replace whole top-level entries using parser marks; preserve other bytes.
    if node.flow_style:
        raise ControlError("config-needs-block-style-root")
    lines = text.splitlines(keepends=True)
    edits = []
    for key, value in node.value:
        if key.value in changes:
            end = value.end_mark.line + (1 if value.end_mark.column else 0)
            edits.append((key.start_mark.line, end))
    for start, end in sorted(edits, reverse=True):
        del lines[start:end]
    result = "".join(lines).rstrip() + "\n"
    # JSON scalars/containers are a YAML subset; no secret interpolation.
    return result + "".join(k + ": " + json.dumps(v, ensure_ascii=False) + "\n" for k, v in changes.items())


def endpoint(data):
    match = re.fullmatch(r"127\.0\.0\.1:([0-9]{1,5})", str(data.get("external-controller", "")))
    token = data.get("secret")
    if not match or not 1024 <= int(match[1]) <= 65535:
        raise ControlError("controller-not-configured-as-loopback")
    if not isinstance(token, str) or not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        raise ControlError("controller-secret-must-be-32-to-256-url-safe-characters")
    if any(data.get(k) for k in ("external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-doh-server")):
        raise ControlError("additional-controller-listeners-not-supported")
    return int(match[1]), token


class Client:
    def __init__(self, port, token):
        self.port, self.token = port, token

    def request(self, path, method="GET", body=None, anonymous=False, stream=False):
        # http.client ignores all proxy variables and never follows redirects.
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=8)
        headers = {} if anonymous else {"Authorization": "Bearer " + self.token}
        if body is not None:
            headers["Content-Type"] = "application/json"
        try:
            connection.request(method, path, None if body is None else json.dumps(body).encode(), headers)
            response = connection.getresponse()
            if anonymous:
                if response.status != 401:
                    raise ControlError("controller-authentication-not-enforced", 1)
                return None
            if response.status == 401:
                raise ControlError("controller-authentication-failed", 1)
            if response.status not in (200, 204):
                raise ControlError("controller-request-failed", 1)
            raw = response.readline(LIMIT + 1) if stream else response.read(LIMIT + 1)
            if len(raw) > LIMIT:
                raise ControlError("controller-response-too-large")
            value = json.loads(raw) if raw else {}
            if not isinstance(value, dict):
                raise ControlError("controller-response-invalid")
            return value
        except (OSError, http.client.HTTPException):
            raise ControlError("controller-unreachable", 1) from None
        except (ValueError, UnicodeError):
            raise ControlError("controller-response-invalid") from None
        finally:
            connection.close()

    def verify(self):
        binding = acceptance.listener_check(self.port, 5)
        if binding.status != "PASS":
            raise ControlError("controller-" + binding.evidence, 1 if binding.status == "FAIL" else 2)
        # Check kernel socket UID before sending the bearer credential. This is
        # a snapshot, not protection against root or a same-UID adversary.
        owned = []
        for line in Path("/proc/net/tcp").read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) >= 8 and fields[3] == "0A" and fields[1] == "0100007F:{:04X}".format(self.port):
                owned.append(int(fields[7]))
        if not owned or any(uid != os.getuid() for uid in owned):
            raise ControlError("controller-listener-not-owned-by-current-user")
        self.request("/version", anonymous=True)
        self.request("/version")


def label(value):
    if not isinstance(value, str) or len(value) > 512 or any(unicodedata.category(c) in ("Cc", "Cf") for c in value):
        raise ControlError("controller-response-invalid-label")
    return value


def number(value):
    if type(value) not in (int, float) or not 0 <= value <= 2 ** 63:
        raise ControlError("controller-response-invalid-number")
    return value


def proxies(client):
    raw = client.request("/proxies").get("proxies")
    if not isinstance(raw, dict):
        raise ControlError("controller-proxies-invalid")
    result = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise ControlError("controller-proxies-invalid")
        row = {"name": label(name), "type": label(item.get("type", "unknown"))}
        if "all" in item:
            if not isinstance(item["all"], list):
                raise ControlError("controller-proxies-invalid")
            row["members"] = [label(n) for n in item["all"]]
            row["selected"] = label(item["now"]) if item.get("now") else None
            row["selectable"] = row["type"] == "Selector"
        result[name] = row
    return result


def select(client, group, node):
    rows = proxies(client)
    if group not in rows or not rows[group].get("selectable"):
        raise ControlError("selection-requires-Selector-group", 1)
    if node not in rows[group]["members"]:
        raise ControlError("node-not-in-group", 1)
    client.request("/proxies/" + quote(group, safe=""), "PUT", {"name": node})
    if proxies(client).get(group, {}).get("selected") != node:
        raise ControlError("selection-not-confirmed", 1)
    return {"group": group, "selected": node, "existing_connections": "unchanged"}


def snapshot(client, command):
    if command in ("nodes", "groups"):
        rows = proxies(client)
        return {command: [row for row in rows.values() if ("members" in row) == (command == "groups")]}
    if command == "traffic":
        raw = client.request("/traffic", stream=True)
        return {k: number(raw.get(k, 0)) for k in ("up", "down", "upTotal", "downTotal")}
    raw = client.request("/connections")
    connections = raw.get("connections") or []
    if not isinstance(connections, list):
        raise ControlError("controller-connections-invalid")
    # Deliberately omit hosts, IPs, process paths, argv and rule payloads.
    rows = []
    for item in connections:
        if not isinstance(item, dict) or not isinstance(item.get("chains", []), list):
            raise ControlError("controller-connections-invalid")
        rows.append({"chains": [label(n) for n in item.get("chains", [])],
                     "rule": label(item.get("rule", "")),
                     "upload": number(item.get("upload", 0)), "download": number(item.get("download", 0))})
    return {"connections": rows, "uploadTotal": number(raw.get("uploadTotal", 0)),
            "downloadTotal": number(raw.get("downloadTotal", 0))}


def choose_port(requested):
    if requested is not None and not 1024 <= requested <= 65535:
        raise ControlError("controller-port-out-of-range")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", requested or 0))
        except OSError:
            raise ControlError("controller-port-in-use", 1) from None
        return probe.getsockname()[1]


def archive_ui(archive, checksum, destination):
    if not checksum or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ControlError("dashboard-requires-pinned-sha256")
    if archive.is_symlink() or archive.stat().st_size > 32 * 1024 * 1024:
        raise ControlError("dashboard-archive-invalid")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise ControlError("dashboard-sha256-mismatch")
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        roots = [e.filename[:-10] for e in entries if e.filename.endswith("index.html")]
        if len(roots) != 1 or len(entries) > 10000:
            raise ControlError("dashboard-archive-needs-one-index-html")
        root, used, seen = roots[0], 0, set()
        for entry in entries:
            name = entry.filename
            if (name.startswith("/") or "\\" in name or ":" in name or ".." in Path(name).parts
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR) or name in seen):
                raise ControlError("dashboard-archive-unsafe-path")
            seen.add(name)
            used += entry.file_size
            if used > 64 * 1024 * 1024:
                raise ControlError("dashboard-archive-too-large")
            if entry.is_dir() or not name.startswith(root):
                continue
            target = destination / name[len(root):]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with bundle.open(entry) as source:
                data = source.read(64 * 1024 * 1024 + 1)
            if len(data) != entry.file_size:
                raise ControlError("dashboard-archive-invalid-size")
            files.atomic_bytes(target, data)


def setup(args, config):
    text, data, tree = read_config(config)
    if data.get("external-controller"):
        endpoint(data)  # Never silently replace an exposed or unprotected API.
    home = Path(args.home_dir or os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    if not args.home_dir:
        home /= "mihomo"
    private(home, True)
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if not core:
        raise ControlError("mihomo-executable-missing")
    if args.archive is None and data.get("external-ui"):
        raise ControlError("existing-dashboard-preserved-use-explicit-archive-to-replace")
    port = choose_port(args.port)
    if port in (data.get("mixed-port"), data.get("port"), data.get("socks-port")):
        raise ControlError("controller-port-conflicts-with-proxy")
    token = data.get("secret") if data.get("external-controller") else secrets.token_urlsafe(32)
    ui = Path(tempfile.mkdtemp(prefix="userctl-ui-", dir=home))
    candidate = None
    committed = False
    try:
        if args.archive:
            archive_ui(Path(args.archive), args.sha256, ui)
        else:
            bundled = Path(__file__).with_name("dashboard.html")
            files.atomic_bytes(ui / "index.html", bundled.read_bytes())
        changes = {"external-controller": "127.0.0.1:" + str(port), "secret": token,
                   "external-ui": str(ui), "external-ui-name": "", "external-ui-url": "",
                   "external-controller-cors": {"allow-origins": [], "allow-private-network": False}}
        if any(data.get(k) for k in ("external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-doh-server")):
            raise ControlError("additional-controller-listeners-not-supported")
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            raise ControlError("config-profile-invalid")
        changes["profile"] = dict(profile, **{"store-selected": True})
        updated = patch_config(text, tree, changes).encode()
        fd, name = tempfile.mkstemp(prefix="controller-check-", suffix=".yaml", dir=config.parent)
        os.close(fd)
        candidate = Path(name)
        files.atomic_bytes(candidate, updated)
        process = subprocess.run([core, "-t", "-d", str(home), "-f", str(candidate)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=acceptance.clean_environment(), timeout=30)
        if process.returncode:
            raise ControlError("mihomo-config-validation-failed", 1)
        private(config)
        if config.read_text(encoding="utf-8") != text:
            raise ControlError("config-changed-during-setup")
        backup = config.with_name(config.name + ".before-controller-" + secrets.token_hex(8))
        files.atomic_bytes(backup, text.encode())
        files.atomic_bytes(config, updated)
        committed = True
        return {"endpoint": "127.0.0.1:" + str(port), "backup": str(backup),
                "state": "restart-required", "service": "unchanged", "ui": "external" if args.archive else "bundled"}
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        # A directory fsync can fail after os.replace has committed the file.
        # Do not remove assets that the active config already references.
        if not committed and not (candidate is not None and config.read_bytes() == updated):
            shutil.rmtree(ui)


def plain_tui(client):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    while True:
        groups = list(snapshot(client, "groups")["groups"])
        print("\nMihomo · 策略组 / Groups (q: quit, Enter: refresh)")
        for i, group in enumerate(groups, 1):
            print("{}. {} [{}] → {}".format(i, group["name"], group["type"], group["selected"] or "dynamic"))
        answer = input("选择策略组 / Group: ").strip()
        if answer.lower() == "q":
            return {"state": "closed"}
        if not answer.isdigit() or not 1 <= int(answer) <= len(groups):
            continue
        group = groups[int(answer) - 1]
        if not group["selectable"]:
            print("自动/负载均衡组只读；请选择 Selector。 / Automatic group is read-only.")
            continue
        for i, name in enumerate(group["members"], 1):
            print("{}. {}{}".format(i, name, " ✓" if name == group["selected"] else ""))
        answer = input("切换到 / Select (Enter: cancel): ").strip()
        if answer.isdigit() and 1 <= int(answer) <= len(group["members"]):
            select(client, group["name"], group["members"][int(answer) - 1])
            print("已确认切换；已有连接不强制断开。 / Selection confirmed; existing connections unchanged.")


def tui(client, plain=False):
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-requires-interactive-terminal")
    if plain:
        return plain_tui(client)
    try:
        import curses
    except ImportError:
        raise ControlError("curses-unavailable-use-tui-plain") from None

    def screen(window):
        curses.curs_set(0)
        window.keypad(True)
        window.timeout(1000)
        groups, group_index, node_index, focus = [], 0, 0, 0
        note, detail = "", []
        last_refresh = 0
        def put(y, x, value, width, attr=0):
            # Curses counts terminal cells; avoid splitting wide node names.
            text, used = "", 0
            for char in value:
                size = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
                if used + size >= width:
                    break
                text += char; used += size
            try:
                window.addstr(y, x, text, attr)
            except curses.error:
                pass  # A resize may happen between getmaxyx and drawing.

        while True:
            if time.monotonic() - last_refresh >= 5:
                try:
                    groups = snapshot(client, "groups")["groups"]
                    group_index = min(group_index, max(0, len(groups)-1))
                    note = "已刷新 / Refreshed " + time.strftime("%H:%M:%S")
                except ControlError as error:
                    note = "UNVERIFIED: " + error.code
                last_refresh = time.monotonic()
            height, width = window.getmaxyx()
            window.erase()
            if height < 14 or width < 60:
                put(0, 0, "Terminal too small; resize to 60x14 or use tui --plain. q: quit", width)
                window.refresh()
                if window.getch() in (ord('q'), 27): return
                continue
            middle = width // 2
            group = groups[group_index] if groups else None
            members = group.get("members", []) if group else []
            node_index = min(node_index, max(0, len(members)-1))
            put(0, 1, "MIHOMO · 我的节点 / My nodes", width-2, curses.A_BOLD)
            put(1, 1, "SSH 直接操作 · no port forwarding · existing connections unchanged", width-2)
            put(3, 1, "策略组 / Groups", middle-2, curses.A_BOLD)
            put(3, middle, "节点 / Nodes  [*] current selection", width-middle-1, curses.A_BOLD)
            available = max(1, height-11)
            start = max(0, group_index-available+1)
            for index in range(start, min(len(groups), start+available)):
                row = groups[index]
                put(4+index-start, 1, row["name"]+" ["+row["type"]+"]", middle-2,
                    curses.A_REVERSE if index == group_index and focus == 0 else curses.A_NORMAL)
            start = max(0, node_index-available+1)
            for index in range(start, min(len(members), start+available)):
                name = members[index]
                put(4+index-start, middle, ("[*] " if group.get("selected") == name else "[ ] ")+name,
                    width-middle-1, curses.A_REVERSE if index == node_index and focus == 1 else curses.A_NORMAL)
            put(height-6, 1, "当前 / Current: " + (group.get("selected") or "dynamic") if group else "No groups", width-2)
            put(height-5, 1, note, width-2)
            for index, line in enumerate(detail[:2]):
                put(height-4+index, 1, line, width-2)
            put(height-2, 1, "↑↓ browse  Tab/←→ pane  Enter select  r refresh  t latency  c chains  f traffic  q quit", width-2)
            window.refresh()
            key = window.getch()
            if key in (ord('q'), 27): return
            if key in (9, curses.KEY_LEFT, curses.KEY_RIGHT): focus = 1-focus
            elif key in (curses.KEY_UP, curses.KEY_DOWN):
                step = -1 if key == curses.KEY_UP else 1
                if focus == 0:
                    group_index = max(0, min(len(groups)-1, group_index+step)); node_index = 0
                else:
                    node_index = max(0, min(len(members)-1, node_index+step))
            elif key == ord('r'): last_refresh = 0
            elif key in (10, 13, curses.KEY_ENTER, ord('t'), ord('c'), ord('f')):
                if key in (10, 13, curses.KEY_ENTER) and focus == 0:
                    focus = 1
                    if group and group.get("selected") in members:
                        node_index = members.index(group["selected"])
                    continue
                try:
                    if key == ord('c'):
                        rows = snapshot(client, "connections")["connections"]
                        detail = [" ← ".join(row["chains"]) for row in rows[:2]] or ["No active connections"]
                        note = "Active chains (first 2); use mihomoctl connections for all."
                    elif key == ord('f'):
                        values = snapshot(client, "traffic")
                        detail = ["↑ {} B/s   ↓ {} B/s".format(values["up"], values["down"])]
                    elif group and members:
                        if key == ord('t'):
                            name = members[node_index]
                            note = "Testing public HTTPS target..."; put(height-5, 1, note, width-2); window.refresh()
                            raw = client.request("/proxies/"+quote(name, safe="")+"/delay?"+urlencode({"url": TEST_URL,"timeout":5000}))
                            detail = [name+": "+str(number(raw.get("delay")))+" ms; model UNVERIFIED"]
                        else:
                            select(client, group["name"], members[node_index])
                            groups = snapshot(client, "groups")["groups"]
                            note = "已确认切换 / Selection confirmed; existing connections unchanged"
                        last_refresh = time.monotonic()
                except ControlError as error:
                    note = "FAIL: " + error.code
    try:
        curses.wrapper(screen)
    except curses.error:
        raise ControlError("terminal-unavailable-use-tui-plain") from None
    return {"state": "closed"}


def main(argv=None):
    parser = Parser(description=__doc__)
    parser.add_argument("command", choices=COMMANDS)
    parser.add_argument("values", nargs="*")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--config")
    parser.add_argument("--home-dir")
    parser.add_argument("--port", type=int)
    parser.add_argument("--archive")
    parser.add_argument("--sha256")
    parser.add_argument("--plain", action="store_true", help="Use a numbered terminal menu instead of fullscreen TUI")
    args = parser.parse_args(argv)
    if args.plain and args.command != "tui":
        raise ControlError("plain-requires-tui")
    config = Path(args.config or str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mihomo/config.yaml"))
    setup_requested = args.command == "controller" and args.values == ["setup"]
    if not setup_requested and any(v is not None for v in (args.home_dir, args.port, args.archive, args.sha256)):
        raise ControlError("setup-options-require-controller-setup")
    if setup_requested:
        if bool(args.archive) != bool(args.sha256):
            raise ControlError("dashboard-requires-archive-and-sha256")
        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
            payload = setup(args, config)
    else:
        expected = 2 if args.command == "select" else 1 if args.command in ("controller", "latency") else 0
        if len(args.values) != expected:
            raise ControlError("invalid-options")
        if args.command == "controller" and args.values[0] not in ("status", "token"):
            raise ControlError("invalid-controller-command")
        _, data, _ = read_config(config)
        port, token = endpoint(data)
        if args.command == "controller" and args.values == ["token"]:
            if args.json or not sys.stdout.isatty():
                raise ControlError("token-display-requires-terminal-without-json")
            print(token)
            return 0
        client = Client(port, token)
        client.verify()
        if args.command in ("nodes", "groups", "connections", "traffic"):
            payload = snapshot(client, args.command)
        elif args.command == "select":
            payload = select(client, *args.values)
        elif args.command == "latency":
            if args.values[0] not in proxies(client):
                raise ControlError("unknown-node", 1)
            raw = client.request("/proxies/" + quote(args.values[0], safe="") + "/delay?" + urlencode({"url": TEST_URL, "timeout": 5000}))
            payload = {"name": args.values[0], "delay_ms": number(raw.get("delay")), "target": TEST_URL, "model_request": "UNVERIFIED"}
        elif args.command == "tui":
            if args.json:
                raise ControlError("tui-does-not-support-json")
            payload = tui(client, args.plain)
        elif args.command in ("ui", "dashboard"):
            if not data.get("external-ui"):
                raise ControlError("dashboard-not-configured")
            payload = {"url": "http://127.0.0.1:" + str(port) + "/ui/", "secret": "use-mihomoctl-controller-token-in-private-terminal",
                       "remote_access": "ssh -N -L LOCAL_PORT:127.0.0.1:" + str(port) + " USER@SERVER",
                       "remote_url": "http://127.0.0.1:LOCAL_PORT/ui/"}
        else:
            payload = {"endpoint": "127.0.0.1:" + str(port), "authentication": "PASS", "listener": "PASS"}
    document = {"schema": SCHEMA, "command": args.command, "overall": "PASS", **payload}
    if args.json:
        print(json.dumps(document, ensure_ascii=True, sort_keys=True))
    else:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ControlError, files.InstallError, OSError, ValueError, TypeError, KeyError,
            subprocess.TimeoutExpired, zipfile.BadZipFile, EOFError, KeyboardInterrupt) as error:
        code = error.code if isinstance(error, ControlError) else "controller-operation-failed"
        rc = error.rc if isinstance(error, ControlError) else 2
        command = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in COMMANDS else "controller"
        print(json.dumps({"schema": SCHEMA, "command": command, "overall": "FAIL" if rc == 1 else "UNVERIFIED",
                          "error": {"code": code}}))
        sys.exit(rc)
