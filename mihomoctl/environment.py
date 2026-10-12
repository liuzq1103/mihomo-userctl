"""Environment generation and exec/direct environment semantics.

Emits HTTP_PROXY, HTTPS_PROXY, ALL_PROXY and NO_PROXY plus lowercase
counterparts.  HTTP(S) uses an HTTP-capable endpoint; ALL_PROXY uses
socks5h.  Missing protocol support is reported instead of guessed.  URL
credentials are percent-encoded.  Exec clears only these eight inherited
proxy keys before applying the selected profile; direct removes them
only.  Neither touches any other environment variable.
"""

from urllib.parse import quote

from .errors import ConfigError

PROXY_KEYS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _url(scheme, host, port, username, password):
    auth = ""
    if username is not None:
        auth = quote(str(username), safe="")
        if password is not None:
            auth += ":" + quote(str(password), safe="")
        auth += "@"
    host = '[' + host + ']' if ':' in host and not host.startswith('[') else host
    return "%s://%s%s:%d" % (scheme, auth, host, port)


class ProxyEnvironment:
    """Resolved URLs and the eight-variable environment for one profile."""

    def __init__(self, profile_name, http_url, socks_url, no_proxy):
        self.profile = profile_name
        self.http_url = http_url
        self.socks_url = socks_url
        self.no_proxy = no_proxy

    def variables(self):
        env = {
            "http_proxy": self.http_url, "HTTP_PROXY": self.http_url,
            "https_proxy": self.http_url, "HTTPS_PROXY": self.http_url,
            "all_proxy": self.socks_url, "ALL_PROXY": self.socks_url,
            "no_proxy": self.no_proxy, "NO_PROXY": self.no_proxy,
        }
        return env

    def redacted(self):
        def hide(url):
            if url is None:
                return None
            scheme, _, rest = url.partition("://")
            if "@" in rest:
                return scheme + "://***@" + rest.rsplit("@", 1)[1]
            return url
        return {"profile": self.profile, "http_proxy": hide(self.http_url),
                "all_proxy": hide(self.socks_url), "no_proxy": self.no_proxy}


def build(profile, endpoints, credentials):
    """Build the proxy environment for ``profile`` from resolved endpoints."""
    from .endpoints import validate_profile_listeners
    chosen = validate_profile_listeners(profile, endpoints)
    http_endpoint = chosen.get("http_listener")
    socks_endpoint = chosen.get("socks_listener")
    missing = []
    if http_endpoint is None:
        missing.append("http/mixed listener for HTTP_PROXY")
    if socks_endpoint is None:
        missing.append("socks/mixed listener for ALL_PROXY")
    if missing:
        raise ConfigError("environment-incomplete",
                          "profile %r is missing %s; available endpoints: %s"
                          % (profile.name, "; ".join(missing),
                             [(e.name, e.type) for e in endpoints]))
    username = password = None
    if credentials is not None:
        username, password = credentials.username, credentials.password
    http_url = _url("http", http_endpoint.address, http_endpoint.port, username, password)
    socks_url = _url("socks5h", socks_endpoint.address, socks_endpoint.port, username, password)
    return ProxyEnvironment(profile.name, http_url, socks_url,
                            ",".join(profile.no_proxy))


def exec_environment(current, proxy_env):
    """Exec semantics: clear the eight inherited proxy keys, then apply the
    profile.  Unrelated environment is retained."""
    env = {k: v for k, v in current.items() if k not in PROXY_KEYS}
    env.update(proxy_env.variables())
    return env


def direct_environment(current):
    return {k: v for k, v in current.items() if k not in PROXY_KEYS}
