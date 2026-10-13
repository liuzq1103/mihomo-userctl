"""The shared facade: mihomoctl.app.Application.

``Application(system=False, config_dir=None)`` — construction performs no
changes.  ``status()`` / ``health(profile, egress_url)`` /
``lifecycle(action)`` / ``profiles()``; ``context`` exposes resolved
scope paths; ``config_path`` exposes the active core configuration for
the retained Controller bridge.  CLI serialization stays in cli.py.
"""

import json
from pathlib import Path

from . import envelope as env
from .config import Manager, load_manager, render_manager
from .credentials import Credentials
from .endpoints import parse_endpoints, validate_profile_listeners
from .environment import build as build_environment
from .errors import ConfigError, MihomoctlError, NotFoundError, StateError, UsageError
from .health import (controller_probe, http_anonymous_rejected,
                     http_authenticated_accepted, socks_authentication)
from .lifecycle import ports
from .lifecycle.process import ProcessBackend
from .lifecycle.systemd import SystemdBackend
from .scope import Scope
from .trust import require_readable_core_config
from .yamlutil import strict_load

UNIT_NAME = "mihomoctl.service"


class Application:
    def __init__(self, system=False, config_dir=None):
        self.scope = Scope(system=system, config_dir=config_dir)

    # ------------------------------------------------------------------
    # shared properties
    # ------------------------------------------------------------------
    @property
    def context(self):
        result = self.scope.context()
        result['paths'] = dict(result)
        try:
            manager = self.load_manager()
            result['default_profile'] = manager.default_profile
            result['bindings'] = {name: binding.redacted() for name, binding in manager.bindings.items()}
        except MihomoctlError:
            result.update(default_profile=None, bindings={})
        return result

    @property
    def system(self):
        return self.scope.system

    @property
    def config_path(self):
        manager = self.load_manager()
        return manager.core.config

    # ------------------------------------------------------------------
    # loading helpers (also for the TUI / E)
    # ------------------------------------------------------------------
    def load_manager(self):
        return load_manager(self.scope)

    def resolve(self, profile_name=None):
        """Manager + endpoints + controller + chosen profile."""
        manager = self.load_manager()
        if manager.core.config is None:
            raise ConfigError("not-initialized", "no managed configuration; run mihomoctl init")
        require_readable_core_config(manager.core.config, system_scope=self.scope.system)
        cfg = strict_load(Path(manager.core.config).read_text(encoding="utf-8"))
        if bool((cfg.get('tun') or {}).get('enable')) != manager.tun.enabled:
            raise ConfigError('tun-authorization-mismatch', 'TUN configuration must be changed through tun enable/disable')
        if manager.tun.enabled:
            from .trust import require_private_file
            require_private_file(self.scope.tun_receipt, code='tun-authorization-missing')
            receipt = json.loads(self.scope.tun_receipt.read_text(encoding='utf-8'))
            if not receipt.get('enabled') or receipt.get('device') != manager.tun.device:
                raise ConfigError('tun-authorization-mismatch', 'TUN authorization does not match the configured device')
        endpoints, controller = parse_endpoints(cfg, system_scope=self.scope.system,
                                                allowed_addresses=manager.allow_non_loopback)
        name = profile_name or manager.default_profile
        profile = manager.profiles.get(name)
        if profile is None:
            raise NotFoundError("profile-unknown", repr(name))
        selected = validate_profile_listeners(profile, endpoints)
        creds = self.credentials(profile)
        if creds is None:
            raise ConfigError('profile-credentials-required', 'profile must reference private credentials')
        for endpoint in selected.values():
            if endpoint.legacy:
                pairs = [tuple(v.split(':', 1)) for v in cfg.get('authentication', [])]
            else:
                users = next(row.get('users', []) for row in cfg.get('listeners', []) if row['name'] == endpoint.name)
                pairs = [(row['username'], row['password']) for row in users]
            if (creds.username, creds.password) not in pairs:
                raise ConfigError('profile-credentials-mismatch', 'profile credentials do not match the selected listener')
        return manager, endpoints, controller, profile, cfg

    def credentials(self, profile):
        if not profile.credentials_file:
            return None
        return Credentials.load(profile.credentials_file)

    def credentials_for_endpoint(self, endpoint, cfg, profile):
        if endpoint.name in (profile.http_listener, profile.socks_listener):
            return self.credentials(profile)
        if endpoint.legacy:
            entries = cfg.get('authentication') or []
            if entries:
                return Credentials(*entries[0].split(':', 1))
        else:
            for item in cfg.get('listeners', []):
                if item.get('name') == endpoint.name and item.get('users'):
                    return Credentials(**item['users'][0])
        return None

    def proxy_environment(self, profile_name=None):
        manager, endpoints, _controller, profile, _cfg = self.resolve(profile_name)
        return build_environment(profile, endpoints, self.credentials(profile))

    # ------------------------------------------------------------------
    # frozen public API (E/TUI contract): single-value returns
    # ------------------------------------------------------------------
    def status(self):
        """Status data dict (includes ``overall`` and ``errors``)."""
        return self._status_result()[0]

    def health(self, profile=None, egress_url=None):
        """Checks list; each Check carries name/status/evidence/detail."""
        return self._health_result(profile, egress_url)[1]

    def lifecycle(self, action):
        """Lifecycle result data dict (includes ``overall``)."""
        if action not in ("start", "stop", "restart"):
            raise UsageError("lifecycle-unknown", repr(action))
        from .locks import operation_lock
        self.scope.require_mutation()
        def local_health():
            _data, checks, overall = self._health_result(profile.name)
            return overall == env.PASS, "; ".join(
                "%s=%s" % (c.name, c.status) for c in checks if c.status != env.PASS)

        with operation_lock(self.scope):
            manager, endpoints, controller, profile, _cfg = self.resolve()
            backend = self._backend(manager, endpoints, controller)
            if action == "start":
                backend.start(health_check=local_health)
            elif action == "stop":
                backend.stop()
            else:
                backend.restart(health_check=local_health)
        result = self.status()
        if action == 'stop' and not result.get('runtime', {}).get('running'):
            result['overall'] = env.PASS
        return result

    def profiles(self):
        manager = self.load_manager()
        return [manager.profiles[name].redacted() for name in sorted(manager.profiles)]

    # ------------------------------------------------------------------
    # internal helpers returning (data, overall) / (data, checks, overall)
    # ------------------------------------------------------------------
    def _status_result(self):
        data = {"scope": self.scope.name, "backend": None, "core": None,
                "controller": None, "listeners": [], "active_config": None,
                "proxy": None, "mode": None, "tun": None, "errors": []}
        errors = data["errors"]
        try:
            manager, endpoints, controller, profile, cfg = self.resolve()
        except MihomoctlError as exc:
            errors.append(exc.render())
            data["core"] = {"initialized": False}
            data.update(overall=env.UNVERIFIED, evidence=env.UNAVAILABLE, error=exc.code)
            return data, env.UNVERIFIED
        data["backend"] = manager.core.backend
        data["core"] = {"binary": manager.core.binary, "config": manager.core.config,
                        "backend": manager.core.backend, "initialized": True}
        data["controller"] = controller.redacted() if controller else None
        data["listeners"] = [e.redacted() for e in endpoints]
        data["active_config"] = manager.core.config
        data['config'] = {'path': manager.core.config, 'active': True}
        data["mode"] = cfg.get("mode") if isinstance(cfg.get("mode"), str) else None
        data['proxy_mode'] = 'tun' if manager.tun.enabled else 'listener-environment'
        data['routing_mode'] = data['mode'] or 'unknown'
        data["tun"] = {"enabled": bool(manager.tun.enabled), "device": manager.tun.device,
                       "system_only": True}
        try:
            proxy_env = build_environment(profile, endpoints, self.credentials(profile))
            data["proxy"] = proxy_env.redacted()
        except MihomoctlError as exc:
            errors.append(exc.render())
        runtime = self._backend(manager, endpoints, controller).status()
        data["runtime"] = runtime
        data['core']['status'] = 'running' if runtime.get('running') else runtime.get('detail', 'stopped')
        identity = self._backend(manager, endpoints, controller).running_identity() if runtime.get('running') else None
        from .identity import owns_listener
        for row in data['listeners']:
            row['status'] = 'listening' if identity is not None and owns_listener(identity, row['address'], row['port']) else 'not-listening'
            row['evidence'] = env.INFERRED if identity is not None else env.UNAVAILABLE
        if data['controller']:
            data['controller']['status'] = 'listening' if identity is not None and owns_listener(identity, controller.address, controller.port) else 'not-listening'
            data['controller']['evidence'] = env.INFERRED if identity is not None else env.UNAVAILABLE
        data['evidence'] = env.INFERRED
        data['error'] = errors[0] if errors else (None if runtime.get('running') else runtime.get('detail', 'runtime-not-running'))
        overall = env.PASS if runtime.get("running") and runtime.get('listening', True) else env.FAIL
        if errors and overall == env.PASS:
            overall = env.FAIL
        data["overall"] = overall
        return data, overall

    def _health_result(self, profile=None, egress_url=None):
        checks = []
        try:
            manager, endpoints, controller, prof, _cfg = self.resolve(profile)
            checks.append(env.Check("manager-config", env.PASS))
        except MihomoctlError as exc:
            checks.append(env.Check("manager-config", env.FAIL, detail=exc.render()))
            return {"profile": profile, "overall": env.combine_checks(checks)}, checks, env.combine_checks(checks)
        data = {"profile": prof.name}
        runtime = self._backend(manager, endpoints, controller).status()
        running = bool(runtime.get("running"))
        checks.append(env.Check('runtime', env.PASS if running else env.FAIL,
                                evidence=env.INFERRED, detail=runtime.get('detail', 'identity checked')))
        identity = self._backend(manager, endpoints, controller).running_identity() if running else None
        for endpoint in endpoints:
            if not endpoint.usable:
                continue
            name = "listener-%s" % endpoint.name
            if not running:
                checks.append(env.Check(name, env.SKIPPED, detail="runtime-not-running"))
                continue
            rows = ports.listening_rows(endpoint.address, endpoint.port)
            if not rows:
                checks.append(env.Check(name, env.FAIL, evidence=env.CONFIRMED,
                                        detail="%s:%d not listening" % (endpoint.address, endpoint.port)))
                continue
            from .identity import owns_listener
            owned = (identity is not None and owns_listener(identity, endpoint.address, endpoint.port))
            checks.append(env.Check(name, env.PASS if owned else env.FAIL,
                                    evidence=env.INFERRED if owned else env.UNAVAILABLE,
                                    detail="%s:%d listening (uid ownership %s)"
                                           % (endpoint.address, endpoint.port,
                                              "confirmed" if owned else "unverified")))
            creds = self.credentials_for_endpoint(endpoint, _cfg, prof)
            timeout = prof.health.timeout
            if endpoint.authenticated and creds is not None:
                if endpoint.supports_http:
                    ok, detail = http_anonymous_rejected(endpoint)
                    checks.append(env.Check("auth-anon-%s" % endpoint.name,
                                            env.PASS if ok else env.FAIL, detail=detail))
                    ok, detail = http_authenticated_accepted(endpoint, creds.username, creds.password)
                    checks.append(env.Check("auth-http-%s" % endpoint.name,
                                            env.PASS if ok else env.FAIL, detail=detail))
                if endpoint.supports_socks:
                    ok, detail = socks_authentication(endpoint)
                    checks.append(env.Check("auth-socks-anon-%s" % endpoint.name,
                                            env.PASS if ok else env.FAIL, detail=detail))
                    ok, detail = socks_authentication(endpoint, creds.username, creds.password)
                    checks.append(env.Check("auth-socks-%s" % endpoint.name,
                                            env.PASS if ok else env.FAIL, detail=detail))
            else:
                checks.append(env.Check("auth-%s" % endpoint.name, env.FAIL,
                                        detail="authenticated endpoint credentials required"))
        if controller is not None:
            if not running:
                checks.append(env.Check("controller", env.SKIPPED, detail="runtime-not-running"))
            else:
                from .identity import owns_listener
                owned = identity is not None and owns_listener(identity, controller.address, controller.port)
                checks.append(env.Check('controller-ownership', env.PASS if owned else env.FAIL,
                                        evidence=env.INFERRED if owned else env.UNAVAILABLE))
                secret = _controller_secret(_cfg)
                if secret:
                    ok, detail = controller_probe(controller, secret, timeout=prof.health.timeout)
                    checks.append(env.Check("controller", env.PASS if ok else env.FAIL, detail=detail))
                else:
                    checks.append(env.Check("controller", env.FAIL, detail="secret-missing"))
        else:
            checks.append(env.Check("controller", env.SKIPPED, detail="not-configured"))
        if egress_url:
            try:
                proxy_env = build_environment(prof, endpoints, self.credentials(prof))
                from .health import egress_probe
                checks.append(egress_probe(proxy_env, egress_url))
            except MihomoctlError as exc:
                checks.append(env.Check("egress", env.UNVERIFIED, detail=exc.render()))
        overall = env.combine_checks(checks)
        data["overall"] = overall
        return data, checks, overall

    def _backend(self, manager, endpoints, controller):
        if manager.core.backend == "systemd":
            return SystemdBackend(self.scope, manager, endpoints, controller)
        return ProcessBackend(self.scope, manager, endpoints, controller)

    # ------------------------------------------------------------------
    # init (explicit creation of the managed runtime)
    # ------------------------------------------------------------------
    def initialize(self, core, port=None, config_file=None, allow_non_loopback=(),
                   profile_name="default"):
        import secrets

        from .config import CoreSettings, Profile, compose_core_config
        from .credentials import _yaml_str, generate
        from .lifecycle import ports as ports_mod, runner
        from .transaction import run_transaction
        from .trust import require_executable_file

        scope = self.scope
        scope.require_mutation()
        if scope.manager_path.exists():
            raise UsageError("already-initialized",
                             "%s exists; migration is explicit (mihomoctl migrate)" % scope.manager_path)
        require_executable_file(core, as_root=scope.system)
        if port is None:
            port = ports_mod.free_port()
            candidate = True
        else:
            candidate = False
        if not isinstance(port, int) or not 1024 <= port <= 65535:
            raise ConfigError("port-invalid", str(port))
        controller_port = ports_mod.free_port()
        secret = secrets.token_urlsafe(32)
        username = generate("user")
        password = generate()

        as_uid = None
        if scope.system:
            from .lifecycle.systemd import ensure_service_account
            as_uid = ensure_service_account(create=True).pw_uid

        if config_file is not None:
            source = Path(config_file)
            if not source.is_file():
                raise ConfigError("import-config-missing", str(source))
            imported = source.read_text(encoding="utf-8")
            cfg = strict_load(imported)
            if not isinstance(cfg, dict):
                raise ConfigError("import-config-invalid", "must be a mapping")
            if (cfg.get('tun') or {}).get('enable'):
                raise ConfigError('import-tun-forbidden', 'disable imported TUN and enable it explicitly after initialization')
            cfg.setdefault("listeners", [{"name": "proxy", "type": "mixed",
                                          "listen": "127.0.0.1", "port": port,
                                          "users": [{"username": username, "password": password}]}])
            if "external-controller" not in cfg:
                cfg["external-controller"] = "127.0.0.1:%d" % controller_port
                cfg["secret"] = secret
            # An imported config without store-selected silently drops every
            # Selector choice on the next restart. Preserve the rest of the
            # imported profile block and enforce just that key.
            imported_profile = cfg.get("profile", {})
            if not isinstance(imported_profile, dict):
                raise ConfigError("config-invalid", "profile must be a mapping")
            cfg["profile"] = dict(imported_profile, **{"store-selected": True})
            import yaml
            config_text = yaml.safe_dump(cfg, sort_keys=True, allow_unicode=False)
        else:
            config_text = compose_core_config(port, username, password, controller_port, secret)

        endpoints, controller = parse_endpoints(
            strict_load(config_text), system_scope=scope.system,
            allowed_addresses=allow_non_loopback)
        usable = [e for e in endpoints if e.usable]
        if not usable:
            raise ConfigError("config-invalid", "no usable proxy listener in configuration")
        http_listener = next((e.name for e in usable if e.supports_http), None)
        socks_listener = next((e.name for e in usable if e.supports_socks), None)
        # Imported routing stays intact. Select credentials actually configured
        # on the chosen listener instead of inventing a mismatched client secret.
        if config_file is not None:
            chosen_names = {http_listener, socks_listener} - {None}
            imported_credentials = []
            for endpoint in usable:
                if endpoint.name not in chosen_names:
                    continue
                if endpoint.legacy:
                    entries = cfg.get('authentication') or []
                    pairs = [tuple(v.split(':', 1)) for v in entries]
                else:
                    users = next(v.get('users', []) for v in cfg.get('listeners', []) if v['name'] == endpoint.name)
                    pairs = [(v['username'], v['password']) for v in users]
                imported_credentials.append(set(pairs))
            common = set.intersection(*imported_credentials) if imported_credentials else set()
            if not common:
                raise ConfigError('import-credentials-incompatible', 'selected listeners must share a credential pair')
            username, password = sorted(common)[0]
        listener = http_listener or socks_listener
        runner.validate_config(core, config_text, scope.core_home, as_uid=as_uid)

        creds_path = scope.credentials_dir / (profile_name + ".yaml")
        config_path = scope.config_root / "mihomo" / "config.yaml"

        def action(tx):
            tx.write_text(creds_path,
                          "username: %s\npassword: %s\n" % (
                              _yaml_str(username), _yaml_str(password)),
                          mode=0o600)
            mode = 0o640 if scope.system else 0o600
            tx.write_text(config_path, config_text, mode=mode)
            profile = Profile(name=profile_name, http_listener=http_listener,
                              socks_listener=socks_listener, credentials_file=str(creds_path))
            manager_obj = Manager(core=CoreSettings(binary=str(core), config=str(config_path),
                                                    backend="systemd" if scope.system else "process"),
                                  default_profile=profile_name,
                                  profiles={profile_name: profile})
            if allow_non_loopback:
                manager_obj.allow_non_loopback = tuple(allow_non_loopback)
            tx.write_text(scope.manager_path, render_manager(manager_obj), mode=0o600)
            from .trust import require_private_dir
            require_private_dir(scope.core_home, create=True)
            if scope.system:
                from .lifecycle.systemd import _prepare_system_paths
                _prepare_system_paths(scope, manager_obj)
            return None

        run_transaction(scope, "init", action)
        return {"port": port, "port_is_candidate": candidate,
                "controller_port": controller_port,
                "listener": listener, "backend": "systemd" if scope.system else "process",
                "manager": str(scope.manager_path), "config": str(config_path),
                "credentials": str(creds_path),
                "core": {"binary": str(core), "adopted": True},
                "username": username}


def _expected_uid(scope):
    import os
    if scope.system:
        from .lifecycle.systemd import service_account_uid
        return service_account_uid()
    return os.geteuid() if hasattr(os, "geteuid") else os.getuid()


def _controller_secret(cfg):
    secret = cfg.get("secret")
    return secret if isinstance(secret, str) and secret else None
