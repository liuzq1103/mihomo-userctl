"""Existing routing-chain evidence and explicit, scoped probe configuration."""
import argparse
import copy
import re
import shlex
from collections import deque

try:
    from . import probes as acceptance
    from .controller_config import read_config, patch_config
    from .controller_types import ControlError, TEST_URL, LIMIT, label
except ImportError:
    import probes as acceptance
    from controller_config import read_config, patch_config
    from controller_types import ControlError, TEST_URL, LIMIT, label

FIELDS = ("url", "expected-status", "interval", "timeout", "lazy", "tolerance")
AUTO_TYPES = ("URLTest", "Fallback")
EVIDENCE_LABELS = {
    "missing-member-references": "分组引用的节点不在核心代理表中：订阅或提供商尚未加载，或上游已重命名节点",
    "complete": "链路完整", "cycle": "存在循环引用", "missing-reference": "引用对象缺失",
    "unknown-selection": "当前选择未知", "selection-not-in-members": "当前选择不在候选列表",
    "unknown": "尚无法判断", "observed-success": "曾观测到探测成功",
    "all-observed-failed": "全部已观测探测失败", "no-probe-records": "没有探测记录",
    "automatic-fixed-selection": "自动组存在固定选择",
    "manual-path-bypasses-automatic": "当前手动路径绕过了已有自动组",
    "manual-path-no-automatic-candidate": "当前手动路径没有可选自动组",
}


def settings(value):
    """Safe DTO: imported probe URLs may contain account-specific tokens."""
    result = {key: value[key] for key in FIELDS if key in value}
    if "enable" in value:
        result["enable"] = value["enable"]
    if "url" in result and not acceptance.public_https_url(result["url"]):
        result["url"] = "[redacted: non-public-or-credential-url]"
    return result


def probe_overwrites(before, after):
    result = []
    old_groups = {g.get("name"): g for g in before.get("proxy-groups", []) if isinstance(g, dict)}
    new_groups = {g.get("name"): g for g in after.get("proxy-groups", []) if isinstance(g, dict)}
    for name, old in old_groups.items():
        new = new_groups.get(name, {})
        if {k: old[k] for k in FIELDS if k in old} != {k: new[k] for k in FIELDS if k in new}:
            result.append({"scope": "group", "name": label(name), "before": settings(old), "after": settings(new)})
    for name, old in before.get("proxy-providers", {}).items():
        if not isinstance(old, dict):
            continue
        previous = old.get("health-check", {})
        current = after.get("proxy-providers", {}).get(name, {}).get("health-check", {})
        if previous != current:
            result.append({"scope": "provider", "name": label(name), "before": settings(previous), "after": settings(current)})
    return result


def selected_chain(rows, start):
    chain, seen, name = [], set(), start
    while True:
        if name in seen:
            return chain + [name], "cycle"
        seen.add(name)
        chain.append(name)
        row = rows.get(name)
        if row is None:
            return chain, "missing-reference"
        if "members" not in row:
            return chain, "complete"
        name = row.get("selected")
        if not name:
            return chain, "unknown-selection"
        if name not in row["members"]:
            return chain + [name], "selection-not-in-members"


def automatic_candidates(rows, start):
    """One shortest existing path per automatic group, without exponential walks."""
    queue, seen, result = deque([(start, [start])]), {start}, []
    while queue:
        name, path = queue.popleft()
        row = rows.get(name, {})
        if row.get("type") in AUTO_TYPES:
            result.append({"group": name, "path": path})
            continue
        # Only selector edges are actions the user can actually perform.
        if row.get("selectable"):
            for child in row.get("members", []):
                if child not in seen:
                    seen.add(child)
                    queue.append((child, path + [child]))
    return result


def affected_groups(rows, group):
    return sorted(name for name, row in rows.items() if name != group and "members" in row
                  and group in selected_chain(rows, name)[0][1:])


def observed(history):
    return (isinstance(history, list) and bool(history) and isinstance(history[-1], dict)
            and type(history[-1].get("delay")) is int and 0 <= history[-1]["delay"] <= 65535)


def annotate(rows):
    for name, row in rows.items():
        if "members" not in row:
            continue
        chain, state = selected_chain(rows, name)
        candidates = automatic_candidates(rows, name)
        automatic = [n for n in chain if rows.get(n, {}).get("type") in AUTO_TYPES]
        warnings = [] if state == "complete" else [state]
        missing = [member for member in row["members"] if member not in rows]
        row.update(missing_members=missing[:5], missing_member_count=len(missing))
        if missing:
            warnings.append("missing-member-references")
        if row.get("selectable") and not automatic and state == "complete":
            warnings.append("manual-path-bypasses-automatic" if candidates else "manual-path-no-automatic-candidate")
        if row.get("fixed"):
            warnings.append("automatic-fixed-selection")
        health = "unknown"
        if row.get("type") in AUTO_TYPES:
            members = [rows.get(n, {}) for n in row["members"]]
            if row.get("_test_url"):
                states = [m.get("_probe_states", {}).get(row["_test_url"], {}) for m in members]
                members = [{"alive": state.get("alive"), "probe_observed": observed(state.get("history"))}
                           if isinstance(state, dict) else {} for state in states]
            tested = [m for m in members if m.get("probe_observed")]
            if not tested:
                warnings.append("no-probe-records")
            elif members and len(tested) == len(members) and all(m.get("alive") is False for m in tested):
                health = "all-observed-failed"
                warnings.append(health)
            elif any(m.get("alive") is True for m in tested):
                health = "observed-success"
        row.update(selection_chain=chain, chain_state=state, automatic_groups=automatic,
                   automatic_candidates=candidates, affected_groups=affected_groups(rows, name),
                   probe_state=health, warnings=warnings)
    for row in rows.values():
        if "members" in row:
            row["automatic_evidence"] = [{"group": name, "probe_state": rows[name]["probe_state"],
                                          "warnings": rows[name]["warnings"]}
                                         for name in row["automatic_groups"]]
    return rows


def guidance(row):
    """Shared plain-language view for both interactive frontends."""
    lines = ["当前链路：" + " → ".join(row.get("selection_chain", [])),
             "链路状态：" + EVIDENCE_LABELS.get(row.get("chain_state"), "尚无法判断") + "；探测仅代表已观测结果，不保证业务可用。"]
    if row.get("warnings"):
        lines.append("提示：" + "；".join(EVIDENCE_LABELS.get(w, w) for w in row["warnings"]))
    if row.get("missing_member_count"):
        lines.append("缺失引用 {} 个：{}".format(row["missing_member_count"], ", ".join(row["missing_members"])))
    for evidence in row.get("automatic_evidence", []):
        lines.append("自动组 {}：{}；{}".format(evidence["group"], EVIDENCE_LABELS.get(evidence["probe_state"], "尚无法判断"),
                                            "；".join(EVIDENCE_LABELS.get(w, w) for w in evidence["warnings"])))
    for candidate in row.get("automatic_candidates", []):
        lines.append("已有自动路径：" + " → ".join(candidate["path"]) + "（逐个选择入口并核对）")
    if row.get("affected_groups"):
        lines.append("共享当前入口的分组：" + ", ".join(row["affected_groups"]))
    return lines


def add_probe_options(parser):
    from mihomoctl.command_spec import PROBE_OPTIONS
    for name, kwargs in PROBE_OPTIONS:
        parser.add_argument(name, **kwargs)


def probe_options(args):
    return {key: getattr(args, key.replace("-", "_")) for key in FIELDS + ("preset",)
            if getattr(args, key.replace("-", "_")) is not None}


def parse_console(command):
    """No shell evaluation; configuration saves use the regular preview action."""
    class QuietParser(argparse.ArgumentParser):
        def error(self, message):
            raise ControlError("invalid-health-check-options")
    parser = QuietParser(add_help=False)
    parser.add_argument("scope", choices=("group", "provider"))
    parser.add_argument("name")
    add_probe_options(parser)
    try:
        args = parser.parse_args(shlex.split(command))
    except ValueError:
        raise ControlError("invalid-health-check-options") from None
    return args.scope, args.name, probe_options(args)


def health_candidate(config, scope, name, options=None):
    original, data, tree = read_config(config)
    options = dict(options or {})
    if scope not in ("group", "provider") or set(options) - set(FIELDS + ("preset",)):
        raise ControlError("invalid-health-check-options")
    label(name)
    groups = copy.deepcopy(data.get("proxy-groups", []))
    providers = copy.deepcopy(data.get("proxy-providers", {}))
    if not isinstance(groups, list) or not isinstance(providers, dict):
        raise ControlError("config-policy-shape-invalid")
    if scope == "group":
        found = [g for g in groups if isinstance(g, dict) and g.get("name") == name]
        if len(found) != 1 or found[0].get("type") not in ("url-test", "fallback"):
            raise ControlError("health-check-requires-existing-automatic-group", 1)
        target, section = found[0], "proxy-groups"
    else:
        provider = providers.get(name)
        if not isinstance(provider, dict):
            raise ControlError("health-check-provider-missing", 1)
        target = provider.setdefault("health-check", {})
        if not isinstance(target, dict):
            raise ControlError("health-check-provider-settings-invalid")
        section = "proxy-providers"
    before = copy.deepcopy(target)
    preset = options.pop("preset", None)
    updates = {}
    if preset:
        if preset != "resilient":
            raise ControlError("invalid-health-check-preset")
        updates = {"url": TEST_URL, "expected-status": "204", "interval": 120, "timeout": 5000, "lazy": False}
        if scope == "provider":
            updates["enable"] = True
        elif target["type"] == "url-test":
            updates["tolerance"] = 50
    updates.update(options)
    if "url" in updates and not acceptance.public_https_url(updates["url"]):
        raise ControlError("health-check-requires-public-https-without-credentials-or-query", 1)
    for key in ("interval", "timeout", "tolerance"):
        if key in updates and (type(updates[key]) is not int or not (0 if key == "tolerance" else 1) <= updates[key] <= (65535 if key == "tolerance" else 2147483647)):
            raise ControlError("invalid-health-check-" + key, 1)
    if "tolerance" in updates and (scope != "group" or target.get("type") != "url-test"):
        raise ControlError("tolerance-requires-url-test-group", 1)
    if "lazy" in updates:
        if updates["lazy"] in ("true", "false"):
            updates["lazy"] = updates["lazy"] == "true"
        elif type(updates["lazy"]) is not bool:
            raise ControlError("invalid-health-check-lazy", 1)
    if "expected-status" in updates:
        status = str(updates["expected-status"])
        if not re.fullmatch(r"[1-5][0-9]{2}(?:-[1-5][0-9]{2})?(?:/[1-5][0-9]{2}(?:-[1-5][0-9]{2})?)*", status):
            raise ControlError("invalid-health-check-expected-status", 1)
        if any(int(part.split("-")[0]) > int(part.split("-")[-1]) for part in status.split("/")):
            raise ControlError("invalid-health-check-expected-status", 1)
        updates["expected-status"] = status
    target.update(updates)
    changed = before != target
    updated = patch_config(original, tree, {section: groups if scope == "group" else providers}) if changed else original
    if len(updated.encode()) > LIMIT:
        raise ControlError("config-too-large")
    references = ([g.get("name") for g in groups if isinstance(g, dict) and name in g.get("use", [])]
                  if scope == "provider" else [])
    probe_providers = ({p: settings(providers[p].get("health-check", {})) for p in target.get("use", []) if p in providers}
                       if scope == "group" else {})
    result = {"kind": "health-check", "scope": scope, "name": name,
              "state": "preview" if changed else "unchanged", "service": "unchanged",
              "before": settings(before), "after": settings(target), "affected_groups": references,
              "provider_settings": probe_providers,
              "warnings": (["provider-scheduling-may-control-use-members"] if probe_providers else [])}
    if scope == "provider":
        result["before"]["enable"] = before.get("enable", False)
        result["after"]["enable"] = target.get("enable", False)
        result["warnings"].append("shared-provider-probes-affect-referencing-groups")
        if updates and not target.get("enable"):
            result["warnings"].append("provider-health-check-disabled-use-resilient-preset-to-enable")
    return original, updated, result
