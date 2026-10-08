"""Private node-only subscription staging; no full configuration import."""
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import sys
import time
from urllib.parse import urlsplit

try:
    from .controller_types import ControlError, LIMIT, label
    from .controller_config import private, read_config, patch_config
    from .controller_transaction import apply_policy
    from . import install_support as files
except ImportError:
    from controller_types import ControlError, LIMIT, label
    from controller_config import private, read_config, patch_config
    from controller_transaction import apply_policy
    import install_support as files


def digest(content):
    return hashlib.sha256(content).hexdigest()


def download(url):
    """TLS verification, direct transport, no redirects or error-body disclosure."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.fragment or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        raise ControlError("subscription-requires-https-url-without-userinfo", 1)
    try:
        connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443,
                                                 timeout=15, context=ssl.create_default_context())
        try:
            connection.request("GET", (parts.path or "/") + ("?" + parts.query if parts.query else ""),
                               headers={"Accept": "application/yaml, text/yaml, text/plain"})
            response = connection.getresponse()
            if response.status != 200 or response.getheader("Content-Encoding", "identity") != "identity":
                raise ControlError("subscription-download-rejected", 1)
            deadline, chunks, size = time.monotonic() + 15, [], 0
            while size <= LIMIT:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ControlError("subscription-download-timeout", 1)
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, LIMIT + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            result = b"".join(chunks)
        finally:
            connection.close()
    except (OSError, ValueError, http.client.HTTPException):
        raise ControlError("subscription-download-failed", 1) from None
    if not result or len(result) > LIMIT:
        raise ControlError("subscription-size-invalid", 1)
    return result


class Subscriptions:
    def __init__(self, config, home_dir=None):
        self.config, self.home_dir = Path(config), home_dir
        self.data_home = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
        self.root = Path(self.data_home) / "mihomo-userctl-subscriptions"

    def directory(self):
        files.safe_path(self.root, True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        private(self.root, True)

    def preview(self, source_file=None, url_file=None, stdin=False):
        if sum(bool(value) for value in (source_file, url_file, stdin)) != 1:
            raise ControlError("choose-one-private-subscription-source")
        if stdin:
            raw = sys.stdin.buffer.read(LIMIT + 1)
        else:
            path = private(Path(url_file or source_file).absolute())
            if path.stat().st_size > LIMIT:
                raise ControlError("subscription-size-invalid", 1)
            raw = path.read_bytes()
            if url_file:
                try:
                    raw = download(raw.decode("utf-8").strip())
                except UnicodeError:
                    raise ControlError("subscription-url-invalid", 1) from None
        if not raw or len(raw) > LIMIT:
            raise ControlError("subscription-size-invalid", 1)
        self.directory()
        identifier = secrets.token_hex(16)
        source = self.root / (identifier + ".raw.yaml")
        with files.locked(self.data_home):
            files.atomic_bytes(source, raw)
            try:
                _, incoming, _ = read_config(source)
                if set(incoming) != {"proxies"}:
                    raise ControlError("subscription-only-node-list-supported", 1)
                nodes = incoming["proxies"]
                if not isinstance(nodes, list) or not nodes or len(nodes) > 10000:
                    raise ControlError("subscription-node-list-invalid", 1)
                names = set()
                for node in nodes:
                    if not isinstance(node, dict) or not isinstance(node.get("type"), str):
                        raise ControlError("subscription-node-invalid", 1)
                    label(node["type"])
                    name = label(node.get("name"))
                    if not name or name in names:
                        raise ControlError("subscription-node-name-invalid", 1)
                    names.add(name)
                original, data, tree = read_config(self.config)
                current = data.get("proxies", [])
                if not isinstance(current, list) or any(not isinstance(node, dict) or not isinstance(node.get("name"), str) for node in current):
                    raise ControlError("existing-node-list-invalid")
                merged = {node["name"]: node for node in current}
                if len(merged) != len(current):
                    raise ControlError("existing-node-names-not-unique")
                existing_names = set(merged)
                replaced = len(names.intersection(merged))
                merged.update({node["name"]: node for node in nodes})
                candidate = patch_config(original, tree, {"proxies": list(merged.values())}).encode("utf-8")
                candidate_hash = digest(candidate)
                plan = {"schema": 1, "id": identifier, "config": str(self.config.absolute()),
                        "original_sha256": digest(original.encode("utf-8")),
                        "candidate_sha256": candidate_hash, "nodes": len(nodes), "replaced": replaced}
                files.atomic_bytes(self.root / (identifier + ".candidate.yaml"), candidate)
                files.write_json(self.root / (identifier + ".json"), plan)
            except BaseException:
                source.unlink(missing_ok=True)
                raise
        return {"state": "preview", "id": identifier, "sha256": candidate_hash,
                "nodes": len(nodes), "added": len(nodes) - replaced, "replaced": replaced,
                "changes": [{"name": node["name"], "type": label(node["type"]),
                             "action": "replace" if node["name"] in existing_names else "add"} for node in nodes],
                "fields": ["proxies"], "service": "unchanged"}

    def apply(self, identifier, expected_hash):
        if not re.fullmatch(r"[0-9a-f]{32}", identifier) or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise ControlError("subscription-plan-invalid", 1)
        self.directory()
        with files.locked(self.data_home):
            plan_path = private(self.root / (identifier + ".json"))
            candidate_path = private(self.root / (identifier + ".candidate.yaml"))
            if plan_path.stat().st_size > LIMIT or candidate_path.stat().st_size > LIMIT:
                raise ControlError("subscription-size-invalid", 1)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            candidate = candidate_path.read_bytes()
            original, _, _ = read_config(self.config)
            if (plan.get("schema") != 1 or plan.get("id") != identifier or
                    plan.get("config") != str(self.config.absolute()) or
                    plan.get("candidate_sha256") != expected_hash or digest(candidate) != expected_hash):
                raise ControlError("subscription-candidate-changed", 1)
            if digest(original.encode("utf-8")) != plan.get("original_sha256"):
                raise ControlError("subscription-config-changed", 1)
            # Re-parse both sides and enforce the write boundary even if a plan
            # file was edited. The existing JS policy allowlist is unaffected.
            _, before, _ = read_config(self.config)
            _, after, _ = read_config(candidate_path)
            if {k: v for k, v in before.items() if k != "proxies"} != {k: v for k, v in after.items() if k != "proxies"}:
                raise ControlError("subscription-may-only-change-proxies", 1)
            result = apply_policy(self.config, original, candidate.decode("utf-8"), self.home_dir)
            return {"id": identifier, "sha256": expected_hash, **result}
