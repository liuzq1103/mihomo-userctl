"""Python bridge to the retained Controller/subscription/policy/TUI stack.

The legacy scripts are imported as the packaged ``scripts`` module set —
no subprocess Bash, no shell entry callbacks.  The controller needs
MIHOMO_* environment and the active core config path: both are
synthesized from the V1 manager (falling back to the 0.9.x pair) and
injected under a context manager that restores the process environment
in ``finally`` — no permanent pollution.

Legacy failures map to ``BridgeError`` (a MihomoctlError); nothing
escapes as a raw traceback.  The TUI consumes ``mihomoctl.app``
directly (E integration); this bridge forwards environment and config.
Retired application-lifecycle commands return migration guidance.
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
    "manual", "override", "ui", "dashboard", "token",
}
GUIDANCE_COMMANDS = ('paseo', 'codex', 'opencode', 'diagnose', 'ready')
READY_URL_DEFAULT = "https://example.com/"
MIHOMO_KEYS = ("MIHOMO_SERVICE", "MIHOMO_PORT", "MIHOMO_READY_URL",
               "MIHOMO_HTTP_PROXY", "MIHOMO_HTTPS_PROXY", "MIHOMO_ALL_PROXY", 'MIHOMO_CORE_BIN')


class BridgeError(MihomoctlError):
    code = "controller-error"


def _import_controller():
    try:
        from scripts import controller
    except ImportError:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from scripts import controller
    return controller


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


def run_bridge(scope, args, json_mode=False):
    """Run one legacy controller command.  JSON mode captures output and
    re-emits it under the mihomoctl/v1 envelope; TUI passes through."""
    controller = _import_controller()
    from .app import Application
    from scripts.controller_transaction import runtime_application
    app = Application(system=scope.system, config_dir=str(scope.config_root))
    if args[0] in ('select', 'mode', 'subscription', 'manual', 'override', 'health-check') or \
            args[0] == 'controller' and args[1:] in (['setup'], ['initialize'], ['token']):
        scope.require_mutation()
    passthrough = args and args[0] == "tui"
    forward = list(args)
    if json_mode and not passthrough and "--json" not in forward:
        forward.append("--json")
    with bridge_environment(scope) as values:
        token = runtime_application.set(app)
        if values.get("config") and "--config" not in forward:
            index = 1 if forward and not forward[0].startswith("-") else 0
            forward[index:index] = ["--config", values["config"]]
        if values.get('home') and args[0] in ('tui', 'subscription', 'manual', 'override', 'health-check') and '--home-dir' not in forward:
            forward.extend(['--home-dir', values['home']])
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
            error = BridgeError(getattr(exc, "code", "controller-error"))
            error.exit_code = getattr(exc, 'rc', 2)
            raise error from None
        except MihomoctlError:
            raise
        except (controller.files.InstallError, OSError, ValueError, TypeError, KeyError) as exc:
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


def guidance(command):
    if command in GUIDANCE_COMMANDS:
        return {
            "retired": command,
            "guidance": "application daemon lifecycle commands are retired; "
                        "use declarative bindings (mihomoctl integration install) and "
                        "operator-managed restarts; migration: mihomoctl migrate --dry-run",
        }
    return None
