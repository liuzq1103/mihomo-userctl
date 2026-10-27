"""Private node and routing-policy staging; preserve host runtime settings."""
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
from pathlib import PurePosixPath
from urllib.parse import urlsplit

try:
    from .controller_types import ControlError, LIMIT, label
    from .controller_config import private, read_config, parse_config, patch_config
    from .controller_transaction import apply_policy, validate_candidate
    from .controller_health import probe_overwrites
    from . import files
except ImportError:
    from controller_types import ControlError, LIMIT, label
    from controller_config import private, read_config, parse_config, patch_config
    from controller_transaction import apply_policy, validate_candidate
    from controller_health import probe_overwrites
    import files


def digest(content):
    return hashlib.sha256(content).hexdigest()


POLICY_FIELDS = {"proxies": list, "proxy-providers": dict, "proxy-groups": list,
                 "rules": list, "rule-providers": dict}

# `proxies` is the node-list field; every other policy field is routing
# policy. `auto` detects provider mode from the presence of routing policy,
# never from an exact key-set match, so extra top-level keys cannot flip a
# node list into a provider overlay that would default the policy fields the
# source did not supply.
ROUTING_FIELDS = frozenset(key for key in POLICY_FIELDS if key != "proxies")
OVERLAY_FIELDS = frozenset(('proxy-groups', 'rules', 'rule-providers'))


def policy_overlay(incoming, current):
    if not incoming or set(incoming) - OVERLAY_FIELDS:
        raise ControlError('subscription-policy-overlay-fields-only', 1)
    merged = dict(current, **incoming)
    provider_policy(merged)  # Validate references against the complete result.
    return dict(incoming)


def provider_policy(incoming):
    """Keep provider routing intact while excluding host runtime settings."""
    if not set(incoming).intersection(POLICY_FIELDS):
        raise ControlError("subscription-routing-policy-missing", 1)
    changes = {key: incoming.get(key, kind()) for key, kind in POLICY_FIELDS.items()}
    if any(not isinstance(changes[key], kind) for key, kind in POLICY_FIELDS.items()):
        raise ControlError("subscription-policy-shape-invalid", 1)
    names = {"DIRECT", "REJECT", "REJECT-DROP", "PASS", "COMPATIBLE"}
    for row in changes["proxies"] + changes["proxy-groups"]:
        if not isinstance(row, dict) or not isinstance(row.get("type"), str):
            raise ControlError("subscription-policy-entry-invalid", 1)
        name = label(row.get("name"))
        if not name or name in names:
            raise ControlError("subscription-policy-name-invalid", 1)
        names.add(name)
    # Mihomo permits replacing its implicit GLOBAL group with an explicit one.
    names.add("GLOBAL")
    for field in ("proxy-providers", "rule-providers"):
        for name, row in changes[field].items():
            label(name)
            if not isinstance(row, dict):
                raise ControlError("subscription-provider-invalid", 1)
            path = row.get("path")
            if path is not None and (not isinstance(path, str) or not path or
                    "\\" in path or ":" in path or PurePosixPath(path).is_absolute() or
                    ".." in PurePosixPath(path).parts):
                raise ControlError("subscription-provider-path-unsafe", 1)
            if row.get("type") == "file" and not path:
                raise ControlError("subscription-provider-path-required", 1)
    for group in changes["proxy-groups"]:
        members, providers = group.get("proxies", []), group.get("use", [])
        if not isinstance(members, list) or not isinstance(providers, list):
            raise ControlError("subscription-group-references-invalid", 1)
        if any(not isinstance(n, str) or n not in names for n in members):
            raise ControlError("subscription-group-reference-missing", 1)
        if any(not isinstance(n, str) or n not in changes["proxy-providers"] for n in providers):
            raise ControlError("subscription-provider-reference-missing", 1)
    for rule in changes["rules"]:
        if not isinstance(rule, str):
            raise ControlError("subscription-rule-invalid", 1)
        parts = [part.strip() for part in rule.split(",")]
        if len(parts) < 2:
            raise ControlError("subscription-rule-invalid", 1)
        # Logical rules may contain nested commas; their policy remains last.
        target = parts[-2] if parts[-1] == "no-resolve" else parts[-1]
        if target not in names:
            raise ControlError("subscription-rule-target-missing", 1)
        if parts[0] == "RULE-SET" and (len(parts) < 3 or parts[1] not in changes["rule-providers"]):
            raise ControlError("subscription-rule-provider-missing", 1)
    return changes


def download(url, cancelled=None):
    """TLS verification, direct transport, no redirects or error-body disclosure."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.fragment or any(ord(char) < 33 or ord(char) == 127 for char in url)):
        raise ControlError("subscription-requires-https-url-without-userinfo", 1)
    try:
        if cancelled is not None and cancelled.is_set():
            raise ControlError('subscription-download-cancelled')
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
                if cancelled is not None and cancelled.is_set():
                    raise ControlError('subscription-download-cancelled')
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
        try:
            from .controller_transaction import runtime_application
        except ImportError:
            from controller_transaction import runtime_application
        self.app = runtime_application.get()
        self.data_home = str(self.app.scope.state_root) if self.app is not None else os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))
        self.root = Path(self.data_home) / ('subscriptions' if self.app is not None else 'mihomo-userctl-subscriptions')

    def directory(self):
        files.safe_path(self.root, True)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        private(self.root, True)
        with files.locked(self.data_home):
            now = time.time()
            for path in self.root.iterdir():
                if re.fullmatch(r'[a-f0-9]{32}\.(raw\.yaml|candidate\.yaml|json)', path.name):
                    try:
                        private(path)
                    except (ControlError, files.InstallError, OSError):
                        continue  # Foreign/drifted files are never automatic cleanup targets.
                    if now - path.stat().st_mtime > 24 * 60 * 60:
                        path.unlink()

    def discard(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier or ''):
            raise ControlError('subscription-plan-invalid')
        self.directory()
        with files.locked(self.data_home):
            for suffix in ('.json', '.candidate.yaml', '.raw.yaml'):
                path = self.root / (identifier + suffix)
                if path.exists() or path.is_symlink():
                    private(path)
                    path.unlink()

    def check_provider_paths(self, changes):
        home = Path(self.home_dir or str(Path(self.data_home) / "mihomo"))
        if self.app is not None and self.app.system:
            from mihomoctl.lifecycle.systemd import ensure_service_account
            from mihomoctl.trust import _check_ancestors
            owner = ensure_service_account(create=False).pw_uid
            _check_ancestors(home / 'provider', 'provider-path-unsafe', {0, owner})
            if home != self.app.scope.core_home or home.stat().st_uid != owner:
                raise ControlError('subscription-provider-path-unsafe')
        else:
            private(home, True)
        used = set()
        for field in ("proxy-providers", "rule-providers"):
            for row in changes[field].values():
                if row.get("type") == "http" and not row.get("path"):
                    raise ControlError("subscription-provider-cache-path-required", 1)
                if row.get("path"):
                    target = home / row["path"]
                    if home.resolve() not in target.resolve().parents:
                        raise ControlError("subscription-provider-path-unsafe", 1)
                    if self.app is not None and self.app.system:
                        _check_ancestors(target, 'provider-path-unsafe', {0, owner})
                        if target.is_symlink():
                            raise ControlError('subscription-provider-path-unsafe', 1)
                    else:
                        try:
                            files.safe_path(target)
                        except files.InstallError:
                            raise ControlError("subscription-provider-path-unsafe", 1) from None
                    resolved = target.resolve()
                    # Downloaded content must never overwrite configuration or
                    # core state. Preserve safe provider paths in dedicated trees.
                    roots = {"providers", "proxy-providers", "proxy_provider", "proxy_providers",
                             "rules", "rule-providers", "rule_provider", "rule_providers"}
                    relative = resolved.relative_to(home.resolve())
                    if (len(relative.parts) < 2 or relative.parts[0] not in roots or
                            resolved == self.config.resolve() or
                            resolved.name.startswith(self.config.name + ".") or
                            resolved in used):
                        raise ControlError("subscription-provider-cache-path-unsafe", 1)
                    used.add(resolved)

    def preview(self, source_file=None, url_file=None, stdin=False, policy="auto", raw=None, guided=False):
        requested_policy = policy
        if policy not in ("auto", "nodes", "provider", "policy"):
            raise ControlError("subscription-policy-invalid", 1)
        if sum(bool(value) for value in (source_file, url_file, stdin)) + (raw is not None) != 1:
            raise ControlError("choose-one-private-subscription-source")
        if raw is not None:
            pass
        elif stdin:
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
        with files.locked(self.data_home):
            try:
                _, incoming, _ = parse_config(raw)
                for key in incoming:
                    label(key)
                if policy == "auto":
                    policy = "provider" if set(incoming) & ROUTING_FIELDS else "nodes"
                if policy == "nodes" and set(incoming) != {"proxies"}:
                    raise ControlError("subscription-only-node-list-supported", 1)
                nodes = incoming.get("proxies", [])
                if not isinstance(nodes, list) or (not nodes and policy == "nodes") or len(nodes) > 10000:
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
                if guided:
                    from mihomoctl.onboarding import guided_shape, guided_policy
                    if not guided_shape(data):
                        raise ControlError('existing-routing-preserved-use-advanced')
                    changes = guided_policy(incoming)
                else:
                    changes = (policy_overlay(incoming, data) if policy == 'policy' else
                               provider_policy(incoming) if policy == "provider" else {"proxies": list(merged.values())})
                if policy in ("provider", "policy"):
                    self.check_provider_paths(provider_policy(dict(data, **changes)))
                    validate_candidate(self.config, self.home_dir, patch_config(original, tree, changes))
                candidate = patch_config(original, tree, changes).encode("utf-8")
                candidate_hash = digest(candidate)
                plan = {"schema": 1, "id": identifier, "config": str(self.config.absolute()),
                        "original_sha256": digest(original.encode("utf-8")),
                        "candidate_sha256": candidate_hash, "nodes": len(nodes), "replaced": replaced,
                        "policy": policy}
                files.atomic_bytes(self.root / (identifier + ".candidate.yaml"), candidate)
                files.write_json(self.root / (identifier + ".json"), plan)
            except BaseException:
                for suffix in ('.json', '.candidate.yaml'):
                    (self.root / (identifier + suffix)).unlink(missing_ok=True)
                raise
        return {"state": "preview", "id": identifier, "sha256": candidate_hash,
                "nodes": len(nodes), "added": len(nodes) - replaced, "replaced": replaced,
                "changes": [{"name": node["name"], "type": label(node["type"]),
                             "action": "replace" if node["name"] in existing_names else "add"} for node in nodes],
                "policy": policy, "requested_policy": requested_policy, "fields": list(changes),
                "probe_overwrites": probe_overwrites(data, changes) if policy == "provider" else [],
                "ignored_fields": sorted(set(incoming) - set(changes)),
                "removed": len(existing_names - names) if policy == "provider" else 0,
                "removed_groups": (len({g.get("name") for g in data.get("proxy-groups", []) if isinstance(g, dict)} -
                                       {g["name"] for g in changes["proxy-groups"]}) if policy == "provider" else 0),
                "removed_rules": (sum(rule not in changes["rules"] for rule in data.get("rules", [])) if policy == "provider" else 0),
                "group_changes": ([{"name": group["name"], "type": label(group["type"])}
                                   for group in changes.get("proxy-groups", [])] if policy == "provider" else []),
                "groups": len(changes.get("proxy-groups", [])),
                "rules": len(changes.get("rules", [])), "service": "unchanged"}

    def apply(self, identifier, expected_hash, source_url=None, activate=False):
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
            policy = plan.get("policy", "nodes")
            if policy not in ("nodes", "provider", "policy"):
                raise ControlError("subscription-plan-invalid", 1)
            allowed = set(POLICY_FIELDS) if policy == "provider" else OVERLAY_FIELDS if policy == 'policy' else {"proxies"}
            if policy in ("provider", "policy"):
                self.check_provider_paths(provider_policy(after))
            if {k: v for k, v in before.items() if k not in allowed} != {k: v for k, v in after.items() if k not in allowed}:
                raise ControlError("subscription-may-only-change-routing-policy" if policy == "provider" else "subscription-may-only-change-proxies", 1)
            def save_source(tx):
                if self.app is not None and source_url is not None:
                    path = self.app.scope.config_root / 'subscription-url'
                    if source_url:
                        tx.write_text(path, source_url + '\n')
                    else:
                        tx.delete(path)
            result = apply_policy(self.config, original, candidate.decode("utf-8"), self.home_dir,
                                  after_write=save_source if source_url is not None else None, activate=activate)
            try:
                for suffix in ('.json', '.candidate.yaml', '.raw.yaml'):
                    (self.root / (identifier + suffix)).unlink(missing_ok=True)
            except OSError:
                state={'phase':'cleanup','config':'unverified','runtime':'unverified',
                       'activation':'unverified' if activate else 'not-requested'}
                try:
                    state['config']='committed' if digest(self.config.read_bytes())==result.get('applied_sha256',expected_hash) else 'changed'
                    if self.app is not None:
                        observed=self.app.status();runtime=observed.get('runtime',{})
                        if observed.get('overall')=='PASS' and runtime.get('running') is True:
                            state['runtime']='running'
                            if activate and state['config']=='committed':state['activation']='verified'
                        elif runtime.get('running') is False and runtime.get('detail')!='stale-state' and runtime.get('state') in (None,'inactive','failed'):
                            state['runtime']='stopped'
                except Exception:pass
                error=ControlError('subscription-cleanup-incomplete')
                error.operation_state=state
                error.safe_detail='phase={phase}; config={config}; runtime={runtime}; activation={activation}'.format(**state)
                raise error from None
            return {"id": identifier, "sha256": expected_hash, **result}
