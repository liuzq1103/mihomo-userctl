"""User-level controller component; no global proxy or daemon."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
try:
    from . import acceptance
except ImportError:
    import acceptance
try:
    from .controller_types import ControlError, LIMIT, label
    from .controller_config import private, read_config, patch_config
except ImportError:
    from controller_types import ControlError, LIMIT, label
    from controller_config import private, read_config, patch_config

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
