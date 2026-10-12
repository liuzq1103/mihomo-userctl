"""User-level controller component; no global proxy or daemon.

V1 rule (architecture-v1.md): this bridge renders and never decides. Every
runtime, health, profile and lifecycle answer comes from the shared
``mihomoctl.app.Application`` instance injected as ``app``; this module no
longer re-enters the Bash CLI in a subprocess. When no application is injected
the caller gets an explicit UNVERIFIED document -- never a guessed success.
"""
import json
import contextlib
from functools import wraps
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
from mihomoctl.errors import MihomoctlError
from mihomoctl.envelope import Check, combine_checks
try:
    from . import acceptance, install_support as files
except ImportError:
    import acceptance
    import install_support as files
try:
    from .controller_types import ControlError, LIMIT, TEST_URL, label, number
    from .controller_health import annotate, affected_groups, health_candidate, observed
except ImportError:
    from controller_types import ControlError, LIMIT, TEST_URL, label, number
    from controller_health import annotate, affected_groups, health_candidate, observed

# Unit name used when neither the Application nor an owned legacy file names one.
DEFAULT_UNIT = "mihomo"
# The seven facts a V1 runtime view must always show, in display order.
RUNTIME_FIELDS = ("core", "controller", "listeners", "config", "proxy_mode", "tun", "error")
UNVERIFIED_REASON = "runtime-application-unavailable"

# Fixed, always-rendered boundaries. These keep a green console from being read
# as a stronger claim than the observation supports (architecture-v1.md
# "Integration and output contract"; design-reference.md 9).
HEALTH_LIMITS = (
    "readiness-is-not-model-e2e",
    "listener-presence-does-not-prove-ownership",
    "authenticated-probe-does-not-prove-a-remote-node",
    "node-selection-does-not-prove-one-request",
    "unobserved-socket-does-not-mean-a-direct-connection",
)
ENV_LIMITS = (
    "environment-is-inherited-at-process-creation-only",
    "environment-is-not-a-network-enforcement-policy",
    "existing-processes-need-an-operator-restart",
)


def field(source, *names, default=None):
    """Read the first present key/attribute from a dict or an object.

    The Application facade is frozen at the method level but its payload key
    names are not part of that contract. Reading tolerantly here keeps the
    console decoupled from a single spelling and keeps every miss explicit.
    """
    for name in names:
        if isinstance(source, dict):
            if name in source:
                return source[name]
        else:
            value = getattr(source, name, None)
            if value is not None:
                return value
    return default


def unavailable(reason, **extra):
    """One explicit UNVERIFIED document; callers never infer success from absence."""
    document = {"overall": "UNVERIFIED", "evidence": "unavailable", "reason": reason}
    document.update(extra)
    return document


def application_context(operation):
    """Carry the injected domain into worker threads and restore prior context."""
    @wraps(operation)
    def invoke(self, *args, **kwargs):
        if self.app is None:
            return operation(self, *args, **kwargs)
        try:
            from .controller_transaction import runtime_application
        except ImportError:
            from controller_transaction import runtime_application
        token = runtime_application.set(self.app)
        try:
            return operation(self, *args, **kwargs)
        except MihomoctlError as error:
            raise ControlError(error.code, error.exit_code) from error
        finally:
            runtime_application.reset(token)
    return invoke

def proxies(client):
    raw = client.request("/proxies", optional=True).get("proxies")
    if not isinstance(raw, dict):
        raise ControlError("controller-proxies-invalid")
    result = {}
    for name, item in raw.items():
        if not isinstance(item, dict):
            raise ControlError("controller-proxies-invalid")
        row = {"name": label(name), "type": label(item.get("type", "unknown"))}
        if type(item.get("alive")) is bool:
            row["alive"] = item["alive"]
        history = item.get("history")
        row["probe_observed"] = observed(history)
        # Private, transient evidence keyed by the group's own probe URL.
        # Generic alive can remain true for an HTTP response with rejected status.
        if isinstance(item.get("extra"), dict):
            row["_probe_states"] = item["extra"]
        if isinstance(item.get("testUrl"), str):
            row["_test_url"] = item["testUrl"]
        if isinstance(item.get("fixed"), str):
            row["fixed"] = label(item["fixed"])
        if "all" in item:
            if not isinstance(item["all"], list):
                raise ControlError("controller-proxies-invalid")
            row["members"] = [label(n) for n in item["all"]]
            row["selected"] = label(item["now"]) if item.get("now") else None
            row["selectable"] = row["type"] == "Selector"
        result[name] = row
    annotate(result)
    for row in result.values():
        row.pop("_probe_states", None)
        row.pop("_test_url", None)
    return result


def select(client, group, node):
    client.verify()
    rows = proxies(client)
    if group not in rows or not rows[group].get("selectable"):
        raise ControlError("selection-requires-Selector-group", 1)
    if node not in rows[group]["members"]:
        raise ControlError("node-not-in-group", 1)
    client.request("/proxies/" + quote(group, safe=""), "PUT", {"name": node}, optional=True)
    if proxies(client).get(group, {}).get("selected") != node:
        raise ControlError("selection-not-confirmed", 1)
    return {"group": group, "selected": node, "existing_connections": "unchanged",
            "affected_groups": affected_groups(rows, group)}


def snapshot(client, command, details=False, id_key=None):
    if command in ("nodes", "groups"):
        rows = proxies(client)
        return {command: [row for row in rows.values() if ("members" in row) == (command == "groups")]}
    if command == "traffic":
        raw = client.request("/traffic", stream=True, optional=True)
        return {k: number(raw.get(k, 0)) for k in ("up", "down", "upTotal", "downTotal")}
    raw = client.request("/connections", optional=True)
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

    ``app`` is the shared ``mihomoctl.app.Application``. It is optional so the
    retained Controller, subscription and policy assets stay usable on their own;
    runtime, health, profile and lifecycle answers are UNVERIFIED without it.
    """
    def __init__(self, config, home_dir=None, details=False, script=None, flclash=False, app=None):
        self.config = Path(config)
        self.home_dir, self.details = home_dir, details
        self.script, self.flclash = script, flclash
        self.app = app
        self._connection_key = secrets.token_bytes(32)
        self.pending_restart = False
        self.backup = None
        try:
            from .controller_transaction import pending_state
        except ImportError:
            from controller_transaction import pending_state
        try:
            receipt = pending_state(self.config)
            self.pending_restart = bool(receipt)
            self.backup = receipt.get("backup")
        except (ControlError, files.InstallError, OSError, ValueError, TypeError):
            pass

    def application(self):
        """Return the injected Application or state plainly that there is none."""
        return self.app

    def scope(self):
        return "system" if self.app is not None and field(self.app, "system", default=False) else "user"

    def legacy_lock(self):
        # Managed mutations hold the domain's scope lock. Never discover a root
        # system-operation lock from an inherited user's XDG environment.
        if self.app is not None:
            return contextlib.nullcontext()
        return files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))

    @application_context
    def initialize(self):
        try:
            from .controller_dashboard import initialize
        except ImportError:
            from controller_dashboard import initialize
        with self.legacy_lock():
            result = initialize(self.config, self.home_dir)
        return self.saved(result)

    def saved(self, result):
        if result.get("state") == "restart-required":
            self.pending_restart = True
            self.backup = result.get("backup")
        return result

    @application_context
    def restore(self):
        if not self.backup:
            raise ControlError("configuration-backup-unavailable")
        try:
            from .controller_config import read_config
            from .controller_transaction import apply_policy
        except ImportError:
            from controller_config import read_config
            from controller_transaction import apply_policy
        with self.legacy_lock():
            try:
                from .controller_transaction import pending_state
            except ImportError:
                from controller_transaction import pending_state
            receipt = pending_state(self.config)
            if not receipt or receipt.get("backup") != self.backup:
                raise ControlError("configuration-changed-restore-cancelled")
            original, _, _ = read_config(self.config)
            restored, _, _ = read_config(Path(self.backup))
            return self.saved(apply_policy(self.config, original, restored, self.home_dir))

    @application_context
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
        """Retained entry point name; V1 dispatches straight to the domain.

        No branch spawns the Bash CLI. Every answer comes from the injected
        Application, from the retained Controller bridge, or is reported
        UNVERIFIED with the reason attached.
        """
        if action in ("start", "stop", "restart"):
            return self.lifecycle(action)
        if action == "status":
            return self.runtime_document()
        if action in ("ready", "doctor", "health"):
            return self.health_document()
        if action in ("rules-status", "rules-check"):
            return self.rules(action.split("-")[1])
        if action in ("codex", "codex-diagnosis", "paseo", "paseo-preflight"):
            # Workload-specific diagnostics are retired. They map to the generic
            # health answer rather than to a third-party daemon probe.
            return dict(self.health_document(), retired_command=action,
                        guidance="use `mihomoctl health` and `mihomoctl status`")
        raise ControlError("invalid-runtime-action")

    def lifecycle(self, action):
        """Explicit start/stop/restart of the managed runtime only."""
        if action not in ("start", "stop", "restart"):
            raise ControlError("invalid-runtime-action")
        operation = field(self.app, "lifecycle") if self.app is not None else None
        if operation is None:
            value = unavailable(UNVERIFIED_REASON, action=action, state=UNVERIFIED_REASON,
                                changed=False, scope=self.scope())
        else:
            try:
                value = operation(action)
            except MihomoctlError as error:
                # Retained console backends handle ControlError; keep the domain
                # code/exit result, without forwarding private exception details.
                raise ControlError(error.code, error.exit_code) from error
        if action in ("start", "restart"):
            # The receipt describes the configuration file, not the service, so
            # it is re-read as a fact even when no Application ran the action.
            try:
                from .controller_transaction import pending_state
            except ImportError:
                from controller_transaction import pending_state
            try:
                self.pending_restart = bool(pending_state(self.config))
            except (ControlError, files.InstallError, OSError, ValueError, TypeError):
                pass
            if not self.pending_restart:
                self.backup = None
        return dict(value, action=action, shell="unchanged")

    def runtime_document(self):
        """Normalized V1 runtime status: the seven required facts, always present."""
        blank = dict(scope=self.scope(), backend="unknown", **{key: None for key in RUNTIME_FIELDS})
        if self.app is None:
            return unavailable(UNVERIFIED_REASON, **blank)
        try:
            value = self.app.status()
        except (MihomoctlError, ControlError, files.InstallError, OSError, ValueError, TypeError, KeyError) as error:
            return unavailable(getattr(error, "code", "status-unavailable"), **blank)
        return self.normalize_status(value)

    def normalize_status(self, value):
        """Project an Application status payload onto the fixed display contract.

        Rendering never decides a verdict: ``overall`` and ``evidence`` are carried
        through, and a missing fact renders UNVERIFIED rather than a reassuring
        default.
        """
        listeners = field(value, "listeners", "listener", default=None)
        if isinstance(listeners, dict):
            listeners = [listeners]
        if not isinstance(listeners, list):
            listeners = []
        tun = field(value, "tun", default=None)
        tun = dict(tun) if isinstance(tun, dict) else {"state": "unknown"}
        tun.setdefault("state", ("enabled" if tun["enabled"] else "disabled")
                       if type(tun.get("enabled")) is bool else "unknown")
        error = field(value, "error", "errors", default=None)
        if isinstance(error, list):
            error = {"code": "; ".join(str(item) for item in error)} if error else None
        elif isinstance(error, dict):
            error = dict(error)
        elif error:
            error = {"code": str(error)}
        else:
            error = None
        overall = str(field(value, "overall", "state", default="UNVERIFIED")).upper()
        if overall not in ("PASS", "FAIL", "UNVERIFIED", "BLOCKED", "SKIPPED"):
            overall = "UNVERIFIED"
        evidence = str(field(value, "evidence", default="inferred"))
        if evidence not in ("confirmed", "inferred", "unavailable"):
            evidence = "inferred"
        core = field(value, "core", default=None)
        if isinstance(core, dict):
            core = dict(core)
            runtime = field(value, "runtime", default=None)
            if isinstance(runtime, dict):
                for key in ("running", "listening"):
                    if type(runtime.get(key)) is bool:
                        core[key] = runtime[key]
        return {
            "scope": str(field(value, "scope", default=self.scope())),
            "backend": str(field(value, "backend", default="unknown")),
            "overall": overall,
            "evidence": evidence,
            "core": core,
            "controller": field(value, "controller", default=None),
            "listeners": listeners,
            "config": field(value, "config", "active_config", default=None),
            "proxy_mode": str(field(value, "proxy_mode", "mode", default="unknown")),
            "routing_mode": field(value, "routing_mode", "mode", default="unknown"),
            "tun": tun,
            "error": error,
        }

    def health_document(self, profile=None, egress_url=None):
        """Generic runtime health. No workload-specific branch exists here."""
        if self.app is None:
            return unavailable(UNVERIFIED_REASON, scope=self.scope(), checks=[],
                               limits=list(HEALTH_LIMITS))
        try:
            try:
                checks = self.app.health(profile=profile, egress_url=egress_url)
            except TypeError:
                checks = self.app.health()
        except (MihomoctlError, ControlError, files.InstallError, OSError, ValueError, TypeError, KeyError) as error:
            return unavailable(getattr(error, "code", "health-unavailable"),
                               scope=self.scope(), checks=[], limits=list(HEALTH_LIMITS))
        return self.normalize_health(checks)

    def normalize_health(self, checks):
        if isinstance(checks, dict):
            rows = field(checks, "checks", default=None)
            rows = rows if isinstance(rows, list) else []
            overall = str(field(checks, "overall", default="UNVERIFIED")).upper()
            limits = field(checks, "limits", default=None)
        else:
            rows, overall, limits = (checks if isinstance(checks, list) else []), "UNVERIFIED", None
            if rows and all(isinstance(row, Check) for row in rows):
                # Use the shared domain aggregation, never a separate UI policy.
                overall = combine_checks(rows)
        normalized = []
        for row in rows:
            if not isinstance(row, (dict, Check)):
                continue
            status = str(field(row, "status", "state", default="UNVERIFIED")).upper()
            if status not in ("PASS", "FAIL", "UNVERIFIED", "SKIPPED", "BLOCKED"):
                status = "UNVERIFIED"
            evidence = str(field(row, "evidence", default="unavailable"))
            if evidence not in ("confirmed", "inferred", "unavailable"):
                evidence = "unavailable"
            normalized.append({"name": str(field(row, "name", "id", default="check")),
                               "status": status, "evidence": evidence,
                               "detail": str(field(row, "detail", "message", default=""))})
        if overall not in ("PASS", "FAIL", "UNVERIFIED", "BLOCKED", "SKIPPED"):
            overall = "UNVERIFIED"
        return {"overall": overall, "scope": self.scope(), "checks": normalized,
                "limits": limits if isinstance(limits, list) else list(HEALTH_LIMITS)}

    def profiles_document(self):
        """Redacted proxy profiles plus the binding descriptions of this scope."""
        if self.app is None:
            return unavailable(UNVERIFIED_REASON, scope=self.scope(), profiles=[], bindings=[])
        try:
            profiles = field(self.app, "profiles", default=None)
            profiles = profiles() if callable(profiles) else profiles
        except (MihomoctlError, ControlError, files.InstallError, OSError, ValueError, TypeError, KeyError) as error:
            return unavailable(getattr(error, "code", "profiles-unavailable"),
                               scope=self.scope(), profiles=[], bindings=[])
        rows = profiles.values() if isinstance(profiles, dict) else (profiles or [])
        context = field(self.app, "context", default=None)
        default_profile = field(context, "default_profile", "profile", default=None)
        default_profile = str(default_profile) if default_profile else None
        normalized, selected = [], None
        for row in rows:
            if isinstance(row, str):
                row = {"name": row}
            if not isinstance(row, dict):
                continue
            name = str(field(row, "name", default=""))
            if not name:
                continue
            is_selected = bool(default_profile) and name == default_profile
            selected = name if is_selected else selected
            listeners = field(row, "listeners", default=None)
            if listeners is None:
                listeners = list(dict.fromkeys(item for item in (
                    field(row, "http_listener"), field(row, "socks_listener")) if item))
            elif isinstance(listeners, str):
                listeners = [listeners]
            normalized.append({"name": name,
                               "listeners": listeners if isinstance(listeners, list) else [],
                               "no_proxy": field(row, "no_proxy", default=[]),
                               "credentials": "external-private-file",
                               "selected": is_selected})
        bindings = field(context, "bindings", default=None)
        return {"overall": "PASS", "scope": self.scope(), "profiles": normalized,
                "selected": selected,
                "bindings": bindings if isinstance(bindings, dict) else {},
                "environment": list(ENV_LIMITS)}

    def rules(self, subcommand):
        """Read-only custom-rule contract check, executed in process.

        ``rules.py`` owns the parsing and the ownership policy. This only builds
        a display payload from its results, so the console never prints onto the
        terminal itself and never re-enters the Bash CLI.
        """
        if subcommand not in ("status", "check"):
            raise ControlError("invalid-runtime-action")
        try:
            from . import rules as rules_module
        except ImportError:
            import rules as rules_module
        arguments = type("RuleArguments", (), {"home_dir": self.home_dir, "config": str(self.config)})()
        try:
            home, config = rules_module.resolve_paths(arguments)
            rules_module.inspect_owned(home / "rules", 0o700, "rules-directory")
            files = [rules_module.file_status(home / "rules" / name) for name in rules_module.FILES]
        except rules_module.RuleError as error:
            return {"overall": "UNVERIFIED", "command": "rules-" + subcommand,
                    "error": {"code": error.code}, "read_only": True}
        rows = [{"name": item["name"], "status": item["status"],
                 "rules": item.get("rules"), "sha256": item.get("sha256"),
                 "modified": item.get("modified_utc"), "error": item.get("error")}
                for item in files]
        overall = ("FAIL" if any(item["status"] == "FAIL" for item in files) else
                   "UNVERIFIED" if any(item["status"] == "UNVERIFIED" for item in files) else "PASS")
        document = {"overall": overall, "command": "rules-" + subcommand, "files": rows,
                    "read_only": True, "writes": "none"}
        if subcommand == "check" and overall == "PASS":
            try:
                document["fallback"] = "present" if not rules_module.parse_config(config) else "absent"
                rules_module.config_test(rules_module.find_mihomo(), home, config)
                document["mihomo-config-test"] = "PASS"
            except rules_module.RuleError as error:
                document["mihomo-config-test"] = "FAIL"
                document["error"] = {"code": error.code}
                document["overall"] = "FAIL"
        return document

    @application_context
    def read(self, page):
        if page == "overview":
            try:
                client = self.client()
            except (ControlError, OSError) as error:
                return {"controller": "unavailable", "error": getattr(error, "code", "config-missing"),
                        "pending_restart": self.pending_restart, "groups": []}
            value = {"controller": "connected", "authentication": "PASS", "listener": "PASS",
                     "core": label(client.request("/version").get("version", "unknown")),
                     "pending_restart": self.pending_restart, "capabilities": {}}
            for key, operation in (("groups", lambda: snapshot(client, "groups")["groups"]),
                                   ("connections", lambda: len(snapshot(client, "connections")["connections"])),
                                   ("mode", lambda: label(client.request("/configs", optional=True).get("mode", "unknown")))):
                try:
                    value[key] = operation()
                except ControlError as error:
                    value["capabilities"][key] = error.code
            return value
        if page == "runtime":
            return self.runtime_document()
        if page == "diagnostics":
            # Generic runtime health plus the fixed evidence boundaries. The
            # retired workload-specific probes map here and add no branches.
            document = self.health_document()
            document["guidance"] = "health applies to the runtime only; : health refreshes"
            return document
        if page == "profile":
            # Resolved from manager.yaml, so it stays available even when the
            # controller is not configured yet.
            return self.profiles_document()
        if page in ("subscriptions", "profiles"):
            # "profiles" is the retained identifier of the subscription page.
            # V1 reserves the word for ProxyProfile, so the console canonical
            # page is "subscriptions"; the old key keeps working for callers.
            try:
                from .controller_config import read_config
            except ImportError:
                from controller_config import read_config
            if not self.config.exists():
                return {"configuration": "missing", "nodes": 0, "groups": 0,
                        "service": "Create a private Mihomo config first"}
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
        """Read-only, current-user-only process or target diagnosis, in process.

        The same-UID restriction and the evidence policy stay owned by
        ``diagnostics.py``; this only adapts its pure readers for the console and
        strips control characters before anything can reach a widget.
        """
        if kind == "url":
            if not acceptance.public_https_url(target):
                raise ControlError("diagnosis-requires-public-https-without-credentials-or-query", 1)
            return self.health_document(egress_url=target)
        if kind == "process":
            if not re.fullmatch(r"[1-9][0-9]{0,19}", target):
                raise ControlError("invalid-pid", 1)
        elif kind == "name":
            if (not target or len(target) > 64 or "/" in target
                    or any(ord(char) < 32 or ord(char) == 127 for char in target)):
                raise ControlError("invalid-process-name")
        else:
            raise ControlError("invalid-diagnosis-kind")
        expected = self.expected_proxy_environment()
        if kind == "process":
            try:
                from . import diagnostics
            except ImportError:
                import diagnostics
            item = diagnostics.inspect(Path("/proc"), int(target), self.proxy_port(), expected=expected)
            return {"overall": "PASS", "scope": "current-user-only",
                    "process": self.project(item)}
        return self.named_processes(target, expected=expected)

    @staticmethod
    def project(item):
        """Strip terminal control characters from any diagnostic payload."""
        if isinstance(item, str):
            return "".join(char if unicodedata.category(char) not in ("Cc", "Cf") else " " for char in item)
        if isinstance(item, list):
            return [ConsoleService.project(child) for child in item]
        if isinstance(item, dict):
            return {key: ConsoleService.project(child) for key, child in item.items()}
        return item


    def named_processes(self, target, expected=None):
        """Enumerate exact-name matches of the current user; never by prefix."""
        try:
            from . import diagnostics
        except ImportError:
            import diagnostics
        root, uid, matches, unverified = Path("/proc"), os.getuid(), [], 0
        try:
            candidates = sorted((entry for entry in root.iterdir() if entry.name.isdigit()),
                                key=lambda entry: int(entry.name))
        except OSError:
            raise ControlError("proc-unavailable") from None
        for entry in candidates:
            try:
                owner, _ = diagnostics.read_status(root, int(entry.name))
                if owner != uid:
                    continue
                if (entry / "comm").read_text(errors="strict").rstrip("\n") != target:
                    continue
                try:
                    matches.append(diagnostics.inspect(root, int(entry.name), self.proxy_port(), uid=uid,
                                                       expected=expected))
                except diagnostics.DiagnosticError:
                    unverified += 1
            except (diagnostics.DiagnosticError, OSError, UnicodeError):
                continue
        return {"overall": "UNVERIFIED" if unverified else "PASS" if matches else "FAIL",
                "processes": matches, "unverified_matches": unverified,
                "scope": "current-user-only"}

    def proxy_port(self):
        """Observed listener port; falls back to 0 so no check silently passes."""
        try:
            return self.proxy_endpoint()[0]
        except (ControlError, OSError, ValueError):
            return 0

    @application_context
    def expected_proxy_environment(self):
        """Pass private expectations directly; never mutate thread-shared env."""
        return self.app.proxy_environment().variables() if self.app is not None else None

    @application_context
    def proxy_endpoint(self):
        if self.app is not None:
            _manager, endpoints, _controller, profile, _config = self.app.resolve()
            name = profile.http_listener or profile.socks_listener
            endpoint = next(item for item in endpoints if item.name == name)
            return endpoint.port, endpoint.address
        try:
            from .controller_config import read_config, endpoint
        except ImportError:
            from controller_config import read_config, endpoint
        _, data, _ = read_config(self.config)
        if not isinstance(data, dict):
            raise ControlError("config-must-be-mapping")
        port = data.get("mixed-port")
        if type(port) is not int or not 1024 <= port <= 65535:
            port = field(self.app, "proxy_port", default=None) if self.app is not None else None
        if type(port) is not int or not 1024 <= port <= 65535:
            raise ControlError("proxy-listener-unavailable")
        if any(data.get(key) for key in ("allow-lan", "bind-address")) and not str(
                data.get("bind-address", "")).startswith("127."):
            raise ControlError("proxy-listener-not-loopback")
        endpoint(data)
        return port, "127.0.0.1"

    @application_context
    def proxy_credential(self):
        if self.app is not None:
            profile = self.app.resolve()[3]
            credentials = self.app.credentials(profile)
            if credentials is None:
                raise ControlError("proxy-authentication-unavailable")
            return credentials.username + ":" + credentials.password
        try:
            from .controller_config import read_config
        except ImportError:
            from controller_config import read_config
        _, data, _ = read_config(self.config)
        entries = data.get("authentication") or []
        if not isinstance(entries, list) or not entries:
            raise ControlError("proxy-authentication-unavailable")
        first = entries[0]
        if not isinstance(first, str) or ":" not in first:
            raise ControlError("proxy-authentication-unavailable")
        return first


    def choose(self, group, node):
        return select(self.client(), group, node)

    def latency(self, node):
        client = self.client()
        if node not in proxies(client):
            raise ControlError("unknown-node", 1)
        raw = client.request("/proxies/" + quote(node, safe="") + "/delay?" +
                             urlencode({"url": TEST_URL, "timeout": 5000}), optional=True)
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

    @application_context
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

    @application_context
    def journal(self, since=None, until=None, lines=200):
        """Current-user service journal, read directly without the Bash CLI."""
        if type(lines) is not int or not 1 <= lines <= 10000:
            raise ControlError("invalid-journal-lines")
        filters = []
        for flag, value in (("--since", since), ("--until", until)):
            if value is not None:
                if not isinstance(value, str) or not value or len(value) > 128 or any(ord(c) < 32 for c in value):
                    raise ControlError("invalid-journal-time")
                filters.extend([flag, value])
        if self.app is not None and self.app.load_manager().core.backend != "systemd":
            raise ControlError("journal-unavailable-for-process-backend")
        command = ["journalctl", *([] if self.scope() == "system" else ["--user"]), "--unit", self.service_unit(), "--no-pager",
                   "--output=json", "--lines", str(lines)] + filters
        try:
            result = subprocess.run(command, env=acceptance.clean_environment(),
                                    capture_output=True, timeout=8)
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
        return {"source": "current-user-service-journal", "unit": self.service_unit(),
                "entries": rows,
                "state": "records" if rows else "no-records-in-window",
                "retention": "controlled-by-server-journal-configuration"}

    def service_unit(self):
        """Managed unit name: the Application, then the owned legacy file, then
        the documented default.

        The default matches the name the published configuration seeded before
        parsing, so an installation without an explicit unit keeps working.
        """
        context = field(self.app, "context", default=None) if self.app is not None else None
        if self.app is not None:
            from mihomoctl.app import UNIT_NAME
            return UNIT_NAME
        for key in ("service_unit", "unit"):
            unit = field(context, key, default=None)
            if isinstance(unit, str) and re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", unit):
                return unit
        legacy = Path(os.environ.get("MIHOMO_USERCTL_CONFIG") or
                      (Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
                       / "mihomo" / "mihomo-shell.conf"))
        try:
            files.safe_path(legacy)
            for line in legacy.read_text(errors="strict").splitlines():
                if line.startswith("MIHOMO_SERVICE="):
                    value = line.split("=", 1)[1].strip().strip("'\"")
                    if re.fullmatch(r"[A-Za-z0-9_.@-]{1,64}", value):
                        return value
        except (ControlError, files.InstallError, OSError, UnicodeError, ValueError):
            pass
        return DEFAULT_UNIT


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

    @application_context
    def policy(self, group=None, apply=False):
        try:
            from .controller_policy import policy_candidate
            from .controller_transaction import apply_policy
        except ImportError:
            from controller_policy import policy_candidate
            from controller_transaction import apply_policy
        with self.legacy_lock():
            if apply:
                if not getattr(self, "_policy", None):
                    raise ControlError("policy-preview-required")
                original, updated, result = self._policy
                self._policy = None
                return self.saved(dict(result, **apply_policy(self.config, original, updated, self.home_dir)))
            original, updated, result = policy_candidate(self.config, group=group,
                    script=None if group else self.script, flclash=self.flclash, home_dir=self.home_dir)
            self._policy = (original, updated, result)
            return result

    @application_context
    def health_check(self, scope=None, name=None, options=None, apply=False):
        try:
            from .controller_transaction import apply_policy
        except ImportError:
            from controller_transaction import apply_policy
        with self.legacy_lock():
            if apply:
                if not getattr(self, "_health_preview", None):
                    raise ControlError("health-check-preview-required")
                original, updated, result = self._health_preview
                self._health_preview = None
                return self.saved(dict(result, **apply_policy(self.config, original, updated, self.home_dir)))
            self._health_preview = None
            original, updated, result = health_candidate(self.config, scope, name, options)
            if result["state"] == "preview":
                self._health_preview = (original, updated, result)
            return result

    @application_context
    def subscription_preview(self, path, url=False, policy="auto"):
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        return Subscriptions(self.config, self.home_dir).preview(policy=policy, **{"url_file" if url else "source_file": path})

    @application_context
    def subscription_apply(self, identifier, digest):
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        return self.saved(Subscriptions(self.config, self.home_dir).apply(identifier, digest))
