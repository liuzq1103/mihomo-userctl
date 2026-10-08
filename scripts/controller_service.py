"""User-level controller component; no global proxy or daemon."""
import json
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import subprocess
import time
import unicodedata
from urllib.parse import quote, urlencode
try:
    from . import acceptance, install_support as files
except ImportError:
    import acceptance
    import install_support as files
try:
    from .controller_types import ControlError, LIMIT, TEST_URL, label, number
except ImportError:
    from controller_types import ControlError, LIMIT, TEST_URL, label, number

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
    client.verify()
    rows = proxies(client)
    if group not in rows or not rows[group].get("selectable"):
        raise ControlError("selection-requires-Selector-group", 1)
    if node not in rows[group]["members"]:
        raise ControlError("node-not-in-group", 1)
    client.request("/proxies/" + quote(group, safe=""), "PUT", {"name": node})
    if proxies(client).get(group, {}).get("selected") != node:
        raise ControlError("selection-not-confirmed", 1)
    return {"group": group, "selected": node, "existing_connections": "unchanged"}


def snapshot(client, command, details=False, id_key=None):
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
        if id_key is not None:
            identity = item.get("id") or json.dumps(item, sort_keys=True, ensure_ascii=True)
            rows[-1]["id"] = hmac.new(id_key, str(identity).encode("utf-8"), hashlib.sha256).hexdigest()[:32]
        if details:
            metadata = item.get("metadata") or {}
            if not isinstance(metadata, dict):
                raise ControlError("controller-connections-invalid")
            rows[-1]["host"] = label(metadata.get("host", ""))
            rows[-1]["rule_payload"] = label(item.get("rulePayload", ""))
    return {"connections": rows, "uploadTotal": number(raw.get("uploadTotal", 0)),
            "downloadTotal": number(raw.get("downloadTotal", 0))}


class ConsoleService:
    """One security boundary shared by interactive backends and new CLI actions.

    Raw configurations and credentials stay local to operations, never in DTOs.
    Each operation opens and verifies a new controller session. Mutations are
    explicit and are never retried or replayed after a transport failure.
    """
    def __init__(self, config, home_dir=None, details=False, script=None, flclash=False):
        self.config = Path(config)
        self.home_dir, self.details = home_dir, details
        self.script, self.flclash = script, flclash
        self._connection_key = secrets.token_bytes(32)

    def client(self):
        try:
            from .controller_config import read_config, endpoint
            from .controller_api import Client
        except ImportError:
            from controller_config import read_config, endpoint
            from controller_api import Client
        _, data, _ = read_config(self.config)
        client = Client(*endpoint(data))
        client.verify()
        return client

    def shell(self, action):
        allowed = {"status", "ready", "doctor", "start", "stop", "restart", "codex", "codex-diagnosis", "rules-status", "rules-check"}
        if action not in allowed:
            raise ControlError("invalid-runtime-action")
        root = Path(__file__).resolve().parent
        executable = root / "mihomoctl"
        if not executable.exists():
            executable = root.parent / "src/mihomoctl"
        args = ["bash", str(executable), action]
        if action in ("rules-status", "rules-check"):
            args = ["bash", str(executable), "rules", action.split("-")[1], "--json"]
        elif action == "codex":
            args.extend(["preflight", "--json"])
        elif action == "codex-diagnosis":
            args = ["bash", str(executable), "diagnose", "codex", "--json"]
        elif action == "doctor":
            args.extend(["--offline", "--json"])
        elif action in ("status", "ready", "doctor"):
            args.append("--json")
        environment = acceptance.clean_environment()
        environment["MIHOMO_USERCTL_LIB_DIR"] = str(root)
        result = subprocess.run(args, env=environment, capture_output=True, timeout=45)
        if len(result.stdout) > LIMIT:
            raise ControlError("runtime-response-too-large")
        if action in ("start", "stop", "restart"):
            if result.returncode:
                raise ControlError("runtime-action-failed", 1 if result.returncode == 1 else 2)
            return {"action": action, "state": "confirmed", "shell": "unchanged"}
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise ControlError("runtime-response-invalid") from None
        if not isinstance(value, dict):
            raise ControlError("runtime-response-invalid")
        return value

    def read(self, page):
        if page == "runtime":
            return self.shell("status")
        if page == "diagnostics":
            return {"doctor": self.shell("doctor"), "codex": self.shell("codex-diagnosis"),
                    "preflight": "explicit : codex; readiness: explicit : ready"}
        if page == "profiles":
            try:
                from .controller_config import read_config
            except ImportError:
                from controller_config import read_config
            _, data, _ = read_config(self.config)
            return {"configuration": "private", "nodes": len(data.get("proxies") or []),
                    "groups": len(data.get("proxy-groups") or []),
                    "providers": len(data.get("proxy-providers") or {}),
                    "service": "disk config; restart separately after saving"}
        client = self.client()
        if page == "proxies":
            return proxies(client)
        if page in ("connections", "traffic"):
            return snapshot(client, page, self.details, self._connection_key if page == "connections" else None)
        if page == "memory":
            raw = client.request("/memory", stream=True, optional=True)
            return {key: number(raw.get(key, 0)) for key in ("inuse", "oslimit")}
        if page == "overview":
            version = client.request("/version")
            return {"authentication": "PASS", "listener": "PASS",
                    "core": label(version.get("version", "unknown")),
                    "groups": snapshot(client, "groups")["groups"],
                    "traffic": snapshot(client, "traffic"),
                    "connections": len(snapshot(client, "connections")["connections"])}
        if page == "rules":
            raw = client.request("/rules", optional=True).get("rules", [])
            if not isinstance(raw, list):
                raise ControlError("controller-rules-invalid")
            counts = {}
            for row in raw:
                if not isinstance(row, dict):
                    raise ControlError("controller-rules-invalid")
                kind = label(row.get("type", "unknown"))
                counts[kind] = counts.get(kind, 0) + 1
            providers, provider_state = [], "supported"
            try:
                source = client.request("/providers/rules", optional=True).get("providers", {})
            except ControlError as error:
                if error.code != "controller-capability-unsupported":
                    raise
                source, provider_state = {}, "unsupported"
            if not isinstance(source, dict):
                raise ControlError("controller-rule-providers-invalid")
            for name, row in source.items():
                if not isinstance(row, dict):
                    raise ControlError("controller-rule-providers-invalid")
                providers.append({"name": label(name), "type": label(row.get("vehicleType", "unknown")),
                                  "behavior": label(row.get("behavior", "unknown")),
                                  "rules": number(row.get("ruleCount", 0)),
                                  "updated": label(row.get("updatedAt", "unknown"))})
            return {"total": len(raw), "types": counts, "providers": providers,
                    "provider_capability": provider_state}
        if page == "providers":
            raw = client.request("/providers/proxies", optional=True).get("providers", {})
            if not isinstance(raw, dict):
                raise ControlError("controller-providers-invalid")
            result = []
            for name, row in raw.items():
                if not isinstance(row, dict) or not isinstance(row.get("proxies", []), list):
                    raise ControlError("controller-providers-invalid")
                result.append({"name": label(name), "type": label(row.get("vehicleType", "unknown")),
                               "nodes": len(row.get("proxies", [])),
                               "updated": label(row.get("updatedAt", "unknown"))})
            return {"providers": result}
        if page == "logs":
            raw = client.request("/logs?level=info", stream=True, optional=True)
            # Log payloads can contain URLs, credentials and destinations.
            return {"level": label(raw.get("type", "unknown")),
                    "message": self.log_text(raw.get("payload", ""), [client.token] + self.log_credentials())}
        raise ControlError("unknown-console-page")

    def diagnose(self, kind, target):
        if kind == "url":
            if not acceptance.public_https_url(target):
                raise ControlError("diagnosis-requires-public-https-without-credentials-or-query", 1)
        elif kind == "process":
            if not re.fullmatch(r"[1-9][0-9]{0,19}", target):
                raise ControlError("invalid-pid", 1)
        else:
            raise ControlError("invalid-diagnosis-kind")
        root = Path(__file__).resolve().parent
        executable = root / "mihomoctl"
        if not executable.exists():
            executable = root.parent / "src/mihomoctl"
        environment = acceptance.clean_environment()
        environment["MIHOMO_USERCTL_LIB_DIR"] = str(root)
        result = subprocess.run(["bash", str(executable), "diagnose", kind, target, "--json"],
                                env=environment, capture_output=True, timeout=60)
        if len(result.stdout) > LIMIT:
            raise ControlError("runtime-response-too-large")
        try:
            value = json.loads(result.stdout)
        except (ValueError, UnicodeError):
            raise ControlError("runtime-response-invalid") from None
        if not isinstance(value, dict):
            raise ControlError("runtime-response-invalid")
        # Existing diagnostics owns UID restrictions and the evidence policy.
        # Terminal control characters from a process comm cannot reach widgets.
        def project(item):
            if isinstance(item, str):
                return "".join(char if unicodedata.category(char) not in ("Cc", "Cf") else " " for char in item)
            if isinstance(item, list):
                return [project(child) for child in item]
            if isinstance(item, dict):
                return {key: project(child) for key, child in item.items()}
            return item
        return project(value)

    def choose(self, group, node):
        return select(self.client(), group, node)

    def latency(self, node):
        client = self.client()
        if node not in proxies(client):
            raise ControlError("unknown-node", 1)
        raw = client.request("/proxies/" + quote(node, safe="") + "/delay?" +
                             urlencode({"url": TEST_URL, "timeout": 5000}))
        return {"name": node, "delay_ms": number(raw.get("delay")), "target": TEST_URL,
                "model_request": "UNVERIFIED", "sampled_at": time.time()}

    def batch_latency(self, nodes, cancelled=None, progress=None):
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        cancelled = cancelled or threading.Event()
        targets = tuple(dict.fromkeys(nodes))
        if not targets or len(targets) > 1000:
            raise ControlError("invalid-batch-targets")
        results = []
        def test(node):
            if cancelled.is_set():
                return {"name": node, "state": "cancelled"}
            try:
                return dict(self.latency(node), state="success")
            except ControlError as error:
                return {"name": node, "state": "failed", "error": error.code}
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(test, node) for node in targets]
            for future in as_completed(futures):
                results.append(future.result())
                if progress:
                    progress(len(results), len(targets))
        return {"results": results, "target_count": len(targets)}

    def provider_refresh(self, name):
        label(name)
        if name not in [row["name"] for row in self.read("providers")["providers"]]:
            raise ControlError("unknown-provider", 1)
        self.client().request("/providers/proxies/" + quote(name, safe=""), "PUT", optional=True)
        return {"provider": name, "state": "refresh-requested"}

    def logs(self, emit, cancelled, level="info"):
        if level not in ("debug", "info", "warning", "error"):
            raise ControlError("invalid-log-level", 1)
        failures = 0
        while not cancelled.is_set():
            try:
                client = self.client()
                redactions = [client.token] + self.log_credentials()
                emit({"level": level, "message": "authenticated stream connected"})
                for row in client.lines("/logs?" + urlencode({"level": level}), cancelled):
                    message = self.log_text(row.get("payload", ""), redactions)
                    emit({"level": label(row.get("type", "unknown")), "message": message,
                          "sampled_at": time.time()})
                failures = 0
                cancelled.wait(.1)
            except ControlError as error:
                emit(error=error.code)
                if error.code == "controller-capability-unsupported":
                    return
                cancelled.wait(min(2 ** min(failures, 4), 15))
                failures += 1
            except (OSError, ValueError):
                emit(error="controller-stream-unverified")
                cancelled.wait(min(2 ** min(failures, 4), 15))
                failures += 1

    def log_credentials(self):
        if not self.details:
            return []
        try:
            from .controller_config import read_config
        except ImportError:
            from controller_config import read_config
        _, configuration, _ = read_config(self.config)
        redactions = []
        def collect(value, protected=False):
            if isinstance(value, dict):
                for key, child in value.items():
                    collect(child, protected or str(key).lower() in ("password", "secret", "uuid", "private-key", "authentication", "url"))
            elif isinstance(value, list):
                for child in value:
                    collect(child, protected)
            elif protected and isinstance(value, str) and value:
                redactions.append(value)
                if ":" in value and "://" not in value:
                    redactions.extend(part for part in value.split(":", 1) if part)
        collect(configuration)
        return redactions

    def log_text(self, payload, redactions):
        if not self.details:
            return "private log entry (use --details)"
        if not isinstance(payload, str):
            raise ControlError("controller-log-invalid")
        for credential in sorted(set(redactions), key=len, reverse=True):
            payload = payload.replace(credential, "[redacted]")
        payload = re.sub(r"(https?://)[^\s/]+@", r"\1[redacted]@", payload)
        payload = re.sub(r"([?&](?:token|key|secret|password|auth)=)[^\s&]+", r"\1[redacted]", payload, flags=re.I)
        return "".join(char if unicodedata.category(char) not in ("Cc", "Cf") else " " for char in payload)[:4096]

    def journal(self):
        common = Path(__file__).with_name("common.bash")
        if not common.exists():
            common = Path(__file__).resolve().parents[1] / "src/common.bash"
        files.safe_path(common)
        if common.stat().st_mode & 0o022:
            raise ControlError("unsafe-runtime-module")
        code = 'source "$1" || exit 2; _muc_load_config || exit 2; exec journalctl --user --unit "$MIHOMO_SERVICE" --lines 200 --no-pager --output=json'
        try:
            result = subprocess.run(["bash", "-c", code, "mihomo-journal", str(common)],
                                    env=acceptance.clean_environment(), capture_output=True, timeout=8)
        except (OSError, subprocess.TimeoutExpired):
            raise ControlError("journal-unavailable") from None
        if result.returncode or len(result.stdout) > LIMIT:
            raise ControlError("journal-unavailable")
        redactions, rows = self.log_credentials(), []
        try:
            for line in result.stdout.splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ControlError("journal-response-invalid")
                priority, timestamp = str(row.get("PRIORITY", "")), str(row.get("__REALTIME_TIMESTAMP", ""))
                rows.append({"priority": priority if re.fullmatch(r"[0-7]", priority) else "unknown",
                             "time_us": timestamp if re.fullmatch(r"[0-9]{1,20}", timestamp) else "unknown",
                             "message": self.log_text(row.get("MESSAGE", ""), redactions)})
        except (ValueError, UnicodeError):
            raise ControlError("journal-response-invalid") from None
        return {"source": "current-user-service-journal", "entries": rows}

    def mode(self, mode):
        if mode not in ("rule", "global", "direct"):
            raise ControlError("invalid-core-mode", 1)
        client = self.client()
        client.request("/configs", "PATCH", {"mode": mode}, optional=True)
        if str(client.request("/configs", optional=True).get("mode", "")).lower() != mode:
            raise ControlError("mode-not-confirmed", 1)
        return {"mode": mode, "scope": "runtime-only", "shell": "unchanged", "config": "unchanged"}

    def dns(self, name, record="A"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", name) or record not in ("A", "AAAA", "CNAME", "TXT", "MX"):
            raise ControlError("invalid-dns-query", 1)
        raw = self.client().request("/dns/query?" + urlencode({"name": name, "type": record}), optional=True)
        answer = raw.get("Answer") or []
        if not isinstance(answer, list):
            raise ControlError("controller-dns-invalid")
        return {"query": name, "record": record, "answers": [
            {"type": number(row.get("type", 0)), "ttl": number(row.get("TTL", 0)),
             "data": label(str(row.get("data", "")))} for row in answer if isinstance(row, dict)],
            "system_dns": "unchanged"}

    def policy(self, group=None, apply=False):
        try:
            from .controller_policy import policy_candidate
            from .controller_transaction import apply_policy
        except ImportError:
            from controller_policy import policy_candidate
            from controller_transaction import apply_policy
        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
            if apply:
                if not getattr(self, "_policy", None):
                    raise ControlError("policy-preview-required")
                original, updated, result = self._policy
                self._policy = None
                return dict(result, **apply_policy(self.config, original, updated, self.home_dir))
            original, updated, result = policy_candidate(self.config, group=group,
                    script=None if group else self.script, flclash=self.flclash, home_dir=self.home_dir)
            self._policy = (original, updated, result)
            return result

    def subscription_preview(self, path, url=False):
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        return Subscriptions(self.config, self.home_dir).preview(**{"url_file" if url else "source_file": path})

    def subscription_apply(self, identifier, digest):
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        return Subscriptions(self.config, self.home_dir).apply(identifier, digest)
