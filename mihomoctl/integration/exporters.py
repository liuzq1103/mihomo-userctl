"""Export-only adapters: docker, kubernetes, supervisor, pm2, ci.

These render artifacts; they never deploy, call container APIs or touch
clusters.  Bindings for separate network namespaces must specify a
reachable connect_host; wildcard addresses are never emitted.
"""

import base64
import json
import shlex

from ..errors import ConfigError

from . import render_template

ENV_KEYS = ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'NO_PROXY',
            'http_proxy', 'https_proxy', 'all_proxy', 'no_proxy')


def _values(proxy_env, binding):
    variables = proxy_env.variables()
    return {
        "http_url": variables["HTTP_PROXY"],
        "https_url": variables["HTTPS_PROXY"],
        "socks_url": variables["ALL_PROXY"],
        "no_proxy": variables["NO_PROXY"],
        "profile": proxy_env.profile,
        "binding": binding.name,
        "connect_host": binding.connect_host or "127.0.0.1",
    }


def _require_host(binding):
    host = binding.connect_host
    if not host:
        raise ConfigError("export-requires-connect-host",
                          "binding %s must declare connect_host (reachable address; never a wildcard)"
                          % binding.name)
    return host


def docker(proxy_env, binding):
    """docker --env-file snippet plus a compose env_file reference."""
    variables = proxy_env.variables()
    host = _require_host(binding)
    lines = ["# docker --env-file (mihomoctl export; not deployed)"]
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        lines.append("%s=%s" % (key, variables[key]))
    snippet = "\n".join(lines) + "\n"
    compose = ("# docker-compose.yaml fragment (not deployed)\n"
               "services:\n  %s:\n    env_file:\n      - ./docker.env\n"
               % binding.name)
    return {"docker.env": snippet, "compose-fragment.yaml": compose,
            "connect_host": host}


def kubernetes(proxy_env, binding):
    host = _require_host(binding)
    variables = proxy_env.variables()
    secret_data = {key: base64.b64encode(variables[key].encode()).decode()
                   for key in ENV_KEYS}
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": "mihomoctl-%s" % binding.name},
        "type": "Opaque",
        "data": secret_data,
    }
    fragment = ("# deployment fragment (not deployed)\n"
                "        envFrom:\n"
                "        - secretRef:\n            name: mihomoctl-%s\n" % binding.name)
    return {"k8s-secret.yaml": json.dumps(manifest, indent=2) + "\n",
            "deployment-fragment.yaml": fragment,
            "connect_host": host}


def supervisor(proxy_env, binding):
    variables = proxy_env.variables()
    environment = ",".join('%s="%s"' % (key, variables[key].replace('%', '%%').replace('"', '\\"'))
                           for key in ENV_KEYS)
    text = ("; supervisor program fragment (mihomoctl export; not deployed)\n"
            "[program:%s]\nenvironment=%s\n" % (binding.name, environment))
    return {"supervisor.ini": text}


def pm2(proxy_env, binding):
    variables = proxy_env.variables()
    env = ", ".join('%s: %s' % (key, json.dumps(variables[key]))
                    for key in ENV_KEYS)
    text = ("// pm2 ecosystem fragment (mihomoctl export; not deployed)\n"
            "module.exports = { apps: [{ name: %s, env: { %s } }] };\n"
            % (json.dumps(binding.name), env))
    return {"ecosystem.config.js": text}


def ci(proxy_env, binding):
    variables = proxy_env.variables()
    lines = ["# CI env fragment (mihomoctl export; mask secrets in your CI logs)"]
    for key in ENV_KEYS:
        lines.append("%s: %s" % (key, json.dumps(variables[key])))
    yaml_text = "\n".join(lines) + "\n"
    shell_text = "\n".join("export %s=%s" % (key, shlex.quote(variables[key]))
                           for key in ENV_KEYS) + "\n"
    return {"ci-env.yaml": yaml_text, "ci-env.sh": shell_text}


def render_export(adapter, proxy_env, binding, custom=None):
    kind = custom.get('kind', adapter) if custom else adapter
    if kind in ('docker', 'kubernetes'):
        from urllib.parse import urlsplit
        from ..environment import ProxyEnvironment
        host = _require_host(binding).strip('[]')
        if ':' in host:
            host = '[' + host + ']'
        def rehost(value):
            parsed = urlsplit(value)
            auth = parsed.netloc.rsplit('@', 1)[0] + '@' if '@' in parsed.netloc else ''
            return '%s://%s%s:%d' % (parsed.scheme, auth, host, parsed.port)
        proxy_env = ProxyEnvironment(proxy_env.profile, rehost(proxy_env.http_url), rehost(proxy_env.socks_url), proxy_env.no_proxy)
    if custom and custom.get("template"):
        values = _values(proxy_env, binding)
        rendered = render_template(custom["template"], values, kind=custom['kind'])
        return {"custom." + custom["kind"]: rendered}
    table = {"docker": docker, "kubernetes": kubernetes, "supervisor": supervisor,
             "pm2": pm2, "ci": ci}
    if adapter not in table:
        raise ConfigError("adapter-unknown", "adapter %r has no exporter" % adapter)
    return table[adapter](proxy_env, binding)
