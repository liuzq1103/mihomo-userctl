#!/usr/bin/env python3
"""Read-only checks for the documented local custom-rule contract."""

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

try:
    from . import reporting
except ImportError:  # Installed modules are executed from one runtime directory.
    import reporting


SCHEMA = reporting.RULES_SCHEMA
MAX_FILE = 4 * 1024 * 1024
MAX_RULES = 100000
FILES = ("custom-direct.yaml", "custom-proxy.yaml", "custom-reject.yaml")
PROVIDERS = {
    "custom-direct": ("custom-direct.yaml", "DIRECT"),
    "custom-proxy": ("custom-proxy.yaml", "Proxy"),
    "custom-reject": ("custom-reject.yaml", "REJECT"),
}


class RuleError(Exception):
    def __init__(self, code, usage=False):
        self.code = code
        self.usage = usage
        super().__init__(code)


class Parser(argparse.ArgumentParser):
    def error(self, _message):
        raise RuleError("invalid-options", True)


def safe_absolute(raw, label):
    path = Path(raw)
    if (not path.is_absolute() or ".." in path.parts
            or any(ord(char) < 32 or ord(char) == 127 for char in str(path))):
        raise RuleError(label + "-must-be-safe-absolute-path", True)
    current = path
    while current != current.parent:
        if current.is_symlink():
            raise RuleError(label + "-symlink-not-supported")
        current = current.parent
    return path


def inspect_owned(path, expected_mode, kind):
    try:
        info = path.lstat()
    except OSError:
        raise RuleError(kind + "-missing-or-unreadable") from None
    if stat.S_ISLNK(info.st_mode):
        raise RuleError(kind + "-symlink-not-supported")
    expected_type = stat.S_ISDIR if kind == "rules-directory" else stat.S_ISREG
    if not expected_type(info.st_mode):
        raise RuleError(kind + "-wrong-type")
    if info.st_uid != os.getuid():
        raise RuleError(kind + "-not-owned-by-current-user")
    if stat.S_IMODE(info.st_mode) != expected_mode:
        raise RuleError(kind + "-mode-must-be-" + format(expected_mode, "o"))
    return info


def digest(data):
    return hashlib.sha256(data).hexdigest()


def parse_rule_file(path):
    info = inspect_owned(path, 0o600, "rule-file")
    if info.st_size > MAX_FILE:
        raise RuleError("rule-file-size-limit-exceeded")
    try:
        data = path.read_bytes()
        text = data.decode("utf-8")
    except (OSError, UnicodeError):
        raise RuleError("rule-file-must-be-utf8") from None
    if "\0" in text or "\t" in text:
        raise RuleError("rule-file-unsupported-yaml")
    payload = 0
    count = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line == "payload:":
            payload += 1
            continue
        if payload == 1 and re.fullmatch(r" {0,8}-[ ]+[^#\s].*", line):
            item = line.split("-", 1)[1].lstrip()
            if item.startswith(("[", "{", "&", "*", "!", "<<:")):
                raise RuleError("rule-file-unsupported-yaml")
            count += 1
            if count > MAX_RULES:
                raise RuleError("rule-count-limit-exceeded")
            continue
        raise RuleError("rule-file-unsupported-yaml")
    if payload != 1 or count == 0:
        raise RuleError("rule-file-invalid-payload")
    return {"name": path.name, "exists": True, "rules": count,
            "sha256": digest(data),
            "modified_utc": datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
            "mode": "600", "status": "PASS"}


def file_status(path):
    try:
        return parse_rule_file(path)
    except RuleError as error:
        exists = path.exists() and not path.is_symlink()
        return {"name": path.name, "exists": exists, "rules": None, "sha256": None,
                "modified_utc": None, "mode": None,
                "status": "UNVERIFIED" if "unsupported" in error.code else "FAIL",
                "error": error.code}


def strip_comment(line):
    quote = None
    escaped = False
    result = []
    for index, char in enumerate(line):
        if quote == '"' and char == "\\" and not escaped:
            escaped = True
            result.append(char)
            continue
        if char in ("'", '"') and not escaped:
            quote = None if quote == char else char if quote is None else quote
        if char == "#" and quote is None and (index == 0 or line[index - 1].isspace()):
            break
        result.append(char)
        escaped = False
    if quote is not None:
        raise RuleError("config-unsupported-yaml")
    return "".join(result).rstrip()


def scalar(value):
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    if not value or any(char in value for char in "{}[]&!\t\r\n") or value.startswith("*"):
        raise RuleError("config-unsupported-yaml")
    return value


def parse_config(path):
    inspect_owned(path, 0o600, "config-file")
    try:
        if path.stat().st_size > MAX_FILE:
            raise RuleError("config-size-limit-exceeded")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise RuleError("config-must-be-utf8") from None
    section = None
    current_provider = None
    providers = {}
    groups = set()
    routed = []
    fallback = False
    for raw in lines:
        line = strip_comment(raw)
        if not line.strip():
            continue
        if "\t" in line:
            raise RuleError("config-unsupported-yaml")
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()
        if indent == 0 and re.match(r"(?:rule-providers|proxy-groups|rules):[ ]+\S", content):
            raise RuleError("config-unsupported-yaml")
        top = re.fullmatch(r"([A-Za-z0-9_-]+):", content) if indent == 0 else None
        if top:
            section = top.group(1)
            current_provider = None
            continue
        if section == "rule-providers":
            match = re.fullmatch(r"([^:]+):", content)
            if indent == 2 and match:
                name = scalar(match.group(1))
                if name in providers:
                    raise RuleError("duplicate-rule-provider")
                providers[name] = {}
                current_provider = name
                continue
            prop = re.fullmatch(r"([A-Za-z0-9_-]+):[ ]+(.+)", content)
            if indent == 4 and current_provider and prop:
                key = prop.group(1)
                if key in providers[current_provider]:
                    raise RuleError("duplicate-provider-property")
                providers[current_provider][key] = scalar(prop.group(2))
                continue
            if current_provider in PROVIDERS:
                raise RuleError("config-unsupported-yaml")
        elif section == "proxy-groups":
            match = re.fullmatch(r"-[ ]+name:[ ]+(.+)", content)
            if match:
                groups.add(scalar(match.group(1)))
        elif section == "rules":
            match = re.fullmatch(r"-[ ]+(.+)", content)
            if not match:
                raise RuleError("config-unsupported-yaml")
            rule = scalar(match.group(1))
            parts = [part.strip() for part in rule.split(",")]
            if parts[0] == "RULE-SET" and len(parts) >= 3 and parts[1] in PROVIDERS:
                routed.append((parts[1], parts[2], len(routed)))
            if parts[0] == "MATCH":
                fallback = True
                routed.append(("MATCH", parts[1] if len(parts) > 1 else "", len(routed)))
    for name, (filename, _target) in PROVIDERS.items():
        expected = {"type": "file", "behavior": "classical", "format": "yaml",
                    "path": "./rules/" + filename}
        if name not in providers:
            raise RuleError("required-provider-missing")
        if any(providers[name].get(key) != value for key, value in expected.items()):
            raise RuleError("provider-contract-mismatch")
    seen = {}
    match_index = next((index for name, _target, index in routed if name == "MATCH"), None)
    for name, target, index in routed:
        if name == "MATCH":
            continue
        if name in seen:
            raise RuleError("duplicate-provider-rule")
        seen[name] = index
        expected_target = PROVIDERS[name][1]
        if target != expected_target:
            if target not in groups and target not in ("DIRECT", "REJECT"):
                raise RuleError("unknown-rule-target")
            raise RuleError("provider-target-mismatch")
        if match_index is not None and index > match_index:
            raise RuleError("custom-rule-after-match")
    if set(seen) != set(PROVIDERS):
        raise RuleError("provider-rule-reference-missing")
    if "Proxy" not in groups:
        raise RuleError("required-proxy-group-missing")
    return not fallback


def find_mihomo():
    for candidate in (os.environ.get("MIHOMO_CORE_BIN"),
                      str(Path.home() / ".local/bin/mihomo")):
        if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
            return candidate
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "mihomo"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    raise RuleError("mihomo-binary-missing")


def config_test(binary, home, config):
    try:
        proc = subprocess.run([binary, "-t", "-d", str(home), "-f", str(config)],
                              stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise RuleError("mihomo-config-test-unverified") from None
    if proc.returncode:
        raise RuleError("mihomo-config-test-failed")


def resolve_paths(args):
    data_home = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    config_home = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config")))
    home = safe_absolute(args.home_dir or str(data_home / "mihomo"), "home-dir")
    config = safe_absolute(args.config or str(config_home / "mihomo/config.yaml"), "config")
    return home, config


def output_status(files, json_mode):
    overall = ("FAIL" if any(item["status"] == "FAIL" for item in files) else
               "UNVERIFIED" if any(item["status"] == "UNVERIFIED" for item in files) else "PASS")
    if json_mode:
        reporting.rules("rules-status", overall, {"files": files})
    else:
        for item in files:
            if item["status"] == "PASS":
                print("PASS\t{}\trules={};sha256={};modified={};mode=600".format(
                    item["name"], item["rules"], item["sha256"], item["modified_utc"]))
            else:
                print("{}\t{}\t{}".format(item["status"], item["name"], item["error"]))
        print("{}\toverall\tfiles={}".format(overall, len(files)))
    return 0 if overall == "PASS" else 1 if overall == "FAIL" else 2


def main(argv=None):
    parser = Parser(prog="mihomoctl rules")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "check"):
        child = sub.add_parser(command)
        child.add_argument("--home-dir")
        child.add_argument("--config")
        if command == "status":
            child.add_argument("--json", action="store_true")
    try:
        args = parser.parse_args(argv)
        home, config = resolve_paths(args)
        inspect_owned(home / "rules", 0o700, "rules-directory")
        files = [file_status(home / "rules" / name) for name in FILES]
        if args.command == "status":
            return output_status(files, args.json)
        if any(item["status"] != "PASS" for item in files):
            return output_status(files, False)
        warning = parse_config(config)
        config_test(find_mihomo(), home, config)
        for name in ("directory", "files", "provider-contract", "mihomo-config-test"):
            print("PASS\t{}\tok".format(name))
        if warning:
            print("WARN\tfallback\tfinal-MATCH-is-missing")
        print("PASS\toverall\tread-only-custom-rule-contract-valid")
        return 0
    except RuleError as error:
        json_mode = "--json" in (argv if argv is not None else sys.argv[1:])
        command = "rules-status" if "status" in (argv if argv is not None else sys.argv[1:]) else "rules-check"
        unverified = error.usage or "unsupported" in error.code or "unverified" in error.code
        if json_mode:
            reporting.rules(command, "UNVERIFIED" if unverified else "FAIL",
                            error=error.code)
        print("mihomo-userctl: " + error.code, file=sys.stderr)
        return 2 if unverified else 1


if __name__ == "__main__":
    sys.exit(main())
