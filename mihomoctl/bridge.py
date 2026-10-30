"""Bridge from the manager/application services to the packaged controller.

Temporary MIHOMO_* environment is restored after each invocation. The current
controller runs in-process; no Bash lifecycle or application daemon is invoked.
The optional old configuration fallback supports read/migration compatibility.
Legacy JSON field names are retained as part of the existing wire contract.
"""

import io
import json
import os
import sys
from contextlib import contextmanager, redirect_stdout
from pathlib import Path

from .config import load_manager
from .errors import MihomoctlError, UsageError
from .migrate import legacy_dir, load_legacy

BRIDGE_COMMANDS = {
    "controller", "nodes", "groups", "select", "latency", "connections", "traffic",
    "tui", "providers", "provider", "dns", "mode", "subscription", "health-check",
    "manual", "override", "ui", "dashboard",
}
GUIDANCE_COMMANDS = ('paseo', 'codex', 'opencode', 'diagnose', 'ready')
READY_URL_DEFAULT = "https://example.com/"
MIHOMO_KEYS = ("MIHOMO_SERVICE", "MIHOMO_PORT", "MIHOMO_READY_URL",
               "MIHOMO_HTTP_PROXY", "MIHOMO_HTTPS_PROXY", "MIHOMO_ALL_PROXY", 'MIHOMO_CORE_BIN')


class BridgeError(MihomoctlError):
    code = "controller-error"


def _import_controller():
    try:
        from mihomoctl.controller import controller
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from mihomoctl.controller import controller
    return controller


def _import_rules():
    try:
        from mihomoctl.controller import rules
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from mihomoctl.controller import rules
    return rules


def _v1_values(scope):
    """MIHOMO_* values + config path from the V1 manager, or None."""
    try:
        manager = load_manager(scope)
    except MihomoctlError:
        return None
    if not manager.core.config:
        return None
    from .app import Application
    app = Application(system=scope.system,
                      config_dir=str(scope.config_dir_override) if scope.config_dir_override else None)
    _manager, endpoints, _controller, profile, _cfg = app.resolve()
    creds = app.credentials(profile)
    if creds is None:
        return None
    from .endpoints import validate_profile_listeners
    chosen = validate_profile_listeners(profile, endpoints)
    http = chosen.get("http_listener")
    if http is None:
        return None
    from .environment import build as build_env
    proxy_env = build_env(profile, endpoints, creds)
    variables = proxy_env.variables()
    return {
        "MIHOMO_SERVICE": "mihomoctl.service" if manager.core.backend == "systemd" else "mihomo-process",
        "MIHOMO_PORT": str(http.port),
        "MIHOMO_READY_URL": READY_URL_DEFAULT,
        "MIHOMO_HTTP_PROXY": variables["HTTP_PROXY"],
        "MIHOMO_HTTPS_PROXY": variables["HTTPS_PROXY"],
        "MIHOMO_ALL_PROXY": variables["ALL_PROXY"],
        'MIHOMO_CORE_BIN': manager.core.binary,
        'home': str(scope.core_home),
        "config": manager.core.config,
    }


def synthesize_environment(scope):
    """Values for the legacy scripts: V1 manager first, 0.9.x fallback."""
    values = _v1_values(scope)
    if values is not None:
        return values
    legacy = load_legacy(legacy_dir(scope))
    if legacy is None:
        raise UsageError("bridge-unavailable",
                         "initialize V1 (mihomoctl init) or keep the 0.9.x configuration")
    settings, proxies = legacy
    env = {
        "MIHOMO_SERVICE": settings.get("MIHOMO_SERVICE", "mihomo"),
        "MIHOMO_PORT": settings.get("MIHOMO_PORT", ""),
        "MIHOMO_READY_URL": settings.get("MIHOMO_READY_URL", READY_URL_DEFAULT),
    }
    for key in ("MIHOMO_HTTP_PROXY", "MIHOMO_HTTPS_PROXY", "MIHOMO_ALL_PROXY"):
        if key in proxies:
            env[key] = proxies[key]
    if not env["MIHOMO_PORT"] or "MIHOMO_HTTP_PROXY" not in env:
        raise UsageError("bridge-unavailable", "legacy configuration is incomplete")
    return env


@contextmanager
def bridge_environment(scope):
    """Temporarily inject MIHOMO_* into the process environment; restore
    the prior values in ``finally`` (removed keys stay removed)."""
    values = synthesize_environment(scope)
    saved = {key: os.environ.get(key) for key in MIHOMO_KEYS}
    try:
        os.environ.update({k: v for k, v in values.items() if k in MIHOMO_KEYS})
        yield values
    finally:
        for key, old in saved.items():
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old


def bridge_forward(args, values, json_mode=False):
    """Build the child argv for one bridged controller command.

    Every synthesized option is *appended*, never spliced between the command
    name and its values: the child parser takes the command values as a
    ``nargs="*"`` positional, and argparse cannot match an optional that
    precedes such a positional.  ``mihomoctl select GROUP NODE`` therefore
    arrived at the child as ``select --config PATH GROUP NODE`` and was
    rejected as ``invalid-options``.  ``--json`` and ``--home-dir`` follow the
    same append-only rule; an option the caller already supplied wins.
    """
    passthrough = args and args[0] == "tui"
    forward = list(args)
    if json_mode and not passthrough and "--json" not in forward:
        forward.append("--json")
    if values.get("config") and "--config" not in forward:
        forward.extend(["--config", values["config"]])
    if values.get('home') and args[0] in ('tui', 'subscription', 'manual', 'override', 'health-check') \
            and '--home-dir' not in forward:
        forward.extend(['--home-dir', values['home']])
    return forward


def run_bridge(scope, args, json_mode=False):
    if args and args[0] == 'tui':
        from .locks import console_generation_lease
        with console_generation_lease(scope):
            return _run_bridge(scope, args, json_mode)
    return _run_bridge(scope, args, json_mode)


def _run_bridge(scope, args, json_mode=False):
    """Run one legacy controller command.  JSON mode captures output and
    re-emits it under the mihomoctl/v1 envelope; TUI passes through."""
    controller = _import_controller()
    from .app import Application
    from mihomoctl.controller.controller_transaction import runtime_application
    app = Application(system=scope.system, config_dir=str(scope.config_root))
    if args[0] in ('select', 'mode', 'provider', 'subscription', 'manual', 'override', 'health-check') or \
            args[0] == 'controller' and args[1:] in (['setup'], ['initialize'], ['token']):
        scope.require_mutation()
    passthrough = args and args[0] == "tui"
    if passthrough:
        config = scope.config_root / 'mihomo/config.yaml'
        try:
            if scope.manager_path.exists():
                config = Path(load_manager(scope).core.config)
        except MihomoctlError:
            pass  # The interface reports invalid existing state without replacing it.
        forward = bridge_forward(args, {'config': str(config), 'home': str(scope.core_home)})
        try:
            code = controller.main(forward, app=app)
        except controller.ControlError as error:
            from .controller.controller_types import safe_failure
            failure = BridgeError(error.code, safe_failure(error))
            failure.exit_code = getattr(error, 'rc', 2)
            raise failure from None
        except controller.files.InstallError as error:
            raise BridgeError(error.code, error.safe_detail) from None
        return {'passthrough': True}, None if code in (None, 0) else BridgeError('controller-exit')
    with bridge_environment(scope) as values:
        token = runtime_application.set(app)
        forward = bridge_forward(args, values, json_mode)
        try:
            if passthrough or not json_mode:
                code = controller.main(forward, app=app)
                if isinstance(code, int) and code != 0:
                    return {"legacy_exit": code, "passthrough": True}, BridgeError(
                        "controller-exit-%d" % code, " ".join(forward[:2]))
                return {"passthrough": True}, None
            buffer = io.StringIO()
            code = 0
            with redirect_stdout(buffer):
                try:
                    code = controller.main(forward, app=app)
                except SystemExit as exc:
                    code = exc.code if isinstance(exc.code, int) else 0
            output = buffer.getvalue()
        except controller.ControlError as exc:
            from .controller.controller_types import error_detail, safe_failure
            error = BridgeError(getattr(exc, "code", "controller-error"),
                                error_detail(exc.code, safe_failure(exc) or getattr(exc, "detail", "")))
            error.exit_code = getattr(exc, 'rc', 2)
            raise error from None
        except MihomoctlError:
            raise
        except controller.files.InstallError as exc:
            raise BridgeError(exc.code, exc.safe_detail) from None
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise BridgeError('controller-operation-unavailable', exc.__class__.__name__) from None
        finally:
            runtime_application.reset(token)
    try:
        payload = json.loads(output)
    except ValueError:
        payload = {'output': 'unstructured controller output omitted'}
    overall = env_overall(payload, code)
    return {"legacy": payload, "exit": code, "legacy_overall": overall}, (
        BridgeError("controller-exit-%d" % code) if isinstance(code, int) and code != 0 else None)


def env_overall(payload, code):
    if isinstance(code, int) and code != 0:
        return "FAIL"
    if isinstance(payload, dict):
        value = payload.get("overall")
        if value in ("PASS", "FAIL", "UNVERIFIED", "SKIPPED"):
            return value
    return "PASS"


def run_rules(scope, args, json_mode=False):
    """Read-only custom-rule contract checks over the managed core layout.

    No mutation is requested and no proxy environment is synthesized: the
    checker only needs the core HomeDir and the active config path, both owned
    by the V1 manager, so the paths are supplied explicitly instead of guessed.
    The checker's own 0/1/2 result already matches the CLI contract and is
    preserved verbatim; output is re-emitted under the ``mihomoctl/v1``
    envelope.
    """
    checker = _import_rules()
    if not args or args[0] not in ("status", "check"):
        raise UsageError("usage-error",
                         "usage: mihomoctl rules status|check [--home-dir PATH] [--config PATH]")
    manager = load_manager(scope)
    forward = list(args)
    if "--home-dir" not in forward:
        forward.extend(["--home-dir", str(scope.core_home)])
    if "--config" not in forward:
        if not manager.core.config:
            raise UsageError("rules-unavailable",
                             "run mihomoctl init first so the active core config path is known")
        forward.extend(["--config", manager.core.config])
    if json_mode and "--json" not in forward:
        forward.append("--json")
    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            from .lifecycle.systemd import service_account_uid
            code = checker.main(forward, core_binary=manager.core.binary,
                                core_uid=service_account_uid() if scope.system else None)
    except checker.RuleError as exc:
        raise BridgeError(exc.code) from None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise BridgeError("rules-operation-unavailable", exc.__class__.__name__) from None
    text = buffer.getvalue()
    payload = None
    if json_mode:
        try:
            payload = json.loads(text)
        except ValueError:
            payload = None
    overall = "PASS" if code == 0 else "FAIL" if code == 1 else "UNVERIFIED"
    data = {"check": args[0], "exit": code, "output": text}
    if payload is not None:
        data["rules"] = payload
    return data, overall


def guidance(command):
    if command in GUIDANCE_COMMANDS:
        return {
            "retired": command,
            "guidance": "application daemon lifecycle commands are retired; "
                        "use declarative bindings (mihomoctl integration install) and "
                        "operator-managed restarts; migration: mihomoctl migrate --dry-run",
        }
    return None
