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
COMMANDS = ("controller", "nodes", "groups", "select", "latency", "connections", "traffic", "ui", "dashboard", "tui", "override", "manual")
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


def snapshot(client, command, details=False):
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
        if details:
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ControlError("controller-connections-invalid")
            rows[-1]["host"] = label(metadata.get("host", ""))
            rows[-1]["rule_payload"] = label(item.get("rulePayload", ""))
    return {"connections": rows, "uploadTotal": number(raw.get("uploadTotal", 0)),
            "downloadTotal": number(raw.get("downloadTotal", 0))}


POLICY_KEYS = ("proxy-groups", "rules", "rule-providers")
# This executes a trusted user's script. Node vm is NOT a security sandbox.
OVERRIDE_RUNNER = r'''
const fs = require('fs'), vm = require('vm');
const config = JSON.parse(fs.readFileSync(0, 'utf8'));
let failed = false;
const context = vm.createContext({console: {log() {}, warn() {}, error() {failed = true;}}});
vm.runInContext(fs.readFileSync(process.argv[1], 'utf8'), context, {timeout: 3000});
context.input = config;
const result = vm.runInContext('main(input)', context, {timeout: 3000});
if (failed || !result || typeof result !== 'object' || Array.isArray(result)) process.exit(2);
process.stdout.write(JSON.stringify(result));
'''


def flclash_input(data, home_dir=None):
    """Adapt a provider-based server config to the user's desktop script contract."""
    import yaml
    adapted = json.loads(json.dumps(data))
    providers = data.get("proxy-providers", {})
    home = Path(home_dir or str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo"))
    nodes = list(adapted.get("proxies", []))
    provider_nodes = {}
    for name, provider in providers.items():
        if not isinstance(provider, dict) or not provider.get("path"):
            raise ControlError("flclash-provider-needs-local-cache")
        path = Path(provider["path"])
        path = private(path if path.is_absolute() else home / path)
        if path.stat().st_size > LIMIT:
            raise ControlError("flclash-provider-cache-too-large")
        cached = yaml.safe_load(path.read_text(encoding="utf-8"))
        entries = cached.get("proxies") if isinstance(cached, dict) else None
        if not isinstance(entries, list) or any(not isinstance(n, dict) or not isinstance(n.get("name"), str) for n in entries):
            raise ControlError("flclash-provider-cache-invalid")
        for entry in entries:
            provider_nodes.setdefault(entry["name"], []).append(name)
        nodes.extend(entries)
    adapted["proxies"] = nodes
    groups = adapted.setdefault("proxy-groups", [])
    names = {g.get("name") for g in groups}
    for name, choices in (("Ai+", []), ("漏网之鱼", ["DIRECT"])):
        if name not in names:
            groups.append({"name": name, "type": "select", "proxies": choices})
    return adapted, provider_nodes


def policy_candidate(config, script=None, group=None, flclash=False, home_dir=None):
    text, data, tree = read_config(config)
    if script:
        script = private(Path(script))
        if script.stat().st_size > LIMIT:
            raise ControlError("override-script-too-large")
        node = shutil.which("node")
        if not node:
            raise ControlError("override-requires-node")
        input_data, provider_nodes = flclash_input(data, home_dir) if flclash else (data, {})
        result = subprocess.run([node, "-e", OVERRIDE_RUNNER, str(script)],
                                input=json.dumps(input_data), capture_output=True, text=True, encoding="utf-8",
                                env=acceptance.clean_environment(), timeout=10)
        if result.returncode or len(result.stdout.encode()) > LIMIT:
            raise ControlError("override-failed-check-script-input-groups-and-inline-proxies", 1)
        try:
            changed = json.loads(result.stdout)
        except ValueError:
            raise ControlError("override-result-invalid") from None
        if not isinstance(changed, dict):
            raise ControlError("override-result-invalid")
        if flclash:
            if changed.get("proxies") != input_data.get("proxies"):
                raise ControlError("flclash-script-must-preserve-nodes")
            if "proxies" in data:
                changed["proxies"] = data["proxies"]
            else:
                changed.pop("proxies", None)
            inline_names = {n["name"] for n in data.get("proxies", [])}
            for g in changed.get("proxy-groups", []):
                choices = g.get("proxies", [])
                cached_names = [n for n in choices if n in provider_nodes and n not in inline_names]
                if cached_names:
                    g["proxies"] = [n for n in choices if n not in cached_names]
                    g["use"] = list(dict.fromkeys(p for n in cached_names for p in provider_nodes[n]))
                    g["filter"] = "^(?:" + "|".join(re.sub(r'([\\.^$|?*+()\[\]{}])', r'\\\1', n) for n in cached_names) + ")$"
                if g.get("name") == "Ai+":
                    g["type"] = "select"
                    g.pop("use", None)
        # Prevent a desktop script from replacing listeners/auth/TUN/server policy.
        if any(changed.get(k) != data.get(k) for k in set(data) | set(changed) if k not in POLICY_KEYS):
            raise ControlError("override-may-only-change-groups-rules-rule-providers")
        changes = {k: changed[k] for k in POLICY_KEYS if k in changed and changed[k] != data.get(k)}
        if any(k in data and k not in changed for k in POLICY_KEYS):
            raise ControlError("override-cannot-remove-policy-sections")
    else:
        groups = json.loads(json.dumps(data.get("proxy-groups", [])))
        found = [row for row in groups if isinstance(row, dict) and row.get("name") == group]
        if len(found) != 1 or found[0].get("type") not in ("select", "url-test", "fallback", "load-balance"):
            raise ControlError("manual-requires-existing-policy-group", 1)
        found[0]["type"] = "select"
        for key in ("url", "interval", "tolerance", "lazy", "timeout", "max-failed-times", "expected-status", "strategy"):
            found[0].pop(key, None)
        changes = {} if groups == data.get("proxy-groups") else {"proxy-groups": groups}
    profile = data.get("profile", {})
    if not isinstance(profile, dict):
        raise ControlError("config-profile-invalid")
    if changes:
        changes["profile"] = dict(profile, **{"store-selected": True})
    updated = patch_config(text, tree, changes) if changes else text
    if len(updated.encode()) > LIMIT:
        raise ControlError("config-too-large")
    summary = {"changed_sections": list(changes), "state": "preview" if changes else "unchanged",
               "groups": [{"name": label(g["name"]), "type": label(g["type"])}
                          for g in changes.get("proxy-groups", [])],
               "rule_count": len(changes.get("rules", data.get("rules", []))),
               "service": "unchanged"}
    return text, updated, summary


def apply_policy(config, original, updated, home_dir=None):
    if original == updated:
        return {"state": "unchanged", "service": "unchanged"}
    home = Path(home_dir or str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo"))
    private(home, True)
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if not core:
        raise ControlError("mihomo-executable-missing")
    fd, name = tempfile.mkstemp(prefix="policy-check-", suffix=".yaml", dir=config.parent)
    os.close(fd)
    candidate = Path(name)
    try:
        files.atomic_bytes(candidate, updated.encode())
        result = subprocess.run([core, "-t", "-d", str(home), "-f", str(candidate)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=acceptance.clean_environment(), timeout=30)
        if result.returncode:
            raise ControlError("mihomo-config-validation-failed", 1)
        private(config)
        if config.read_text(encoding="utf-8") != original:
            raise ControlError("config-changed-during-policy-edit")
        backup = config.with_name(config.name + ".before-policy-" + secrets.token_hex(8))
        files.atomic_bytes(backup, original.encode())
        files.atomic_bytes(config, updated.encode())
        return {"state": "restart-required", "backup": str(backup), "service": "unchanged"}
    finally:
        candidate.unlink(missing_ok=True)


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


def tui(client, plain=False, config=None, script=None, home_dir=None, details=False, flclash=False):
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
        query, pending = "", None
        delays = {}
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
            middle = min(max(26, width // 3), 42)
            group = groups[group_index] if groups else None
            members = [n for n in group.get("members", []) if query.casefold() in n.casefold()] if group else []
            node_index = min(node_index, max(0, len(members)-1))
            put(0, 1, "MIHOMO · 我的节点 / My nodes", width-2, curses.A_BOLD)
            put(1, 1, "Nodes | / Search | c Connections | o Override | m Manual group", width-2)
            put(2, 1, "Group: " + (group["name"] if group else "none") + " | " +
                ("MANUAL" if group and group["selectable"] else "AUTO / read-only") +
                " | Filter: " + (query or "all"), width-2, curses.A_BOLD)
            put(3, 1, "策略组 / Groups", middle-2, curses.A_BOLD)
            put(3, middle, "节点 / Nodes ({})  [*] selected".format(len(members)), width-middle-1, curses.A_BOLD)
            for y in range(3, height-6):
                put(y, middle-1, "│", 1, curses.A_DIM)
            available = max(1, height-11)
            start = max(0, group_index-available+1)
            for index in range(start, min(len(groups), start+available)):
                row = groups[index]
                put(4+index-start, 1, ("> " if index == group_index else "  ")+row["name"]+" ["+row["type"]+"]", middle-2,
                    curses.A_REVERSE if index == group_index and focus == 0 else curses.A_NORMAL)
            start = max(0, node_index-available+1)
            for index in range(start, min(len(members), start+available)):
                name = members[index]
                suffix = "  {} ms".format(delays[name]) if name in delays else ""
                put(4+index-start, middle, ("[*] " if group.get("selected") == name else "[ ] ")+name+suffix,
                    width-middle-1, curses.A_REVERSE if index == node_index and focus == 1 else curses.A_NORMAL)
            put(height-6, 1, "当前 / Current: " + (group.get("selected") or "dynamic") if group else "No groups", width-2)
            put(height-5, 1, note, width-2)
            for index, line in enumerate(detail[:2]):
                put(height-4+index, 1, line, width-2)
            put(height-2, 1, "↑↓ browse Tab pane Enter select / search m manual o script y apply r refresh t test q quit", width-2)
            window.refresh()
            key = window.getch()
            if key in (ord('q'), 27): return
            if key == ord('/'):
                put(height-5, 1, "Search (empty clears): ", width-2); window.refresh()
                window.timeout(-1); curses.echo(); curses.curs_set(1)
                try:
                    query = window.getstr(height-5, 24, min(120, width-26)).decode("utf-8", errors="replace")
                finally:
                    curses.noecho(); curses.curs_set(0); window.timeout(1000)
                node_index = 0
                continue
            if key in (ord('m'), ord('o'), ord('y')):
                try:
                    if not config:
                        raise ControlError("policy-edit-requires-config")
                    if key == ord('y'):
                        if pending is None:
                            note = "Preview with m or o first."
                            continue
                        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
                            result = apply_policy(config, pending[0], pending[1], home_dir)
                        detail = ["Backup: " + result.get("backup", "none"), "Exit; run mihomoctl restart when ready."]
                        note = "Saved; running policy unchanged until restart."
                        pending = None
                    else:
                        if key == ord('o') and not script:
                            note = "Start with tui --script /ABSOLUTE/trusted-override.js"
                            continue
                        if key == ord('m') and (not group or group["name"] == "GLOBAL"):
                            raise ControlError("choose-configured-policy-group")
                        pending = policy_candidate(config, script=script if key == ord('o') else None,
                                                   group=group["name"] if group else None, flclash=flclash,
                                                   home_dir=home_dir)
                        summary = pending[2]
                        note = "PREVIEW: " + ", ".join(summary["changed_sections"]) + " | y saves, q cancels"
                        detail = ["Groups: " + ", ".join(g["name"] for g in summary["groups"]),
                                  "Rules: {} | existing connections unchanged; restart required".format(summary["rule_count"])]
                except (ControlError, files.InstallError, OSError, ValueError, subprocess.TimeoutExpired) as error:
                    pending = None
                    note = "FAIL: " + (error.code if isinstance(error, ControlError) else "policy-operation-failed")
                continue
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
                        rows = snapshot(client, "connections", details)["connections"]
                        detail = [(row.get("host", "") + " | " if details else "") + " ← ".join(row["chains"]) for row in rows[:2]] or ["No active connections"]
                        note = "Active chains (first 2); use mihomoctl connections for all."
                    elif key == ord('f'):
                        values = snapshot(client, "traffic")
                        detail = ["↑ {} B/s   ↓ {} B/s".format(values["up"], values["down"])]
                    elif group and members:
                        if key == ord('t'):
                            name = members[node_index]
                            note = "Testing public HTTPS target..."; put(height-5, 1, note, width-2); window.refresh()
                            raw = client.request("/proxies/"+quote(name, safe="")+"/delay?"+urlencode({"url": TEST_URL,"timeout":5000}))
                            delays[name] = number(raw.get("delay"))
                            detail = [name+": "+str(delays[name])+" ms; model UNVERIFIED"]
                        else:
                            if not group["selectable"]:
                                note = "自动组只读 / Auto group: m previews conversion to manual; y saves."
                                continue
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
    parser.add_argument("--script", help="Trusted local JS main(config); Node vm is not a security sandbox")
    parser.add_argument("--apply", action="store_true", help="Validate, back up and save the preview; restart separately")
    parser.add_argument("--details", action="store_true", help="Opt in to private host/rule details for connections/TUI")
    parser.add_argument("--flclash-compat", action="store_true", help="Adapt local provider caches and missing Ai+/fallback groups for FlClash-rules")
    args = parser.parse_args(argv)
    if args.plain and args.command != "tui":
        raise ControlError("plain-requires-tui")
    if args.script and args.command not in ("override", "tui") or args.apply and args.command not in ("override", "manual"):
        raise ControlError("policy-options-require-override-manual-or-tui")
    if args.details and args.command not in ("connections", "tui"):
        raise ControlError("details-requires-connections-or-tui")
    if args.flclash_compat and (not args.script or args.command not in ("override", "tui")):
        raise ControlError("flclash-compat-requires-script")
    if args.plain and args.script:
        raise ControlError("script-preview-requires-fullscreen-tui-or-override-command")
    config = Path(args.config or str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mihomo/config.yaml"))
    setup_requested = args.command == "controller" and args.values == ["setup"]
    if not setup_requested and (any(v is not None for v in (args.port, args.archive, args.sha256)) or
                                args.home_dir is not None and args.command not in ("override", "manual", "tui")):
        raise ControlError("setup-options-require-controller-setup")
    if args.command in ("override", "manual"):
        if (args.command == "override" and (not args.script or args.values) or
                args.command == "manual" and len(args.values) != 1):
            raise ControlError("invalid-options")
        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
            original, updated, payload = policy_candidate(config, script=args.script,
                                                         group=args.values[0] if args.values else None,
                                                         flclash=args.flclash_compat, home_dir=args.home_dir)
            if args.apply:
                payload.update(apply_policy(config, original, updated, args.home_dir))
    elif setup_requested:
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
            payload = snapshot(client, args.command, args.details)
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
            payload = tui(client, args.plain, config, args.script, args.home_dir, args.details, args.flclash_compat)
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
