"""Endpoint normalization and the security envelope for Mihomo configs.

Active named ``listeners`` and legacy top-level ``port`` / ``socks-port`` /
``mixed-port`` (plus ``redir-port`` / ``tproxy-port`` as inert surfaces)
are normalized into Endpoint records.  Disabled zero ports never shadow
listeners.  All listening surfaces are validated, not just the selected
proxy port.

Authentication is per endpoint: named listeners authenticate through
their own ``users`` list; top-level ``authentication`` only covers legacy
ports.  Health checks must verify each endpoint: anonymous must fail,
valid credentials must succeed.

The security envelope (design-reference 10.2) is enforced for any policy
or subscription input: listener/auth/controller/TUN/DNS-listening keys
may not be added, removed or changed.
"""

from dataclasses import dataclass

from .errors import ConfigError

LOOPBACKS = ("127.0.0.1", "::1", "localhost")
PROXY_TYPES = ("http", "socks", "mixed")
INERT_PORT_KEYS = (("port", "http"), ("socks-port", "socks"), ("mixed-port", "mixed"),
                   ("redir-port", "redir"), ("tproxy-port", "tproxy"))

# design-reference 10.2: keys policy/subscription input can never touch.
FORBIDDEN_KEYS = (
    "port", "socks-port", "mixed-port", "redir-port", "tproxy-port",
    "bind-address", "allow-lan", "lan-allowed-ips", "lan-disallowed-ips",
    "authentication", "skip-auth-prefixes",
    "external-controller", "external-controller-tls", "external-controller-unix",
    "external-controller-cors", "external-doh-server", "secret",
    "tun", "listeners",
)
EXISTENCE_PROTECTED = ("external-controller", "external-controller-tls",
                       "external-controller-unix", "external-controller-cors",
                       "external-doh-server", "secret")


@dataclass(frozen=True)
class Endpoint:
    name: str
    source: str        # "listeners" | port/socks-port/mixed-port/redir-port/tproxy-port
    type: str          # http | socks | mixed | redir | tproxy
    address: str       # normalized (localhost -> 127.0.0.1)
    port: int
    legacy: bool
    authenticated: bool = False

    @property
    def supports_http(self):
        return self.type in ("http", "mixed")

    @property
    def supports_socks(self):
        return self.type in ("socks", "mixed")

    @property
    def usable(self):
        return self.type in PROXY_TYPES

    def redacted(self):
        return {"name": self.name, "source": self.source, "type": self.type,
                "address": self.address, "port": self.port, "authenticated": self.authenticated}


@dataclass(frozen=True)
class Controller:
    address: str
    port: int
    authenticated: bool

    def redacted(self):
        return {"address": self.address, "port": self.port, "authenticated": self.authenticated}


def _normalize_address(raw, context, allow_non_loopback):
    if not isinstance(raw, str) or not raw:
        raise ConfigError("config-invalid", "%s: address must be a string" % context)
    address = raw.strip().strip("[]").lower()
    if address == "localhost":
        address = "127.0.0.1"
    try:
        import ipaddress
        address = str(ipaddress.ip_address(address))
    except ValueError:
        raise ConfigError('config-invalid', '%s: listen address must be an IP literal or localhost' % context) from None
    if address in ("0.0.0.0", "::", "*"):
        raise ConfigError("config-invalid",
                          "%s: wildcard bind requires an explicit authorized address" % context)
    if address in LOOPBACKS:
        return address
    if not allow_non_loopback:
        raise ConfigError("config-invalid",
                          "%s: non-loopback address requires system scope and explicit authorization" % context)
    return address


def _port(value, context):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError("config-invalid", "%s: port must be an integer" % context)
    if not 1024 <= value <= 65535:
        raise ConfigError("config-invalid", "%s: port %d outside managed range 1024-65535" % (context, value))
    return value


def _parse_users(raw, context):
    """Listener-level authentication (``users``).  Returns True when the
    listener enforces username/password authentication."""
    if raw is None:
        return False
    if not isinstance(raw, list) or not raw:
        raise ConfigError("config-invalid", "%s: users must be a non-empty list" % context)
    for item in raw:
        if not isinstance(item, dict) or set(item) - {"username", "password"} \
                or not isinstance(item.get("username"), str) or not item["username"] \
                or not isinstance(item.get("password"), str):
            raise ConfigError("config-invalid", "%s: each user needs username/password" % context)
        from .credentials import Credentials
        Credentials(item['username'], item['password'])
    return True


def parse_endpoints(cfg, system_scope=False, allowed_addresses=()):
    """Normalize every listening surface into Endpoint records.

    Returns (endpoints, controller)."""
    if cfg is None:
        cfg = {}
    if not isinstance(cfg, dict):
        raise ConfigError("config-invalid", "core configuration must be a YAML mapping")
    tun = cfg.get('tun') or {}
    if not isinstance(tun, dict):
        raise ConfigError('config-invalid', 'tun must be a mapping')
    if not system_scope and (tun.get('enable') or any(cfg.get(k) for k in ('redir-port', 'tproxy-port'))):
        raise ConfigError('config-invalid', 'TUN and transparent listeners require explicit system authorization')
    if not system_scope and cfg.get('allow-lan'):
        raise ConfigError('config-invalid', 'allow-lan requires explicit system scope authorization')
    dns = cfg.get('dns') or {}
    if not isinstance(dns, dict) or dns.get('listen'):
        raise ConfigError('config-invalid', 'DNS listening is not an authorized V1 surface')
    if cfg.get('skip-auth-prefixes') or cfg.get('external-doh-server'):
        raise ConfigError('config-invalid', 'authentication bypass and DoH listening are not authorized')
    allowed = {str(a).strip().strip("[]").lower() for a in allowed_addresses}
    allow_non_loopback = bool(system_scope and allowed)
    endpoints = []
    names = set()

    def add(name, source, etype, raw_address, port, legacy, authenticated):
        address = _normalize_address(raw_address, source, allow_non_loopback)
        if address not in LOOPBACKS and address not in allowed:
            raise ConfigError("config-invalid",
                              "listener address is not in the authorized non-loopback list")
        if name in names:
            raise ConfigError("config-invalid", "duplicate endpoint name")
        if any(e.address == address and e.port == port for e in endpoints):
            raise ConfigError("config-invalid",
                              "duplicate listener bind")
        names.add(name)
        endpoints.append(Endpoint(name, source, etype, address, port, legacy, authenticated))

    listeners = cfg.get("listeners")
    if listeners is not None:
        if not isinstance(listeners, list):
            raise ConfigError("config-invalid", "listeners must be a list")
        for index, item in enumerate(listeners):
            if not isinstance(item, dict):
                raise ConfigError("config-invalid", "listeners[%d] must be a mapping" % index)
            unknown = set(item) - {"name", "type", "listen", "port", "users"}
            if unknown:
                raise ConfigError("config-invalid", "listeners[%d] has unsupported fields" % index)
            name = item.get("name")
            if not isinstance(name, str) or not name or len(name) > 64 or any(c.isspace() for c in name):
                raise ConfigError("config-invalid", "listeners[%d].name is invalid" % index)
            etype = item.get("type")
            if not isinstance(etype, str) or etype not in PROXY_TYPES + ("redir", "tproxy"):
                raise ConfigError("config-invalid", "listeners[%d].type is not supported" % index)
            authenticated = _parse_users(item.get("users"), "listeners[%d]" % index)
            if etype in ('redir', 'tproxy') and not system_scope:
                raise ConfigError('config-invalid', 'transparent listeners require system scope')
            if etype in PROXY_TYPES and not authenticated:
                raise ConfigError('config-invalid', 'proxy listeners require authentication')
            add(name, "listeners", etype, item.get("listen", "127.0.0.1"),
                _port(item.get("port"), "listeners[%d]" % index), legacy=False,
                authenticated=authenticated)

    # Top-level authentication covers legacy top-level ports only.
    legacy_auth = isinstance(cfg.get("authentication"), list) and len(cfg["authentication"]) > 0
    if legacy_auth and any(not isinstance(v, str) or ':' not in v or not all(v.split(':', 1)) for v in cfg['authentication']):
        raise ConfigError('config-invalid', 'invalid legacy authentication entries')
    allow_lan = bool(cfg.get("allow-lan"))
    legacy_address = cfg.get("bind-address", "*" if allow_lan else "127.0.0.1")
    if allow_lan and legacy_address == "*":
        legacy_address = "0.0.0.0"
    for key, etype in INERT_PORT_KEYS:
        value = cfg.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError("config-invalid", "%s must be an integer" % key)
        if value == 0:
            continue  # disabled: never shadows listeners
        if etype in PROXY_TYPES and not legacy_auth:
            raise ConfigError('config-invalid', 'legacy proxy ports require authentication')
        add(key, key, etype, legacy_address, _port(value, key), legacy=True,
            authenticated=legacy_auth)

    controller = _parse_controller(cfg)
    if controller and any(e.port == controller.port and e.address == controller.address for e in endpoints):
        raise ConfigError('config-invalid', 'controller port conflicts with a listener')
    return endpoints, controller


def listening_surfaces(endpoints, controller):
    return list(endpoints) + ([Endpoint('controller', 'external-controller', 'controller',
                                     controller.address, controller.port, False, True)] if controller else [])


def _parse_controller(cfg):
    unix = cfg.get("external-controller-unix")
    tls = cfg.get("external-controller-tls")
    if unix is not None or tls is not None:
        raise ConfigError("config-invalid",
                          "external-controller-unix/-tls are not supported; use an authenticated loopback external-controller")
    raw = cfg.get("external-controller")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ConfigError("config-invalid", "external-controller must be a string")
    text = raw.strip()
    if text.count(":") < 1:
        raise ConfigError("config-invalid", "external-controller must be host:port")
    host, _, port_text = text.rpartition(":")
    host = host.strip("[]")
    try:
        port = int(port_text)
    except ValueError:
        raise ConfigError("config-invalid", "external-controller port is not an integer") from None
    if host == "localhost":
        host = "127.0.0.1"
    if host not in LOOPBACKS:
        raise ConfigError("config-invalid", "external-controller must be loopback")
    if not 1024 <= port <= 65535:
        raise ConfigError("config-invalid", "external-controller port outside managed range 1024-65535")
    secret = cfg.get("secret")
    import re
    if not isinstance(secret, str) or not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', secret):
        raise ConfigError("config-invalid",
                          "external-controller requires a 32-256 character URL-safe secret")
    return Controller(host, port, True)


def validate_profile_listeners(profile, endpoints):
    """Resolve the profile's http/socks listener references.

    The same endpoint (e.g. one mixed listener) may serve both roles.
    Bind conflicts between distinct endpoints are already rejected at
    parse time; nothing further is enforced here."""
    by_name = {e.name: e for e in endpoints}
    chosen = {}
    for role in ("http_listener", "socks_listener"):
        name = getattr(profile, role) if hasattr(profile, role) else profile.get(role)
        if not name:
            continue
        if name not in by_name:
            raise ConfigError("config-invalid",
                              "profile references an unknown listener")
        endpoint = by_name[name]
        if role == "http_listener" and not endpoint.supports_http:
            raise ConfigError("config-invalid",
                              "selected listener cannot serve HTTP proxy clients")
        if role == "socks_listener" and not endpoint.supports_socks:
            raise ConfigError("config-invalid",
                              "selected listener cannot serve SOCKS clients")
        chosen[role] = endpoint
    return chosen


def assert_security_envelope(before, after, path="policy-input"):
    """Reject any change to listener/auth/controller/TUN/DNS-listening keys
    between two configuration documents (design-reference 10.2)."""
    before = before if isinstance(before, dict) else {}
    after = after if isinstance(after, dict) else {}
    for key in FORBIDDEN_KEYS:
        old, new = before.get(key), after.get(key)
        if key in EXISTENCE_PROTECTED:
            was, now = key in before, key in after
            if was != now or old != new:
                action = "add" if not was else ("remove" if not now else "change")
                raise ConfigError("policy-envelope-violation",
                                  "%s attempted to %s protected key %r" % (path, action, key))
        elif old != new or (key in before) != (key in after):
            raise ConfigError("policy-envelope-violation",
                              "%s attempted to modify protected key %r" % (path, key))
