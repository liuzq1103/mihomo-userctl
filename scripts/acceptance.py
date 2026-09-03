#!/usr/bin/env python3
"""Non-disruptive listener acceptance; public diagnostics only, never raw errors."""

import argparse
from collections import Counter
from dataclasses import dataclass
import os
import re
import socket
import subprocess
import sys
from urllib.parse import urlsplit


@dataclass
class Result:
    status: str
    check: str
    evidence: str


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse normally echoes invalid argument values, which may be private.
        self.exit(2, "UNVERIFIED\targuments\tinvalid-options-see-help\n")


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


def service_checks(service, timeout, expected_enabled="disabled"):
    results = []
    for name, expected, valid_codes in (("active", "active", (0,)),
                                        ("enabled", expected_enabled, (0, 1))):
        check = "service-" + name
        proc = run_command(["systemctl", "--user", "is-" + name, service], timeout)
        if proc is None or proc.returncode not in (0, 1, 3, 4):
            results.append(Result("UNVERIFIED", check, "systemctl-error"))
        elif proc.stdout.strip() == expected and proc.returncode in valid_codes:
            results.append(Result("PASS", check, expected))
        else:
            results.append(Result("FAIL", check, "unexpected-service-state"))
    return results


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


def curl_check(kind, url, port, timeout, expected, proxy_url=None):
    env = clean_environment()
    args = ["curl", "--disable", "--head", "--globoff", "--proto", "=https",
            "--silent", "--show-error", "--noproxy", "",
            "--max-time", str(timeout), "--output", os.devnull,
            "--write-out", "%{http_code}\t%{http_connect}\t%{remote_ip}\t%{remote_port}"]
    # No redirects: every status belongs to the exact requested public target.
    if kind == "http-auth":
        env["https_proxy"] = proxy_url
    elif kind == "socks5h-auth":
        env["all_proxy"] = proxy_url
    args.append(url)
    proc = run_command(args, timeout + 2, env)
    if proc is None:
        return Result("UNVERIFIED", kind, "curl-unavailable-or-timed-out")
    fields = proc.stdout.strip().split("\t")
    if (len(fields) != 4 or not re.fullmatch(r"\d{3}", fields[0])
            or not re.fullmatch(r"\d{3}", fields[1]) or not fields[3].isdigit()):
        return Result("UNVERIFIED", kind, "curl_rc={};invalid-curl-metrics".format(proc.returncode))
    status, connect = int(fields[0]), int(fields[1])
    peer_ok = fields[2] == "127.0.0.1" and int(fields[3]) == port
    evidence = "curl_rc={};http={};connect={};peer={}".format(
        proc.returncode, status, connect, "listener" if peer_ok else "unexpected")
    status_ok = status == expected if expected is not None else 200 <= status < 300
    passed = proc.returncode == 0 and status_ok and peer_ok
    if kind == "http-auth":
        passed = passed and connect == 200
    return Result("PASS" if passed else "FAIL", kind, evidence)


def http_no_auth(url, port, timeout):
    # Curl may discard peer metrics on a failed CONNECT (407). Inspect a direct
    # socket to the selected loopback listener instead of inferring from curl rc.
    try:
        target = urlsplit(url)
        host = target.hostname.encode("idna").decode("ascii")
        if ":" in host:
            host = "[" + host + "]"
        authority = host + ":" + str(target.port or 443)
        request = ("CONNECT " + authority + " HTTP/1.1\r\nHost: " + authority
                   + "\r\n\r\n").encode("ascii")
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(request)
            with conn.makefile("rb") as response:
                line = response.readline(4096)
    except (OSError, ValueError, UnicodeError):
        return Result("UNVERIFIED", "http-no-auth", "no-connect-response-evidence")
    match = re.fullmatch(rb"HTTP/1\.[01] ([0-9]{3})(?: [^\r\n]*)?\r\n", line)
    if match is None:
        return Result("UNVERIFIED", "http-no-auth", "invalid-connect-response")
    code = int(match[1])
    evidence = "connect={};peer=listener".format(code)
    if code == 407:
        return Result("PASS", "http-no-auth", evidence)
    if code == 200:
        return Result("FAIL", "http-no-auth", evidence + ";authentication-bypass")
    return Result("UNVERIFIED", "http-no-auth", evidence + ";no-auth-rejection-evidence")


def socks_no_auth(port, timeout):
    # RFC 1928: offer ONLY method 00 (no authentication). FF must reject it.
    # No CONNECT request, DNS lookup, credentials, or outbound target is needed.
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as conn:
            conn.sendall(b"\x05\x01\x00")
            response = b""
            while len(response) < 2:
                chunk = conn.recv(2 - len(response))
                if not chunk:
                    break
                response += chunk
    except OSError:
        return Result("UNVERIFIED", "socks5h-no-auth", "no-handshake-evidence")
    if response == b"\x05\xff":
        return Result("PASS", "socks5h-no-auth", "method-ff-no-acceptable-auth-method")
    if response == b"\x05\x00":
        return Result("FAIL", "socks5h-no-auth", "method-00-authentication-bypass")
    return Result("UNVERIFIED", "socks5h-no-auth", "unexpected-or-incomplete-handshake")


def pending_checks(defer_vscode):
    return [
        Result("UNVERIFIED", "proxy-route", "need-target-rule-and-node-evidence"),
        Result("UNVERIFIED", "installed-shell", "need-fresh-shell-and-hook-evidence"),
        Result("UNVERIFIED", "downloads", "need-each-client-socket-evidence"),
        Result("UNVERIFIED", "lifecycle", "need-approved-stop-release-and-restart-evidence"),
        Result("UNVERIFIED", "sensitive-data", "need-scoped-local-scan-evidence"),
        Result("UNVERIFIED", "baseline", "need-before-after-own-scope-comparison"),
        Result("DEFERRED" if defer_vscode else "UNVERIFIED", "vscode-remote",
               "explicitly-deferred" if defer_vscode else "optional-scope-not-assessed"),
    ]


def report(results):
    for result in results:
        print("{}\t{}\t{}".format(result.status, result.check, result.evidence))
    counts = Counter(result.status for result in results)
    overall = ("FAIL" if counts["FAIL"] else "UNVERIFIED"
               if counts["UNVERIFIED"] or counts["DEFERRED"] else "PASS")
    print("{}\toverall\tpass={};fail={};unverified={};deferred={}".format(
        overall, counts["PASS"], counts["FAIL"], counts["UNVERIFIED"], counts["DEFERRED"]))
    return 1 if overall == "FAIL" else 2 if overall == "UNVERIFIED" else 0


def main(argv=None):
    parser = Parser(description="Run via bash scripts/acceptance.sh; never changes service state.")
    parser.add_argument("--url", help="Public HTTPS URL, without userinfo, query, or fragment; default: readiness URL")
    parser.add_argument("--expect-status", type=int, help="Exact expected 2xx status; default: any 2xx")
    parser.add_argument("--timeout", type=int, default=10, help="Timeout per probe in seconds (1-60)")
    parser.add_argument("--defer-vscode", action="store_true", help="Record VS Code verification as explicitly deferred")
    parser.add_argument("--expect-enabled", default="disabled",
                        choices=("disabled", "enabled", "enabled-runtime", "static", "indirect", "masked", "masked-runtime"),
                        help="Expected existing enablement state; never changes it")
    args = parser.parse_args(argv)
    try:
        port = int(os.environ["MIHOMO_PORT"])
        service = os.environ["MIHOMO_SERVICE"]
        url = args.url or os.environ["MIHOMO_READY_URL"]
        parsed = urlsplit(url)
        target_port = parsed.port if parsed.port is not None else 443
        if (not 1 <= target_port <= 65535 or not 1024 <= port <= 65535
                or not re.fullmatch(r"[A-Za-z0-9_.@-]+", service)
                or not 1 <= args.timeout <= 60
                or (args.expect_status is not None and not 200 <= args.expect_status < 300)
                or parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or any(ord(char) < 33 or ord(char) == 127 for char in url)):
            raise ValueError
        # Validation is repeated here to make direct invocation fail safely too.
        for name, scheme in (("MIHOMO_HTTPS_PROXY", "http"), ("MIHOMO_ALL_PROXY", "socks5h")):
            proxy = urlsplit(os.environ[name])
            if (proxy.scheme != scheme or proxy.hostname != "127.0.0.1" or proxy.port != port
                    or not proxy.username or not proxy.password or proxy.query or proxy.fragment
                    or proxy.path not in ("", "/")):
                raise ValueError
    except (KeyError, ValueError):
        return report([Result("UNVERIFIED", "inputs", "invalid-options-or-validated-environment-missing")])
    results = service_checks(service, args.timeout, args.expect_enabled)
    results.append(listener_check(port, args.timeout))
    if any(result.status != "PASS" for result in results):
        results.extend(Result("UNVERIFIED", name, "service-or-binding-preflight-not-passed")
                       for name in ("http-auth", "socks5h-auth", "http-no-auth", "socks5h-no-auth"))
    else:
        results.extend([
            curl_check("http-auth", url, port, args.timeout, args.expect_status,
                       os.environ["MIHOMO_HTTPS_PROXY"]),
            curl_check("socks5h-auth", url, port, args.timeout, args.expect_status,
                       os.environ["MIHOMO_ALL_PROXY"]),
            http_no_auth(url, port, args.timeout),
            socks_no_auth(port, args.timeout),
        ])
    results.extend(pending_checks(args.defer_vscode))
    return report(results)


if __name__ == "__main__":
    sys.exit(main())
