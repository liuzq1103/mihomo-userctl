"""User-level controller component; no global proxy or daemon."""
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

# Verify every flat runtime component before importing executable Python code.
# The containing generation is private; roots / same-UID attackers remain out of scope.
_COMPONENTS = ("controller_types", "controller_config", "controller_api", "controller_service",
               "controller_policy", "controller_transaction", "controller_dashboard", "controller_legacy",
               "controller_state", "controller_runtime", "controller_subscriptions", "controller_textual",
               "controller_deps")
if hasattr(os, "getuid"):
    for _name in _COMPONENTS:
        _path = Path(__file__).absolute().with_name(_name + ".py")
        try:
            _info = _path.lstat()
            _safe = stat.S_ISREG(_info.st_mode) and _info.st_uid == os.getuid() and not _info.st_mode & 0o022
        except OSError:
            _safe = False
        if not _safe:
            print(json.dumps({"schema": "mihomo-userctl.controller/v1", "command": "controller", "overall": "UNVERIFIED", "error": {"code": "unsafe-controller-component"}}))
            sys.exit(2)

try:
    from .controller_types import SCHEMA, COMMANDS, ControlError, Parser, LIMIT, TEST_URL, label, number
    from .controller_config import private, read_config, patch_config, endpoint
    from .controller_api import Client
    from .controller_service import proxies, select, snapshot
    from .controller_policy import POLICY_KEYS, OVERRIDE_RUNNER, flclash_input, policy_candidate
    from .controller_transaction import apply_policy
    from .controller_dashboard import choose_port, archive_ui, setup
    from .controller_legacy import plain_tui, tui
except ImportError:
    from controller_types import SCHEMA, COMMANDS, ControlError, Parser, LIMIT, TEST_URL, label, number
    from controller_config import private, read_config, patch_config, endpoint
    from controller_api import Client
    from controller_service import proxies, select, snapshot
    from controller_policy import POLICY_KEYS, OVERRIDE_RUNNER, flclash_input, policy_candidate
    from controller_transaction import apply_policy
    from controller_dashboard import choose_port, archive_ui, setup
    from controller_legacy import plain_tui, tui

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
    parser.add_argument("--engine", choices=("curses", "textual", "plain"))
    parser.add_argument("--theme", choices=("dark", "light"), default=None)
    parser.add_argument("--ascii", action="store_true", dest="ascii_only")
    parser.add_argument("--source-file", help="Private node-list YAML, never a full config")
    parser.add_argument("--url-file", help="Private file containing one HTTPS subscription URL")
    parser.add_argument("--stdin", action="store_true", dest="source_stdin")
    parser.add_argument("--script", help="Trusted local JS main(config); Node vm is not a security sandbox")
    parser.add_argument("--apply", action="store_true", help="Validate, back up and save the preview; restart separately")
    parser.add_argument("--details", action="store_true", help="Opt in to private host/rule details for connections/TUI")
    parser.add_argument("--flclash-compat", action="store_true", help="Adapt local provider caches and missing Ai+/fallback groups for FlClash-rules")
    args = parser.parse_args(argv)
    if (args.engine or args.theme or args.ascii_only) and args.command != "tui":
        raise ControlError("engine-options-require-tui")
    if args.plain and args.engine not in (None, "plain"):
        raise ControlError("conflicting-tui-engines")
    engine = "plain" if args.plain else args.engine or "curses"
    if (args.theme or args.ascii_only) and engine != "textual":
        raise ControlError("theme-options-require-textual")
    if (args.source_file or args.url_file or args.source_stdin) and (args.command != "subscription" or args.values != ["preview"]):
        raise ControlError("source-options-require-subscription-preview")
    if args.plain and args.command != "tui":
        raise ControlError("plain-requires-tui")
    if args.script and args.command not in ("override", "tui") or args.apply and args.command not in ("override", "manual"):
        raise ControlError("policy-options-require-override-manual-or-tui")
    if args.details and args.command not in ("connections", "tui"):
        raise ControlError("details-requires-connections-or-tui")
    if args.flclash_compat and (not args.script or args.command not in ("override", "tui")):
        raise ControlError("flclash-compat-requires-script")
    if engine == "plain" and args.script:
        raise ControlError("script-preview-requires-fullscreen-tui-or-override-command")
    config = Path(args.config or str(Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "mihomo/config.yaml"))
    setup_requested = args.command == "controller" and args.values == ["setup"]
    if not setup_requested and (any(v is not None for v in (args.port, args.archive)) or
                                args.sha256 is not None and args.command != "subscription" or
                                args.home_dir is not None and args.command not in ("override", "manual", "tui", "subscription")):
        raise ControlError("setup-options-require-controller-setup")
    if args.command == "tui" and engine == "textual":
        if args.json or args.values:
            raise ControlError("tui-does-not-support-json" if args.json else "invalid-options")
        try:
            from .controller_deps import launch
            from .controller_service import ConsoleService
        except ImportError:
            from controller_deps import launch
            from controller_service import ConsoleService
        launch(sys.argv[1:] if argv is None else argv)
        try:
            from .controller_textual import run
        except ImportError:
            try:
                from controller_textual import run
            except ImportError:
                raise ControlError("textual-environment-incomplete-use-engine-curses") from None
        payload = run(ConsoleService(config, args.home_dir, args.details, args.script, args.flclash_compat),
                      ascii_only=args.ascii_only, theme=args.theme or "dark")
    elif args.command == "subscription":
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        subscriptions = Subscriptions(config, args.home_dir)
        if args.values == ["preview"] and not args.sha256:
            payload = subscriptions.preview(args.source_file, args.url_file, args.source_stdin)
        elif len(args.values) == 2 and args.values[0] == "apply" and args.sha256:
            payload = subscriptions.apply(args.values[1], args.sha256)
        else:
            raise ControlError("invalid-subscription-options")
    elif args.command in ("providers", "provider", "dns", "mode"):
        try:
            from .controller_service import ConsoleService
        except ImportError:
            from controller_service import ConsoleService
        service = ConsoleService(config, args.home_dir)
        if args.command == "providers" and not args.values:
            payload = service.read("providers")
        elif args.command == "provider" and len(args.values) == 2 and args.values[0] == "refresh":
            payload = service.provider_refresh(args.values[1])
        elif args.command == "dns" and 1 <= len(args.values) <= 2:
            payload = service.dns(*args.values)
        elif args.command == "mode" and len(args.values) == 1:
            payload = service.mode(args.values[0])
        else:
            raise ControlError("invalid-options")
    elif args.command in ("override", "manual"):
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
            payload = tui(client, engine == "plain", config, args.script, args.home_dir, args.details, args.flclash_compat)
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
