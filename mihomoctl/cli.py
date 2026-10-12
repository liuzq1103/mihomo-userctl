"""CLI: parsing and serialization only — domain decisions live in the
application services.

Grammar: ``mihomoctl [--user|--system] COMMAND [ARGS...] [--json]``.
The first ``--`` separates manager arguments from a child argv (exec /
direct); ``--json`` and scope flags are honored only in the manager
region, so child arguments are passed through verbatim.  After exec
starts, the child's exit/signal result is never remapped.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import SCHEMA, __version__
from . import envelope as env
from .app import Application, UNIT_NAME
from .config import load_manager, render_manager
from .errors import (HealthBlockedError, MihomoctlError, NotFoundError,
                     PermissionScopeError, UsageError)
from .lifecycle import systemd as systemd_backend


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        split = argv.index("--")
        manager_args, child_argv = argv[:split], argv[split + 1:]
    else:
        manager_args, child_argv = argv, None
    manager_args, json_mode = _extract_json(manager_args)
    system = False
    command = "mihomoctl"
    try:
        manager_args, system = _extract_scope(manager_args)
        if not manager_args:
            raise UsageError("usage-error", "a command is required")
        command = manager_args[0]
        app = Application(system=system)
        return dispatch(app, command, manager_args[1:], child_argv, json_mode)
    except MihomoctlError as exc:
        if json_mode:
            _emit(_envelope(command, "system" if system else "user",
                            "FAIL" if exc.exit_code == 1 else "UNVERIFIED",
                            errors=[_error_payload(exc)]))
        else:
            print("mihomoctl: %s" % exc.render(), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130
    except (OSError, UnicodeError, ValueError) as exc:
        error = {'code': 'operation-unavailable', 'detail': exc.__class__.__name__}
        if json_mode:
            _emit(_envelope(command, 'system' if system else 'user', env.UNVERIFIED, errors=[error]))
        else:
            print('mihomoctl: operation unavailable (%s)' % exc.__class__.__name__, file=sys.stderr)
        return 2


def _extract_json(argv):
    json_mode = "--json" in argv
    if json_mode:
        argv = [a for a in argv if a != "--json"]
    return argv, json_mode


def _extract_scope(argv):
    if "--user" in argv and "--system" in argv:
        raise UsageError("scope-flags-exclusive", "--user and --system are mutually exclusive")
    cleaned = []
    system = False
    seen_command = False
    for arg in argv:
        if arg in ("--user", "--system") and not seen_command:
            system = arg == "--system"
            continue
        seen_command = True
        cleaned.append(arg)
    return cleaned, system


def _emit(document):
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))


def _envelope(command, scope_name, overall, data=None, checks=None, errors=None):
    return env.envelope(command, scope_name, overall, data, checks, errors)


def _error_payload(exc):
    row = {"code": exc.code}
    if exc.detail:
        row["detail"] = str(exc.detail)
    if exc.remediation:
        row["remediation"] = exc.remediation
    return row


def _finish(command, scope, overall, data=None, checks=None, json_mode=True, text=None):
    if json_mode:
        _emit(_envelope(command, scope, overall, data, checks))
    elif text is not None:
        print(text)
    return env.exit_code(overall)


# ---------------------------------------------------------------------------
# human renderers
# ---------------------------------------------------------------------------

def _status_text(data):
    lines = ["scope=%s backend=%s" % (data.get("scope"), data.get("backend"))]
    core = data.get("core") or {}
    lines.append("core binary=%s config=%s" % (core.get("binary"), core.get("config")))
    controller = data.get("controller")
    lines.append("controller=%s" % (
        "%s:%d authenticated=%s" % (controller["address"], controller["port"], controller["authenticated"])
        if controller else "not-configured"))
    listeners = data.get("listeners") or []
    lines.append("listeners=%s" % (", ".join(
        "%s(%s %s:%d%s)" % (l["name"], l["type"], l["address"], l["port"],
                            " auth" if l.get("authenticated") else "") for l in listeners) or "none"))
    lines.append("active_config=%s" % data.get("active_config"))
    proxy = data.get("proxy") or {}
    lines.append("proxy profile=%s http=%s socks=%s" % (
        proxy.get("profile"), proxy.get("http_proxy"), proxy.get("all_proxy")))
    lines.append("proxy_mode=%s routing_mode=%s tun=%s" % (data.get("proxy_mode"), data.get("routing_mode", data.get("mode")),
                                             (data.get("tun") or {}).get("enabled")))
    runtime = data.get("runtime") or {}
    lines.append("runtime running=%s detail=%s" % (runtime.get("running"), runtime.get("detail", "")))
    for error in data.get("errors") or []:
        lines.append("error: %s" % error)
    return "\n".join(lines)


def _checks_text(checks):
    return "\n".join("%s %s (%s)%s" % (c.status, c.name, c.evidence,
                                       " " + c.detail if c.detail else "")
                     for c in checks)


def _kv_text(data, indent=0):
    lines = []
    for key in sorted(data) if isinstance(data, dict) else []:
        value = data[key]
        if isinstance(value, dict):
            lines.append(" " * indent + "%s:" % key)
            lines.append(_kv_text(value, indent + 2))
        elif isinstance(value, list):
            lines.append(" " * indent + "%s: %s" % (key, ", ".join(str(v) for v in value)))
        else:
            lines.append(" " * indent + "%s: %s" % (key, value))
    return "\n".join(line for line in lines if line is not None)


# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

def dispatch(app, command, args, child_argv, json_mode):
    scope = app.scope
    name = scope.name
    if args and args[-1] in ('--help', '-h') and command in ('profile', 'service', 'integration', 'core', 'tun', 'env', 'config', 'migrate'):
        surface = {'profile': 'list|show NAME|validate NAME|set-default NAME',
                   'service': 'install|start|stop|restart|status|uninstall [--dry-run]',
                   'integration': 'list|show|check|export|install|remove NAME',
                   'core': 'install|update --version VERSION [--sha256 SHA256]',
                   'tun': 'status|enable|disable', 'env': 'show|export [--profile NAME|--binding NAME] [--output FILE|--reveal]',
                   'config': 'validate [--file FILE]|check', 'migrate': '--dry-run|--apply [--core PATH] [--remove-loader]'}
        return _finish('help', name, env.PASS, {'usage': surface[command]}, json_mode=json_mode,
                       text='Usage: mihomoctl ' + command + ' ' + surface[command])
    if command in ('help', '--help', '-h'):
        commands = 'init start stop restart status logs config profile env exec direct integration service tun core health doctor migrate rollback update controller nodes groups select latency connections traffic subscription rules tui version'
        return _finish('help', name, env.PASS, {'commands': commands.split()}, json_mode=json_mode,
                       text='Usage: mihomoctl [--user|--system] COMMAND [OPTIONS] [--json]\nCommands: ' + commands)
    if command == "init":
        return cmd_init(app, args, json_mode)
    if command == "status":
        data = app.status()
        return _finish("status", name, data.get("overall", env.FAIL), data,
                       json_mode=json_mode, text=_status_text(data))
    if command in ("health",):
        if args and args[0] == "check":
            args = args[1:]
        return cmd_health(app, args, json_mode)
    if command in ("start", "stop", "restart"):
        data = app.lifecycle(command)
        return _finish(command, name, data.get("overall", env.FAIL), data,
                       json_mode=json_mode, text=_status_text(data))
    if command == "exec":
        return cmd_exec(app, args, child_argv, json_mode)
    if command == "direct":
        return cmd_direct(child_argv)
    if command == "env":
        return cmd_env(app, args, json_mode)
    if command == "service":
        return cmd_service(app, args, json_mode)
    if command == "core":
        return cmd_core(app, args, json_mode)
    if command == "tun":
        return cmd_tun(app, args, json_mode)
    if command == "integration":
        return cmd_integration(app, args, json_mode)
    if command == "export":
        return cmd_export(app, args, json_mode)
    if command == "migrate":
        return cmd_migrate(app, args, json_mode)
    if command == "profiles":
        return _finish("profiles", name, env.PASS, {"profiles": app.profiles()},
                       json_mode=json_mode, text=_kv_text({"profiles": app.profiles()}))
    if command == "profile":
        return cmd_profile(app, args, json_mode)
    if command == "config":
        return cmd_config(app, args, json_mode)
    if command == "logs":
        return cmd_logs(app, args, json_mode)
    if command == "rules":
        from .legacy import run_rules
        data, overall = run_rules(scope, args, json_mode)
        return _finish("rules-" + data["check"], name, overall, data,
                       json_mode=json_mode, text=data["output"])
    if command == "doctor":
        return cmd_doctor(app, args, json_mode)
    if command in ("update", "rollback"):
        return cmd_installation(command, app, args, json_mode)
    if command == "version":
        data = {"mihomoctl": __version__, "schema": SCHEMA}
        try:
            manager = app.load_manager()
            if manager.core.binary:
                from .lifecycle.runner import core_version
                from .trust import require_executable_file
                require_executable_file(manager.core.binary, as_root=app.scope.system)
                data["core"] = core_version(manager.core.binary,
                    as_uid=systemd_backend.service_account_uid() if app.scope.system else None)
        except MihomoctlError:
            data["core"] = None
        return _finish("version", name, env.PASS, data, json_mode=json_mode,
                       text="mihomoctl %s\ncore %s" % (data["mihomoctl"], data.get("core")))
    from .legacy import BRIDGE_COMMANDS, GUIDANCE_COMMANDS, guidance, run_bridge
    if command in BRIDGE_COMMANDS:
        data, exc = run_bridge(scope, [command, *args], json_mode)
        if exc is not None:
            raise exc
        legacy_overall = data.get("legacy_overall", env.PASS)
        return _finish(command, name, legacy_overall, data,
                       json_mode=json_mode, text=None if json_mode else "")
    if command in GUIDANCE_COMMANDS:
        raise UsageError('retired-command', 'the legacy application-specific or readiness entry has been retired',
                         remediation='Use mihomoctl exec -- COMMAND for explicit environment injection, mihomoctl health check or mihomoctl doctor; migrate old configuration with mihomoctl migrate --dry-run.')
    raise UsageError("unknown-command", repr(command))


# ---------------------------------------------------------------------------
# init / health / exec / env
# ---------------------------------------------------------------------------

def cmd_init(app, args, json_mode):
    parser = _parser("init")
    parser.add_argument("--core", required=True)
    parser.add_argument("--port", type=int)
    parser.add_argument("--config")
    parser.add_argument("--allow-non-loopback", action="append", default=[])
    values = parser.parse_args(args)
    if app.scope.system and hasattr(os, "geteuid") and os.geteuid() != 0:
        raise PermissionScopeError("system-requires-root", "--system mutations require UID 0")
    data = app.initialize(values.core, port=values.port, config_file=values.config,
                          allow_non_loopback=tuple(values.allow_non_loopback))
    return _finish("init", app.scope.name, env.PASS, data, json_mode=json_mode,
                   text=_kv_text(data))


def cmd_health(app, args, json_mode):
    parser = _parser("health")
    parser.add_argument("--profile")
    parser.add_argument("--binding")
    parser.add_argument("--egress-url")
    values = parser.parse_args(args)
    profile = _profile_of(app, values.profile, values.binding)
    checks = app.health(profile=profile, egress_url=values.egress_url)
    overall = env.combine_checks(checks)
    return _finish("health", app.scope.name, overall, {"overall": overall}, checks,
                   json_mode=json_mode, text=_checks_text(checks))


def _profile_of(app, profile, binding_name):
    if profile is not None and binding_name is not None:
        raise UsageError('profile-binding-exclusive', '--profile and --binding are mutually exclusive')
    if profile is None and binding_name is not None:
        manager = app.load_manager()
        binding = manager.bindings.get(binding_name)
        if binding is None:
            raise NotFoundError("binding-unknown", binding_name)
        return binding.profile
    return profile


def cmd_exec(app, args, child_argv, json_mode):
    parser = _parser("exec")
    parser.add_argument("--profile")
    parser.add_argument("--binding")
    head = [a for a in args if a not in ("--",)]
    values = parser.parse_args(head)
    child = child_argv or []
    if not child:
        raise UsageError("usage-error", "exec requires: exec [--profile P] -- COMMAND [ARGS...]")
    profile = _profile_of(app, values.profile, values.binding)
    checks = app.health(profile=profile)
    overall = env.combine_checks(checks)
    if overall != env.PASS:
        failures = [c.name for c in checks if c.status == env.FAIL]
        raise HealthBlockedError("health-blocked",
                                 "local health not confirmed: %s" % ", ".join(failures or [overall]))
    proxy_env = app.proxy_environment(profile)
    from .environment import exec_environment
    target = exec_environment(dict(os.environ), proxy_env)
    executable = child[0] if "/" in child[0] else (shutil.which(child[0]) or child[0])
    os.execve(executable, child, target)
    return 0  # unreachable


def cmd_direct(child_argv):
    child = child_argv or []
    if not child:
        raise UsageError("usage-error", "direct requires: direct -- COMMAND [ARGS...]")
    from .environment import direct_environment
    target = direct_environment(dict(os.environ))
    executable = child[0] if "/" in child[0] else (shutil.which(child[0]) or child[0])
    os.execve(executable, child, target)
    return 0  # unreachable


def cmd_env(app, args, json_mode):
    if not args:
        raise UsageError("usage-error", "env requires show|export")
    action = args[0]
    parser = _parser("env-" + action)
    parser.add_argument("--profile")
    parser.add_argument("--binding")
    if action == "show":
        parser.add_argument("--reveal", action="store_true")
    if action == "export":
        choice = parser.add_mutually_exclusive_group(required=True)
        choice.add_argument('--output')
        choice.add_argument('--reveal', action='store_true')
    values = parser.parse_args(args[1:])
    profile = _profile_of(app, values.profile, values.binding)
    proxy_env = app.proxy_environment(profile)
    if action == "show":
        data = proxy_env.redacted()
        if values.reveal:
            data = dict(proxy_env.variables())
        return _finish("env-show", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    if action == "export":
        from .credentials import write_atomic
        from .environment import PROXY_KEYS
        variables = proxy_env.variables()
        text = "".join("%s=%s\n" % (key, variables[key]) for key in PROXY_KEYS)
        if values.reveal:
            return _finish('env-export', app.scope.name, env.PASS, {'environment': variables}, json_mode=json_mode, text=text.rstrip())
        write_atomic(Path(values.output).expanduser(), text, mode=0o600)
        return _finish("env-export", app.scope.name, env.PASS,
                       {"output": values.output, "mode": "0600", "keys": sorted(variables)},
                       json_mode=json_mode, text="exported %s (mode 0600)" % values.output)
    raise UsageError("usage-error", "unknown env action %r" % action)


# ---------------------------------------------------------------------------
# profile / config / logs / doctor
# ---------------------------------------------------------------------------

def cmd_profile(app, args, json_mode):
    if not args:
        raise UsageError("usage-error", "profile requires list|show|validate|set-default")
    action = args[0]
    manager = app.load_manager()
    if action == "list":
        rows = app.profiles()
        return _finish("profile-list", app.scope.name, env.PASS, {"profiles": rows},
                       json_mode=json_mode, text=_kv_text({"profiles": rows}))
    if action in ("show", "validate", "set-default"):
        if len(args) < 2:
            raise UsageError("usage-error", "profile %s requires a name" % action)
        name = args[1]
        profile = manager.profiles.get(name)
        if profile is None:
            raise NotFoundError("profile-unknown", name)
        if action == "show":
            return _finish("profile-show", app.scope.name, env.PASS, profile.redacted(),
                           json_mode=json_mode, text=_kv_text(profile.redacted()))
        if action == "validate":
            app.resolve(name)  # resolves endpoints + profile references or raises
            return _finish("profile-validate", app.scope.name, env.PASS,
                           {"profile": name, "valid": True}, json_mode=json_mode,
                           text="profile %s valid" % name)
        # set-default (transactional)
        app.resolve(name)
        from .transaction import run_transaction

        def mutate(tx):
            current, _endpoints, _controller, _profile, _cfg = app.resolve(name)
            current.default_profile = name
            tx.write_text(app.scope.manager_path, render_manager(current), mode=0o600)
        run_transaction(app.scope, "profile-set-default", mutate)
        return _finish("profile-set-default", app.scope.name, env.PASS,
                       {"default_profile": name}, json_mode=json_mode,
                       text="default profile: %s" % name)
    raise UsageError("usage-error", "unknown profile action %r" % action)


def cmd_config(app, args, json_mode):
    if args and args[0] == "check":
        args = ["validate"] + args[1:]
    if not args or args[0] != "validate":
        raise UsageError("usage-error", "config requires: config validate [--file FILE]")
    parser = _parser("config-validate")
    parser.add_argument("--file")
    parser.add_argument("--profile")
    values = parser.parse_args(args[1:])
    from .endpoints import parse_endpoints
    from .lifecycle import runner
    from .yamlutil import strict_load
    checks = []
    if values.file:
        text = Path(values.file).expanduser().read_text(encoding="utf-8")
        cfg = strict_load(text)
        endpoints, controller = parse_endpoints(
            cfg, system_scope=app.scope.system,
            allowed_addresses=(app.load_manager().allow_non_loopback
                               if _manager_exists(app) else ()))
        checks.append(env.Check("config-parse", env.PASS,
                                detail="%d listening surfaces" % len(endpoints)))
        data = {"file": values.file}
        if _manager_exists(app):
            manager = app.load_manager()
            from .trust import require_executable_file
            require_executable_file(manager.core.binary, as_root=app.scope.system)
            runner.validate_config(manager.core.binary, text, app.scope.core_home,
                as_uid=systemd_backend.service_account_uid() if app.scope.system else None)
            checks.append(env.Check('core-validate', env.PASS))
        else:
            checks.append(env.Check('core-validate', env.UNVERIFIED, evidence=env.UNAVAILABLE,
                                    detail='initialize a trusted core before semantic validation'))
    else:
        manager, endpoints, controller, profile, cfg = app.resolve()
        text = Path(manager.core.config).read_text(encoding="utf-8")
        checks.append(env.Check("config-parse", env.PASS,
                                detail="%d listening surfaces" % len(endpoints)))
        data = {"config": manager.core.config}
        binary = manager.core.binary
        if binary:
            from .trust import require_executable_file
            require_executable_file(binary, as_root=app.scope.system)
            as_uid = systemd_backend.service_account_uid() if app.scope.system else None
            try:
                runner.validate_config(binary, text, app.scope.core_home, as_uid=as_uid)
                checks.append(env.Check("core-validate", env.PASS))
            except MihomoctlError as exc:
                checks.append(env.Check("core-validate", env.FAIL, detail=exc.render()))
    return _finish("config-validate", app.scope.name, env.combine_checks(checks), data, checks,
                   json_mode=json_mode, text=_checks_text(checks))


def _manager_exists(app):
    try:
        app.load_manager()
        return True
    except MihomoctlError:
        return False


def cmd_logs(app, args, json_mode):
    parser = _parser("logs")
    parser.add_argument("--lines", type=int, default=50)
    parser.add_argument("--follow", action="store_true")
    values = parser.parse_args(args)
    if not 1 <= values.lines <= 10000:
        raise UsageError('logs-lines-invalid', '--lines must be 1-10000')
    if values.follow and json_mode:
        raise UsageError('logs-follow-json', '--follow cannot produce a single JSON document')
    manager = app.load_manager()
    protected = []
    def collect(value, sensitive=False):
        if isinstance(value, dict):
            for key, item in value.items():
                collect(item, sensitive or str(key).lower() in ('password', 'secret', 'uuid', 'private-key', 'authentication', 'url', 'token'))
        elif isinstance(value, list):
            for item in value:
                collect(item, sensitive)
        elif sensitive and isinstance(value, str) and value:
            protected.append(value)
    collect(app.resolve()[4])
    def redact(line):
        import re
        for value in sorted(protected, key=len, reverse=True):
            line = line.replace(value, '[redacted]')
        line = re.sub(r'(https?|socks5h?)://[^\s/]+@', r'\1://[redacted]@', line)
        line = re.sub(r'([?&](?:token|key|secret|password|auth)=)[^\s&]+', r'\1[redacted]', line, flags=re.I)
        return ''.join(c if c >= ' ' else ' ' for c in line)[:4096]
    if manager.core.backend == "systemd":
        command = ["journalctl"] + ([] if app.scope.system else ["--user"]) + [
            "-u", UNIT_NAME, "--no-pager", "-n", str(values.lines)]
        if values.follow:
            command.append("-f")
        if values.follow:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                for line in process.stdout:
                    print(redact(line.rstrip()), flush=True)
                return process.wait()
            finally:
                if process.poll() is None:
                    process.terminate()
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise MihomoctlError('logs-unavailable', 'journalctl could not read the managed unit')
        entries = [redact(line) for line in result.stdout.splitlines()]
        return _finish('logs', app.scope.name, env.PASS, {'entries': entries}, json_mode=json_mode, text='\n'.join(entries))
    log = app.scope.logs_dir / "mihomo.log"
    if not log.exists():
        raise MihomoctlError("logs-unavailable", "no process logs yet; backend=%s" % manager.core.backend)
    text = [redact(line) for line in log.read_text(encoding="utf-8", errors="replace").splitlines()[-values.lines:]]
    if values.follow:
        import time
        with log.open(encoding='utf-8', errors='replace') as stream:
            for line in text:
                print(line)
            stream.seek(0, 2)
            while True:
                line = stream.readline()
                if line:
                    print(redact(line.rstrip()), flush=True)
                else:
                    time.sleep(.25)
    return _finish("logs", app.scope.name, env.PASS, {"entries": text, "log": str(log)},
                   json_mode=json_mode, text="\n".join(text))


def cmd_doctor(app, args, json_mode):
    checks = []
    data = {"scope": app.scope.name}
    try:
        manager = app.load_manager()
        checks.append(env.Check("manager-config", env.PASS))
        data["backend"] = manager.core.backend
        if manager.core.binary:
            from .trust import require_executable_file
            try:
                require_executable_file(manager.core.binary, as_root=app.scope.system)
                checks.append(env.Check("core-binary", env.PASS, detail=manager.core.binary))
            except MihomoctlError as exc:
                checks.append(env.Check("core-binary", env.FAIL, detail=exc.render()))
    except MihomoctlError as exc:
        checks.append(env.Check("manager-config", env.FAIL, detail=exc.render()))
    try:
        status_data = app.status()
        overall_key = status_data.get("overall")
        checks.append(env.Check("runtime", overall_key if overall_key in (env.PASS, env.FAIL) else env.UNVERIFIED,
                                detail="running=%s" % (status_data.get("runtime") or {}).get("running")))
        data["status"] = {k: status_data.get(k) for k in
                          ("scope", "backend", "listeners", "controller", "tun", "errors")}
    except MihomoctlError as exc:
        checks.append(env.Check("runtime", env.UNVERIFIED, detail=exc.render()))
    try:
        checks.extend(app.health())
    except MihomoctlError as exc:
        checks.append(env.Check("health", env.UNVERIFIED, detail=exc.render()))
    for dependency in ("systemctl", "python3"):
        found = shutil.which(dependency)
        checks.append(env.Check("dependency-%s" % dependency,
                                env.PASS if found else env.SKIPPED,
                                evidence=env.CONFIRMED if found else env.UNAVAILABLE))
    overall = env.combine_checks(checks)
    return _finish("doctor", app.scope.name, overall, data, checks,
                   json_mode=json_mode, text=_checks_text(checks))


# ---------------------------------------------------------------------------
# service / core / tun / integration / export / migrate / installation
# ---------------------------------------------------------------------------

def cmd_service(app, args, json_mode):
    if not args:
        raise UsageError("usage-error", "service requires install|uninstall|start|stop|restart")
    action = args[0]
    scope = app.scope
    if action == 'status':
        data = app.status()
        return _finish('service-status', scope.name, data['overall'], data, json_mode=json_mode, text=_status_text(data))
    if action == "install":
        scope.require_mutation()
        manager, endpoints, controller, profile, _cfg = app.resolve()
        if manager.core.backend == "systemd" and systemd_backend.unit_path(scope).exists():
            systemd_backend.SystemdBackend(scope, manager, endpoints, controller)._require_owned_unit()
            data = {"unit": UNIT_NAME, "installed": True, "changed": False}
            return _finish("service-install", scope.name, env.PASS, data, json_mode=json_mode,
                           text=_kv_text(data))
        if manager.core.backend != "systemd":
            from .lifecycle.process import ProcessBackend
            backend = ProcessBackend(scope, manager, endpoints, controller)
            if backend.running_identity() is not None:
                raise MihomoctlError("backend-active",
                                     "stop the running process backend before switching to systemd")
        from .transaction import run_transaction

        def mutate(tx):
            manager.core.backend = "systemd"
            tx.write_text(scope.manager_path, render_manager(manager), mode=0o600)
        def install(tx):
            nonlocal manager
            manager, current_endpoints, current_controller, _profile, _cfg = app.resolve()
            if manager.core.backend != "systemd":
                from .lifecycle.process import ProcessBackend
                if ProcessBackend(scope, manager, current_endpoints, current_controller).running_identity() is not None:
                    raise MihomoctlError("backend-active", "stop the running process backend before switching to systemd")
            result = systemd_backend.install_unit(manager, scope, tx=tx)
            mutate(tx)
            return result
        # Acquire the operation lock outside recovery handling. A contender
        # must never reload definitions owned by the transaction holding it.
        result = systemd_backend.unit_transaction(scope, "service-install", install)
        return _finish("service-install", scope.name, env.PASS, result, json_mode=json_mode,
                       text=_kv_text(result))
    if action == "uninstall":
        parser = _parser('service-uninstall')
        parser.add_argument('--dry-run', action='store_true')
        values = parser.parse_args(args[1:])
        scope.require_mutation()
        # Preconditions are evaluated in both modes: a preview that could never
        # predict the failure of the real operation is worse than no preview.
        manager, endpoints, controller, _, _ = app.resolve()
        backend = systemd_backend.SystemdBackend(scope, manager, endpoints, controller)
        _running, properties = backend.running()
        if properties.get('ActiveState') not in ('inactive', 'failed', None):
            raise UsageError('backend-active', 'stop the Mihomo service before uninstalling its unit')
        if manager.tun.enabled:
            raise UsageError('tun-enabled', 'disable TUN before uninstalling its managed service')
        if values.dry_run:
            return _finish("service-uninstall-preview", scope.name, env.PASS,
                           {"unit": UNIT_NAME, "dry_run": True},
                           json_mode=json_mode, text="would remove %s" % UNIT_NAME)
        from .transaction import run_transaction
        def uninstall(tx):
            current, current_endpoints, current_controller, _, _ = app.resolve()
            current_backend = systemd_backend.SystemdBackend(scope, current, current_endpoints, current_controller)
            _, properties = current_backend.running()
            if properties.get('ActiveState') not in ('inactive', 'failed', None) or current.tun.enabled:
                raise UsageError('backend-active', 'stop the managed runtime and disable TUN before uninstalling')
            if not scope.system:
                current.core.backend = 'process'
                tx.write_text(scope.manager_path, render_manager(current))
            return systemd_backend.uninstall_unit(scope, tx=tx)
        systemd_backend.unit_transaction(scope, 'service-uninstall', uninstall)
        return _finish("service-uninstall", scope.name, env.PASS, {"unit": UNIT_NAME},
                       json_mode=json_mode, text="removed %s" % UNIT_NAME)
    if action in ("start", "stop", "restart"):
        data = app.lifecycle(action)
        return _finish("service-" + action, scope.name, data.get("overall", env.FAIL), data,
                       json_mode=json_mode, text=_status_text(data))
    raise UsageError("usage-error", "unknown service action %r" % action)


def cmd_core(app, args, json_mode):
    if not args:
        raise UsageError("usage-error", "core requires install|adopt|list")
    action = args[0]
    if action in ("install", 'update'):
        app.scope.require_mutation()
        parser = _parser("core-install")
        parser.add_argument("--version", required=True)
        parser.add_argument("--sha256")
        parser.add_argument("--dry-run", action="store_true")
        values = parser.parse_args(args[1:])
        from .coreinstall import install as core_install
        data = core_install(app.scope, values.version, sha256=values.sha256,
                            dry_run=values.dry_run)
        return _finish("core-install", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    if action == "adopt":
        parser = _parser("core-adopt")
        parser.add_argument("--path", required=True)
        values = parser.parse_args(args[1:])
        from .coreinstall import adopt
        data = adopt(app.scope, values.path)
        return _finish("core-adopt", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    if action == "list":
        from .coreinstall import installed
        data = installed(app.scope)
        return _finish("core-list", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    raise UsageError("usage-error", "unknown core action %r" % action)


def cmd_tun(app, args, json_mode):
    if not args:
        raise UsageError("usage-error", "tun requires enable|disable|status")
    action = args[0]
    from .lifecycle import tun as tun_module
    if action == "status":
        data = tun_module.status(app.scope)
        return _finish("tun-status", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    if action == "enable":
        data = tun_module.enable(app.scope)
        return _finish("tun-enable", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    if action == "disable":
        data = tun_module.disable(app.scope)
        return _finish("tun-disable", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    raise UsageError("usage-error", "unknown tun action %r" % action)


def cmd_integration(app, args, json_mode):
    if not args or args[0] == "list":
        manager = app.load_manager()
        rows = [b.redacted() for b in manager.bindings.values()]
        return _finish("integration-list", app.scope.name, env.PASS, {"bindings": rows},
                       json_mode=json_mode, text=_kv_text({"bindings": rows}))
    action = args[0]
    if action not in ("install", "remove", "check", 'show', 'export') or len(args) < 2:
        raise UsageError("usage-error", "integration requires install|remove|check|list [NAME]")
    binding_name = args[1]
    manager = app.load_manager()
    binding = manager.bindings.get(binding_name)
    if binding is None:
        raise NotFoundError("binding-unknown", binding_name)
    if action == 'show':
        return _finish('integration-show', app.scope.name, env.PASS, binding.redacted(), json_mode=json_mode, text=_kv_text(binding.redacted()))
    if action == 'export':
        return cmd_export(app, ['--binding', binding_name, *args[2:]], json_mode)
    from .integration import systemd_adapter
    if action == "install":
        if binding.adapter != "systemd" or not binding.target:
            raise UsageError("integration-unsupported",
                             "install supports the systemd adapter; use export for artifacts")
        def mutate(tx):
            current = app.load_manager().bindings.get(binding_name)
            if current is None or current.adapter != "systemd" or not current.target:
                raise UsageError("integration-unsupported", "binding changed before installation; inspect it and retry")
            proxy_env = app.proxy_environment(current.profile)
            return systemd_adapter.install(app.scope, current, proxy_env, tx=tx)
        # Include cached-definition recovery for the public CLI path as well
        # as the adapter API, under the same operation lock.
        data = systemd_adapter._transaction(app.scope, "integration-install", mutate)
        return _finish("integration-install", app.scope.name, env.PASS, data,
                       json_mode=json_mode, text=_kv_text(data))
    if action == "remove":
        app.scope.require_mutation()
        data = systemd_adapter.remove(app.scope, binding)
        return _finish("integration-remove", app.scope.name, env.PASS, data,
                       json_mode=json_mode, text=_kv_text(data))
    proxy_env = app.proxy_environment(binding.profile)
    data = systemd_adapter.check(app.scope, binding, proxy_env)
    overall = env.PASS if all(r['state'] == 'current' for r in data['artifacts']) else env.FAIL
    return _finish("integration-check", app.scope.name, overall, data,
                   json_mode=json_mode, text=_kv_text(data))


def cmd_export(app, args, json_mode):
    parser = _parser("export")
    parser.add_argument("--binding", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument('--reveal', action='store_true')
    values = parser.parse_args(args)
    manager = app.load_manager()
    binding = manager.bindings.get(values.binding)
    if binding is None:
        raise NotFoundError("binding-unknown", values.binding)
    from .integration import exporters, load_custom_adapter
    custom = load_custom_adapter(app.scope, binding.adapter)
    proxy_env = app.proxy_environment(binding.profile)
    artifacts = exporters.render_export(binding.adapter, proxy_env, binding, custom)
    written = []
    if values.output_dir:
        from .credentials import write_atomic
        directory = Path(values.output_dir).expanduser()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        for filename, text in artifacts.items():
            if isinstance(text, str):
                path = directory / filename
                write_atomic(path, text, mode=0o600)
                written.append(str(path))
    if not values.reveal:
        from .environment import ProxyEnvironment
        from urllib.parse import urlsplit
        def hide(value):
            url = urlsplit(value)
            host = '[' + url.hostname + ']' if ':' in url.hostname else url.hostname
            return '%s://REDACTED:REDACTED@%s:%d' % (url.scheme, host, url.port)
        shown = exporters.render_export(binding.adapter, ProxyEnvironment(proxy_env.profile,
            hide(proxy_env.http_url), hide(proxy_env.socks_url), proxy_env.no_proxy), binding, custom)
    else:
        shown = artifacts
    data = {"binding": binding.name, "adapter": binding.adapter,
            "artifacts": shown,
            "written": sorted(written), "deployed": False,
            "note": "artifacts are never deployed automatically"}
    return _finish("export", app.scope.name, env.PASS, data, json_mode=json_mode,
                   text=_kv_text(data))


def cmd_migrate(app, args, json_mode):
    from . import migrate as migrate_module
    action = None
    flags = list(args)
    if flags and flags[0] in ("preview", "apply"):
        raise UsageError('usage-error', 'use migrate --dry-run or migrate --apply')
    parser = _parser("migrate")
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--dry-run", action="store_true")
    choice.add_argument("--apply", action="store_true")
    parser.add_argument("--remove-loader", action="store_true")
    parser.add_argument("--no-import", action="store_true")
    parser.add_argument('--core')
    values = parser.parse_args(flags)
    if action is None:
        if values.apply:
            action = "apply"
        elif values.dry_run:
            action = "preview"
        else:
            raise UsageError("usage-error", "migrate requires preview|--dry-run or apply|--apply")
    if action == "preview":
        data = migrate_module.preview(app.scope)
        return _finish("migrate-preview", app.scope.name, env.PASS, data,
                       json_mode=json_mode, text=_kv_text(data))
    data = migrate_module.apply(app.scope, remove_loader=True,
                                import_config=not values.no_import, core=values.core)
    return _finish("migrate-apply", app.scope.name, env.PASS, data,
                   json_mode=json_mode, text=_kv_text(data))


def cmd_installation(command, app, args, json_mode):
    try:
        from . import installation
    except ImportError:
        raise MihomoctlError("installation-unavailable",
                             "the installation module is not present in this build") from None
    if command == "update":
        parser = _parser("update")
        parser.add_argument("source", nargs="?")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--allow-same-version", action="store_true")
        parser.add_argument("--allow-downgrade", action="store_true")
        parser.add_argument('--wheelhouse')
        parser.add_argument('--python')
        values = parser.parse_args(args)
        data = installation.update(app.scope,
                                   source=Path(values.source) if values.source else None,
                                   dry_run=values.dry_run,
                                   allow_same_version=values.allow_same_version,
                                   allow_downgrade=values.allow_downgrade,
                                   wheelhouse=values.wheelhouse, python=values.python)
        return _finish("update", app.scope.name, env.PASS, data, json_mode=json_mode,
                       text=_kv_text(data))
    parser = _parser("rollback")
    parser.add_argument("backup")
    values = parser.parse_args(args)
    backup = Path(values.backup)
    if (backup / 'journal.json').is_file():
        from .transaction import restore_backup
        data = restore_backup(app.scope, backup)
    else:
        data = installation.rollback(app.scope, backup)
    return _finish("rollback", app.scope.name, env.PASS, data, json_mode=json_mode,
                   text=_kv_text(data))


# ---------------------------------------------------------------------------

class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError("usage-error", message)


def _parser(name):
    return _Parser(prog="mihomoctl " + name)


if __name__ == "__main__":
    sys.exit(main())
