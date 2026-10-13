"""Bounded, non-disruptive control-plane observation helpers."""
from dataclasses import dataclass
import ipaddress
import os
import subprocess
from urllib.parse import urlsplit


try:
    from . import reporting
except ImportError:  # Installed modules are executed from one runtime directory.
    import reporting


@dataclass
class Result:
    status: str
    check: str
    evidence: str


def clean_environment():
    names = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
    return {key: value for key, value in os.environ.items()
            if key.lower() not in names and not key.startswith("MIHOMO_")}


def run_command(args, timeout, env=None):
    try:
        return subprocess.run(args, env=clean_environment() if env is None else env,
                              capture_output=True, text=True, timeout=timeout,
                              check=False)
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        return None


def listener_check(port, timeout):
    proc = run_command(["ss", "-H", "-ltn", "sport = :" + str(port)], timeout)
    if proc is None or proc.returncode:
        return Result("UNVERIFIED", "listener-binding", "ss-error")
    rows = [line.split() for line in proc.stdout.splitlines() if line.strip()]
    if not rows:
        return Result("FAIL", "listener-binding", "no-listener")
    if any(len(row) < 5 or row[0] != "LISTEN" for row in rows):
        return Result("UNVERIFIED", "listener-binding", "unrecognized-ss-output")
    if any(row[3] != "127.0.0.1:" + str(port) for row in rows):
        return Result("FAIL", "listener-binding", "non-loopback-or-unexpected-binding")
    return Result("PASS", "listener-binding", "selected-port-ipv4-loopback-only")


def public_https_url(url):
    try:
        parsed = urlsplit(url)
        target_port = parsed.port if parsed.port is not None else 443
        hostname = parsed.hostname.rstrip(".").lower() if parsed.hostname else ""
        if (not 1 <= target_port <= 65535 or parsed.scheme != "https" or not hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment
                or hostname == "localhost" or hostname.endswith((".localhost", ".local"))
                or "." not in hostname
                or any(ord(char) < 33 or ord(char) == 127 for char in url)):
            return False
        try:
            address = ipaddress.ip_address(parsed.hostname)
            if not address.is_global:
                return False
        except ValueError:
            pass
        return True
    except ValueError:
        return False
