"""Runtime integration: declarative bindings and adapters.

Bindings are declarative data.  Built-in adapters: exec, systemd, docker,
kubernetes, supervisor, pm2, ci.  Custom adapters are versioned templates
with an allowlist of placeholders and format-specific escaping — no eval,
no imports, no command execution.  Exported artifacts are never deployed
automatically.
"""

from dataclasses import dataclass

from ..errors import ConfigError

MARKER = "# mihomoctl managed integration v1"
PLACEHOLDERS = ("http_url", "https_url", "socks_url", "no_proxy",
                "profile", "binding", "connect_host")


@dataclass
class ResolvedBinding:
    name: str
    adapter: str
    profile: str
    target: str = None
    connect_host: str = None

    def redacted(self):
        return {"name": self.name, "adapter": self.adapter, "profile": self.profile,
                "target": self.target, "connect_host": self.connect_host}


def load_custom_adapter(scope, name):
    """Custom adapters are declarative template documents (JSON/YAML).

    Schema: {"format": 1, "kind": "<builtin render kind>", "template": "..."}
    Placeholders are limited to PLACEHOLDERS; anything else is rejected."""
    from ..yamlutil import read_private_yaml
    if name in ("exec", "systemd", "docker", "kubernetes", "supervisor", "pm2", "ci"):
        return {"format": 1, "kind": name, "template": None}
    path = scope.adapters_dir / (name + ".json")
    if not path.exists():
        raise ConfigError("adapter-unknown", "adapter %r is not built-in and %s is missing" % (name, path))
    data = read_private_yaml(path, code="adapter-invalid")
    if not isinstance(data, dict) or set(data) != {'format', 'kind', 'template'} or data.get("format") != 1 \
            or data.get("kind") not in ("docker", "kubernetes", "supervisor", "pm2", "ci") \
            or not isinstance(data.get("template"), str) or len(data["template"]) > 65536:
        raise ConfigError("adapter-invalid", "custom adapter must declare format 1, a supported kind and a template")
    for token in _tokens(data["template"]):
        if token not in PLACEHOLDERS:
            raise ConfigError("adapter-invalid", "template placeholder {%s} is not allowed" % token)
    return data


def _tokens(template):
    import re
    return re.findall(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}", template)


def render_template(template, values, kind='docker'):
    """Replace standalone value literals, using the target format's quoting.

    YAML/JavaScript placeholders include their quotes; templates must not
    surround them with another quote pair. Docker env values remain plain,
    Supervisor values use its quoted environment-value representation.
    Templates are data and are never executed by mihomoctl.
    """
    import json
    import re
    if kind not in ('docker', 'kubernetes', 'supervisor', 'pm2', 'ci'):
        raise ConfigError('adapter-invalid', 'unsupported template format')
    for token in _tokens(template):
        if token not in PLACEHOLDERS:
            raise ConfigError('adapter-invalid', 'unknown template placeholder')
    for token in PLACEHOLDERS:
        if re.search(r'\{' + re.escape(token) + r'(?![A-Za-z0-9_]|\})', template):
            raise ConfigError('adapter-invalid', 'malformed template placeholder')
    def replace(match):
        key = match.group(1)
        if key not in PLACEHOLDERS:
            raise ConfigError("adapter-invalid", "placeholder {%s} not allowed" % key)
        value = values.get(key)
        if value is None:
            raise ConfigError("adapter-incomplete", "value for {%s} is unavailable" % key)
        value = str(value)
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ConfigError('adapter-invalid', 'template values cannot contain control characters')
        if kind in ('kubernetes', 'pm2', 'ci'):
            if match.start() and template[match.start() - 1] in '\'"' or \
                    match.end() < len(template) and template[match.end()] in '\'"':
                raise ConfigError('adapter-invalid', 'value placeholders must not be quoted by the template')
            return json.dumps(value, ensure_ascii=True)
        if kind == 'supervisor':
            if match.start() and template[match.start() - 1] in '\'"' or \
                    match.end() < len(template) and template[match.end()] in '\'"':
                raise ConfigError('adapter-invalid', 'value placeholders must not be quoted by the template')
            return '"' + value.replace('%', '%%').replace('\\', '\\\\').replace('"', '\\"') + '"'
        return value
    return re.sub(r"\{([A-Za-z_][A-Za-z0-9_-]*)\}", replace, template)
