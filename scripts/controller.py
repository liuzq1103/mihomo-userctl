"""User-level controller component; no global proxy or daemon."""
import argparse
import importlib.util
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
    from .controller_dashboard import choose_port, archive_ui, setup, initialize
    from .controller_legacy import plain_tui, plain_console, tui
except ImportError:
    from controller_types import SCHEMA, COMMANDS, ControlError, Parser, LIMIT, TEST_URL, label, number
    from controller_config import private, read_config, patch_config, endpoint
    from controller_api import Client
    from controller_service import proxies, select, snapshot
    from controller_policy import POLICY_KEYS, OVERRIDE_RUNNER, flclash_input, policy_candidate
    from controller_transaction import apply_policy
    from controller_dashboard import choose_port, archive_ui, setup, initialize
    from controller_legacy import plain_tui, plain_console, tui

def stdin_preview(service, policy):
    """Consume a pipe before starting the UI, then restore keyboard input from the PTY."""
    if sys.stdin.isatty() or not sys.stdout.isatty():
        raise ControlError("tui-stdin-requires-pipe-and-terminal-output")
    try:
        terminal = open("/dev/tty", "r", encoding="utf-8")
    except OSError:
        raise ControlError("tui-stdin-requires-controlling-terminal") from None
    try:
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        preview = Subscriptions(service.config, service.home_dir).preview(stdin=True, policy=policy)
        os.dup2(terminal.fileno(), 0)
        sys.stdin = sys.__stdin__ = os.fdopen(0, "r", encoding="utf-8", closefd=False)
        return preview
    finally:
        terminal.close()


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
    parser.add_argument("--source-file", help="Private YAML: node list or provider routing policy selected by --policy")
    parser.add_argument("--url-file", help="Private file containing one HTTPS subscription URL")
    parser.add_argument("--stdin", action="store_true", dest="source_stdin")
    parser.add_argument("--policy", choices=("nodes", "provider"), default=None)
    parser.add_argument("--script", help="Trusted local JS main(config); Node vm is not a security sandbox")
    parser.add_argument("--apply", action="store_true", help="Validate, back up and save the preview; restart separately")
    parser.add_argument("--details", action="store_true", help="Opt in to private host/rule details for connections/TUI")
    parser.add_argument("--flclash-compat", action="store_true", help="Adapt local provider caches and missing Ai+/fallback groups for FlClash-rules")
    args = parser.parse_args(argv)
    if (args.engine or args.theme or args.ascii_only) and args.command != "tui":
        raise ControlError("engine-options-require-tui")
    if args.plain and args.engine not in (None, "plain"):
        raise ControlError("conflicting-tui-engines")
    engine = "plain" if args.plain else args.engine
    if engine is None and args.command == "tui":
        try:
            from .controller_deps import interpreter
        except ImportError:
            from controller_deps import interpreter
        try:
            executable, _ = interpreter()
        except (files.InstallError, ControlError, OSError, ValueError, KeyError, TypeError):
            executable = None
        engine = "textual" if executable or importlib.util.find_spec("textual") else "plain"
    if (args.theme or args.ascii_only) and engine != "textual":
        raise ControlError("theme-options-require-textual")
    tui_stdin = args.command == "tui" and args.source_stdin and not (args.source_file or args.url_file)
    if tui_stdin and engine == "curses":
        raise ControlError("tui-stdin-requires-textual-or-plain")
    if (args.source_file or args.url_file or args.source_stdin) and not tui_stdin and (args.command != "subscription" or args.values != ["preview"]):
        raise ControlError("source-options-require-subscription-preview")
    if args.policy is not None and not tui_stdin and (args.command != "subscription" or args.values != ["preview"]):
        raise ControlError("policy-requires-subscription-preview")
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
    initialize_requested = args.command == "controller" and args.values == ["initialize"]
    if initialize_requested and (args.archive or args.sha256):
        raise ControlError("initialize-does-not-install-dashboard")
    if not (setup_requested or initialize_requested) and (any(v is not None for v in (args.port, args.archive)) or
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
        service = ConsoleService(config, args.home_dir, args.details, args.script, args.flclash_compat)
        preview = stdin_preview(service, args.policy or "provider") if tui_stdin else None
        payload = run(service, ascii_only=args.ascii_only, theme=args.theme or "dark", initial_preview=preview)
    elif args.command == "tui" and engine == "plain":
        if args.json or args.values:
            raise ControlError("invalid-options")
        try:
            from .controller_service import ConsoleService
        except ImportError:
            from controller_service import ConsoleService
        service = ConsoleService(config, args.home_dir, args.details)
        preview = stdin_preview(service, args.policy or "provider") if tui_stdin else None
        try:
            payload = plain_console(service, initial_preview=preview)
        except (EOFError, KeyboardInterrupt):
            payload = {"state": "closed", "shell": "unchanged"}
    elif args.command == "subscription":
        try:
            from .controller_subscriptions import Subscriptions
        except ImportError:
            from controller_subscriptions import Subscriptions
        subscriptions = Subscriptions(config, args.home_dir)
        if args.values == ["preview"] and not args.sha256:
            payload = subscriptions.preview(args.source_file, args.url_file, args.source_stdin, args.policy or "nodes")
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
    elif initialize_requested:
        with files.locked(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))):
            payload = initialize(config, args.home_dir, args.port)
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
                          "error": {"code": code, "message": {
                              "controller-not-configured-as-loopback": "控制器需配置为 127.0.0.1:端口；运行 mihomoctl tui 进入设置，或运行 mihomoctl controller initialize。已有非本机监听须先手动修正。",
                              "controller-secret-must-be-32-to-256-url-safe-characters": "已有控制器密钥不符合要求；请在私有配置中设置 32–256 位 URL 安全随机密钥，再重启。",
                              "mihomo-executable-missing": "找不到 Mihomo 核心；安装或将已有核心加入 PATH 后重试，不要求精确版本。",
                              "config-missing": "缺少私有 Mihomo 配置；请按 setup.md 创建权限为 600 的 config.yaml，再运行初始化。",
                              "controller-unreachable": "控制器暂不可达；配置保存后需运行 mihomoctl restart，或在 TUI 首页启动服务。",
                              "controller-capability-unsupported": "当前核心不支持此 API；其他功能仍可使用。"
                          }.get(code, "操作未完成；请检查私有配置及运行环境，修正后重试。")}}, ensure_ascii="--json" in sys.argv))
        sys.exit(rc)
