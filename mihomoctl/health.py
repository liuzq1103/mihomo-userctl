"""Local health checks: never require public egress success.

Per endpoint (inferred procfs ownership plus live local probes):
- anonymous proxying must be rejected (HTTP 407 / SOCKS auth required);
- valid credentials must be accepted (HTTP non-407 response through the
  proxy to a local target; SOCKS username/password subnegotiation 0x00).
Controller: authenticated loopback /version probe.
Optional egress (opt-in URL only) never gates install or local start.
"""

import base64
import socket
import time
from urllib.parse import urlsplit

from . import envelope as env
from .endpoints import Endpoint

_CONNECT_TIMEOUT = 3.0
_READ_TIMEOUT = 5.0


def _tcp(address, port, timeout=_CONNECT_TIMEOUT):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect((address, port))
    return sock


def _recv(sock, size):
    sock.settimeout(_READ_TIMEOUT)
    return sock.recv(size)


def http_anonymous_rejected(endpoint: Endpoint):
    """Anonymous absolute-URI request must yield 407."""
    try:
        sock = _tcp(endpoint.address, endpoint.port)
        request = ("HEAD http://127.0.0.1:9/ HTTP/1.1\r\nHost: 127.0.0.1:9\r\n"
                   "Proxy-Connection: keep-alive\r\n\r\n")
        sock.sendall(request.encode("ascii"))
        head = _recv(sock, 1024).decode("latin-1", "replace")
        sock.close()
    except OSError:
        return False, "probe-failed"
    status = head.split(" ", 2)[1] if " " in head else ""
    if status == "407":
        return True, "407"
    return False, "status=%s" % (status or "none")


def http_authenticated_accepted(endpoint: Endpoint, username, password):
    """Authenticated request through the proxy to a local closed target:
    any non-407 response proves authentication was accepted."""
    try:
        sock = _tcp(endpoint.address, endpoint.port)
        token = base64.b64encode(("%s:%s" % (username, password)).encode()).decode()
        request = ("HEAD http://127.0.0.1:9/ HTTP/1.1\r\nHost: 127.0.0.1:9\r\n"
                   "Proxy-Authorization: Basic %s\r\nProxy-Connection: close\r\n\r\n" % token)
        sock.sendall(request.encode("ascii"))
        head = _recv(sock, 1024).decode("latin-1", "replace")
        sock.close()
    except OSError:
        return False, "probe-failed"
    status = head.split(" ", 2)[1] if " " in head else ""
    if status and status != "407":
        return True, "status=%s" % status
    return False, "status=%s" % (status or "none")


def socks_authentication(endpoint: Endpoint, username=None, password=None):
    """SOCKS5 probe.  Without credentials: the server must refuse the
    no-auth method (0xFF).  With credentials: user/pass subnegotiation
    must succeed (0x00)."""
    try:
        sock = _tcp(endpoint.address, endpoint.port)
        if username is None:
            sock.sendall(b"\x05\x01\x00")  # offer only NO-AUTH
            reply = _recv(sock, 2)
            sock.close()
            if reply in (b"\x05\xff", b"\x05\x02"):
                return True, "anonymous-rejected"
            return False, "anonymous-accepted"
        sock.sendall(b"\x05\x02\x00\x02")  # NO-AUTH or USER/PASS
        reply = _recv(sock, 2)
        if len(reply) < 2 or reply[1] != 0x02:
            sock.close()
            return False, "auth-not-required"
        user = username.encode()
        pwd = password.encode()
        if len(user) > 255 or len(pwd) > 255:
            sock.close()
            return False, "credential-too-long"
        sock.sendall(bytes([1, len(user)]) + user + bytes([len(pwd)]) + pwd)
        verdict = _recv(sock, 2)
        sock.close()
        if len(verdict) == 2 and verdict[1] == 0:
            return True, "authenticated"
        return False, "auth-rejected"
    except OSError:
        return False, "probe-failed"


def controller_probe(controller, secret, timeout=_CONNECT_TIMEOUT):
    """Two-sided controller verification: anonymous request must be
    rejected (401) and the correct bearer secret accepted (200)."""
    def request(authorization):
        sock = _tcp(controller.address, controller.port, timeout)
        try:
            request = ("GET /version HTTP/1.1\r\nHost: %s:%d\r\n%sConnection: close\r\n\r\n"
                       % (controller.address, controller.port, authorization))
            sock.sendall(request.encode("ascii"))
            head = _recv(sock, 2048).decode("latin-1", "replace")
        finally:
            sock.close()
        status = head.split(" ", 2)[1] if " " in head else ""
        return status or "none"

    try:
        anonymous = request("")
        if anonymous != "401":
            return False, "anonymous-status=%s (expected 401)" % anonymous
        authorized = request("Authorization: Bearer %s\r\n" % secret)
        if authorized == "200":
            return True, "anonymous-401+authorized-200"
        return False, "authorized-status=%s (expected 200)" % authorized
    except OSError:
        return False, "probe-failed"


def egress_probe(proxy_env, url, timeout=10.0):
    """Opt-in real egress verification: a complete TLS+HTTP request to the
    target through the proxy tunnel.  Never a gate for install/local start."""
    import ssl
    from urllib.parse import urlsplit, unquote
    sock = None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return env.Check("egress", env.UNVERIFIED, detail="url-not-https")
        endpoint = urlsplit(proxy_env.http_url)
        port = parsed.port or 443
        sock = _tcp(endpoint.hostname, endpoint.port, timeout)
        token = base64.b64encode(("%s:%s" % (unquote(endpoint.username or ''), unquote(endpoint.password or ''))).encode()).decode()
        connect = "CONNECT %s:%d HTTP/1.1\r\nHost: %s:%d\r\nProxy-Authorization: Basic %s\r\n\r\n" % (
            parsed.hostname, port, parsed.hostname, port, token)
        sock.sendall(connect.encode("ascii"))
        head = _recv(sock, 1024).decode("latin-1", "replace")
        if " 200 " not in head.split("\r\n", 1)[0]:
            status = head.split(" ", 2)[1] if " " in head else "none"
            return env.Check("egress", env.FAIL, detail="connect-status=%s" % status)
        context = ssl.create_default_context()
        tunnel = context.wrap_socket(sock, server_hostname=parsed.hostname)
        try:
            path = parsed.path or "/"
            request = "HEAD %s%s HTTP/1.1\r\nHost: %s\r\nConnection: close\r\n\r\n" % (
                path, ("?" + parsed.query) if parsed.query else "", parsed.hostname)
            tunnel.sendall(request.encode("ascii"))
            response = tunnel.recv(2048).decode("latin-1", "replace")
        finally:
            tunnel.close()
        status = response.split(" ", 2)[1] if " " in response else ""
        if status and status.startswith(("2", "3", "4", "5")):
            return env.Check("egress", env.PASS, detail="tls+http-status=%s" % status)
        return env.Check("egress", env.FAIL, detail="no-http-response")
    except OSError as exc:
        return env.Check("egress", env.UNVERIFIED, evidence=env.UNAVAILABLE,
                         detail="probe-failed: %s" % (exc.__class__.__name__,))
    finally:
        if sock is not None:
            sock.close()
