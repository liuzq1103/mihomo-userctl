"""manager.yaml: the managed runtime configuration model.

Canonical shape (architecture-v1) plus system-only TUN and non-loopback
authorizations.  Unknown fields, duplicate keys, unsafe aliases, invalid
scope paths and cross-scope secret references are rejected.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from .errors import ConfigError
from .yamlutil import strict_load, read_private_yaml

VERSION = 1
BACKENDS = ("process", "systemd")
BUILTIN_ADAPTERS = ("exec", "systemd", "docker", "kubernetes", "supervisor", "pm2", "ci")
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_NO_PROXY = re.compile(r"^(\*?\.)?[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?(:[0-9]{1,5})?$|^[A-Za-z0-9.:_-]+$")


@dataclass
class HealthSettings:
    timeout: int = 10

    @staticmethod
    def parse(value):
        if value is None:
            return HealthSettings()
        if not isinstance(value, dict) or set(value) - {"timeout"}:
            raise ConfigError("config-invalid", "profile health settings allow only timeout")
        timeout = value.get("timeout", 10)
        if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 120:
            raise ConfigError("config-invalid", "profile health.timeout must be an integer 1-120")
        return HealthSettings(timeout)


@dataclass
class Profile:
    name: str
    http_listener: str = None
    socks_listener: str = None
    credentials_file: str = None
    no_proxy: tuple = ("localhost", "127.0.0.1", "::1")
    health: HealthSettings = field(default_factory=HealthSettings)

    def redacted(self):
        return {"name": self.name,
                "http_listener": self.http_listener,
                "socks_listener": self.socks_listener,
                "credentials_file": self.credentials_file,
                "credentials_present": bool(self.credentials_file and Path(self.credentials_file).exists()),
                "no_proxy": list(self.no_proxy),
                "health_timeout": self.health.timeout}


@dataclass
class Binding:
    name: str
    profile: str
    adapter: str
    target: str = None
    connect_host: str = None

    def redacted(self):
        return {"name": self.name, "profile": self.profile, "adapter": self.adapter,
                "target": self.target, "connect_host": self.connect_host}


@dataclass
class TunSettings:
    enabled: bool = False
    device: str = "mihomo0"

    @staticmethod
    def parse(value, system_scope):
        if value is None:
            return TunSettings()
        if not isinstance(value, dict) or set(value) - {"enabled", "device"}:
            raise ConfigError("config-invalid", "tun settings allow only enabled/device")
        enabled = value.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ConfigError("config-invalid", "tun.enabled must be boolean")
        if enabled and not system_scope:
            raise ConfigError("config-invalid", "tun can only be enabled in system scope")
        device = value.get("device", "mihomo0")
        if not isinstance(device, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,15}", device):
            raise ConfigError("config-invalid", "tun.device is invalid")
        return TunSettings(enabled, device)


@dataclass
class CoreSettings:
    binary: str = None
    config: str = None
    backend: str = "process"

    def redacted(self):
        return {"binary": self.binary, "config": self.config,
                "backend": self.backend, "system_scope_backend": "systemd"}


@dataclass
class Manager:
    core: CoreSettings = field(default_factory=CoreSettings)
    default_profile: str = "default"
    profiles: dict = field(default_factory=dict)
    bindings: dict = field(default_factory=dict)
    tun: TunSettings = field(default_factory=TunSettings)
    allow_non_loopback: tuple = ()
    version: int = VERSION


def _require_name(value, context):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ConfigError("config-invalid", "%s must match %s" % (context, _NAME.pattern))
    return value


def _require_abs(value, context):
    if not isinstance(value, str) or not value.startswith("/") or '..' in Path(value).parts or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ConfigError("config-invalid", "%s must be an absolute path" % context)
    return value


def _parse_profile(name, value):
    name = _require_name(name, "profile name")
    allowed = {"http_listener", "socks_listener", "credentials_file", "no_proxy", "health"}
    if not isinstance(value, dict):
        raise ConfigError("config-invalid", "profile %s must be a mapping" % name)
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError("config-invalid", "profile %s has unknown fields" % name)
    profile = Profile(name=name)
    for role in ("http_listener", "socks_listener"):
        raw = value.get(role)
        if raw is not None:
            if not isinstance(raw, str) or not raw or len(raw) > 64 or any(c.isspace() for c in raw):
                raise ConfigError("config-invalid", "profile %s %s is invalid" % (name, role))
            setattr(profile, role, raw)
    if not profile.http_listener and not profile.socks_listener:
        raise ConfigError("config-invalid", "profile %s selects no listener" % name)
    raw_creds = value.get("credentials_file")
    if raw_creds is not None:
        profile.credentials_file = _require_abs(raw_creds, "profile %s credentials_file" % name)
    no_proxy = value.get("no_proxy")
    if no_proxy is not None:
        if not isinstance(no_proxy, list) or not no_proxy or len(no_proxy) > 128:
            raise ConfigError("config-invalid", "profile %s no_proxy must be a non-empty list" % name)
        entries = []
        for item in no_proxy:
            if not isinstance(item, str) or not item or len(item) > 253 or not _NO_PROXY.fullmatch(item):
                raise ConfigError("config-invalid", "profile %s no_proxy entry is invalid" % name)
            entries.append(item)
        profile.no_proxy = tuple(entries)
    profile.health = HealthSettings.parse(value.get("health"))
    return profile


def _parse_binding(name, value, profiles):
    name = _require_name(name, "binding name")
    allowed = {"profile", "adapter", "target", "connect_host"}
    if not isinstance(value, dict):
        raise ConfigError("config-invalid", "binding %s must be a mapping" % name)
    unknown = set(value) - allowed
    if unknown:
        raise ConfigError("config-invalid", "binding %s has unknown fields" % name)
    binding = Binding(name=name, profile=value.get('profile'),
                      adapter=value.get('adapter'))
    binding.profile = value.get("profile")
    if not isinstance(binding.profile, str) or binding.profile not in profiles:
        raise ConfigError("config-invalid", "binding %s references an unknown profile" % name)
    binding.adapter = value.get("adapter")
    if not isinstance(binding.adapter, str) or not binding.adapter or len(binding.adapter) > 32:
        raise ConfigError("config-invalid", "binding %s adapter is invalid" % name)
    if binding.adapter not in BUILTIN_ADAPTERS and not _NAME.fullmatch(binding.adapter):
        raise ConfigError("config-invalid", "binding %s adapter name is invalid" % name)
    binding.target = value.get("target")
    if binding.adapter == "systemd":
        if not isinstance(binding.target, str) or not re.fullmatch(r"[A-Za-z0-9_.@:\\-]+\.service", binding.target or ""):
            raise ConfigError("config-invalid", "binding %s systemd target must be a unit name" % name)
    elif binding.target is not None and not isinstance(binding.target, str):
        raise ConfigError("config-invalid", "binding %s target is invalid" % name)
    binding.connect_host = value.get("connect_host")
    if binding.connect_host is not None:
        if not isinstance(binding.connect_host, str) or not re.fullmatch(r'[A-Za-z0-9.:\[\]-]{1,253}', binding.connect_host) or binding.connect_host.strip("[]") in ("0.0.0.0", "::", "*"):
            raise ConfigError("config-invalid",
                              "binding %s connect_host must be an explicitly reachable address" % name)
    return binding


def parse_manager(data, system_scope=False, scope=None):
    if not isinstance(data, dict):
        raise ConfigError("config-invalid", "manager.yaml must be a mapping")
    allowed = {"version", "core", "default_profile", "profiles", "bindings", "tun", "allow_non_loopback"}
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError("config-invalid", "manager.yaml has unknown fields")
    version = data.get("version")
    if version != VERSION:
        raise ConfigError("config-invalid", "manager.yaml version must be %d" % VERSION)
    manager = Manager()
    core = data.get("core") or {}
    if not isinstance(core, dict) or set(core) - {"binary", "config", "backend", "adopted"}:
        raise ConfigError("config-invalid", "core settings are invalid")
    manager.core = CoreSettings(
        binary=_require_abs(core["binary"], "core.binary") if core.get("binary") else None,
        config=_require_abs(core["config"], "core.config") if core.get("config") else None,
        backend=core.get("backend", "process"),
    )
    if system_scope:
        manager.core.backend = "systemd"
    elif manager.core.backend not in BACKENDS:
        raise ConfigError("config-invalid", "core.backend must be one of %s" % (list(BACKENDS),))
    default = data.get("default_profile", "default")
    if not isinstance(default, str):
        raise ConfigError("config-invalid", "default_profile must be a string")
    manager.default_profile = default
    profiles = data.get("profiles") or {}
    if not isinstance(profiles, dict) or not profiles:
        raise ConfigError("config-invalid", "manager.yaml requires at least one profile")
    for name, value in profiles.items():
        manager.profiles[_require_name(name, "profile name")] = _parse_profile(name, value)
    if manager.default_profile not in manager.profiles:
        raise ConfigError("config-invalid", "default_profile is not defined")
    bindings = data.get("bindings") or {}
    if not isinstance(bindings, dict):
        raise ConfigError("config-invalid", "bindings must be a mapping")
    for name, value in bindings.items():
        manager.bindings[_require_name(name, "binding name")] = _parse_binding(name, value, manager.profiles)
    manager.tun = TunSettings.parse(data.get("tun"), system_scope)
    addresses = data.get("allow_non_loopback") or ()
    if addresses:
        if not system_scope:
            raise ConfigError("config-invalid", "non-loopback authorization requires system scope")
        if not isinstance(addresses, list):
            raise ConfigError("config-invalid", "allow_non_loopback must be a list")
        for item in addresses:
            if not isinstance(item, str) or not item or len(item) > 45:
                raise ConfigError("config-invalid", "allow_non_loopback entry is invalid")
    manager.allow_non_loopback = tuple(addresses)
    if scope is not None:
        _check_scope_paths(manager, scope, system_scope)
    return manager


def _check_scope_paths(manager, scope, system_scope):
    for profile in manager.profiles.values():
        path = profile.credentials_file
        if path is None:
            continue
        if system_scope:
            if not Path(path).is_relative_to(scope.config_root):
                raise ConfigError("config-invalid",
                                  "system credentials must stay under %s" % scope.config_root)
        else:
            if path.startswith("/etc/mihomoctl") or path.startswith("/var/lib/mihomoctl"):
                raise ConfigError("config-invalid", "user profile cannot reference system secrets")
            if not scope.is_private_user_path(path):
                raise ConfigError("config-invalid",
                                  "credentials_file must live inside the user's mihomoctl roots")


def load_manager(scope):
    data = read_private_yaml(scope.manager_path, code="config-invalid")
    return parse_manager(data, system_scope=scope.system, scope=scope)


def render_manager(manager):
    lines = ["version: %d" % manager.version]
    lines.append("core:")
    if manager.core.binary:
        lines.append("  binary: %s" % _quote(manager.core.binary))
    if manager.core.config:
        lines.append("  config: %s" % _quote(manager.core.config))
    lines.append("  backend: %s" % manager.core.backend)
    lines.append("default_profile: %s" % _quote(manager.default_profile))
    lines.append("profiles:")
    for name in sorted(manager.profiles):
        p = manager.profiles[name]
        lines.append("  %s:" % name)
        if p.http_listener:
            lines.append("    http_listener: %s" % _quote(p.http_listener))
        if p.socks_listener:
            lines.append("    socks_listener: %s" % _quote(p.socks_listener))
        if p.credentials_file:
            lines.append("    credentials_file: %s" % _quote(p.credentials_file))
        lines.append("    no_proxy: [%s]" % ", ".join(_quote(x) for x in p.no_proxy))
        lines.append("    health:")
        lines.append("      timeout: %d" % p.health.timeout)
    if manager.bindings:
        lines.append("bindings:")
        for name in sorted(manager.bindings):
            b = manager.bindings[name]
            lines.append("  %s:" % name)
            lines.append("    profile: %s" % _quote(b.profile))
            lines.append("    adapter: %s" % _quote(b.adapter))
            if b.target:
                lines.append("    target: %s" % _quote(b.target))
            if b.connect_host:
                lines.append("    connect_host: %s" % _quote(b.connect_host))
    if manager.allow_non_loopback:
        lines.append("allow_non_loopback: [%s]" % ", ".join(_quote(a) for a in manager.allow_non_loopback))
    if manager.tun.enabled or manager.tun.device != "mihomo0":
        lines.append("tun:")
        lines.append("  enabled: %s" % ("true" if manager.tun.enabled else "false"))
        lines.append("  device: %s" % _quote(manager.tun.device))
    return "\n".join(lines) + "\n"


def _quote(value):
    return '"%s"' % str(value).replace("\\", "\\\\").replace('"', '\\"')


def compose_core_config(port, username, password, controller_port, secret,
                        mode="rule", extra=None, listener_name="proxy"):
    """The initial managed core configuration: an authenticated loopback
    named mixed listener (per-listener ``users``; top-level authentication
    only covers legacy ports) plus an authenticated loopback controller.
    ``profile.store-selected`` is emitted explicitly so Selector choices
    survive a restart; relying on the core default leaves the first member —
    often an airport ``Expire:`` information node — selected again.
    Routing policy (rules/proxies) is intentionally minimal and is the
    only area policy input may manage."""
    text = [
        "mode: %s" % mode,
        "listeners:",
        "  - name: %s" % listener_name,
        "    type: mixed",
        "    listen: 127.0.0.1",
        "    port: %d" % port,
        "    users:",
        "      - username: %s" % _quote(username),
        "        password: %s" % _quote(password),
        "external-controller: 127.0.0.1:%d" % controller_port,
        "secret: %s" % _quote(secret),
        "profile:",
        "  store-selected: true",
        "rules:",
        "  - MATCH,DIRECT",
    ]
    if extra:
        text.extend(extra)
    return "\n".join(text) + "\n"
