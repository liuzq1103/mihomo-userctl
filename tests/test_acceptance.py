"""Isolated verifier regressions: no real service, credentials, or public network."""
import contextlib
import io
import json
import os
import socket
import subprocess
import threading
import unittest
from unittest.mock import patch

from scripts import acceptance as a


PORT = 28443
URL = "https://example.com/"
SECRET = "fixture-private-" + "x" * 32
HTTP_PROXY = "http://user:" + SECRET + "@127.0.0.1:" + str(PORT)
SOCKS_PROXY = HTTP_PROXY.replace("http://", "socks5h://")


def completed(stdout, rc=0, stderr=""):
    return subprocess.CompletedProcess([], rc, stdout, stderr)


@contextlib.contextmanager
def peer(response, fragment=False):
    """One loopback connection only; the kernel chooses an unused port."""
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(3)
        errors = []

        def serve():
            try:
                with server.accept()[0] as conn:
                    conn.settimeout(3)
                    conn.recv(8192)
                    if fragment:
                        for byte in response:
                            conn.sendall(bytes([byte]))
                    else:
                        conn.sendall(response)
            except OSError as exc:
                errors.append(type(exc).__name__)

        worker = threading.Thread(target=serve, daemon=True)
        worker.start()
        try:
            yield server.getsockname()[1]
        finally:
            worker.join(4)
            if worker.is_alive() or errors:
                raise AssertionError("local fixture did not finish: " + str(errors))


class AcceptanceTests(unittest.TestCase):
    def curl(self, kind, output, rc=0, expected=204):
        with patch.object(a, "run_command", return_value=completed(output, rc, SECRET)):
            return a.curl_check(kind, URL, PORT, 2, expected, HTTP_PROXY)

    def test_status_is_measured_not_hardcoded(self):
        result = self.curl("http-auth", "200\t200\t127.0.0.1\t28443")
        self.assertEqual(result.status, "FAIL")
        self.assertIn("http=200", result.evidence)
        self.assertEqual(self.curl("http-auth", "204\t200\t127.0.0.1\t28443").status, "PASS")

    def test_wrong_peer_redirect_and_curl_failure_are_not_success(self):
        for text, rc in (("204\t200\t192.0.2.1\t443", 0),
                         ("302\t200\t127.0.0.1\t28443", 0),
                         ("204\t200\t127.0.0.1\t28443", 28)):
            self.assertEqual(self.curl("http-auth", text, rc).status, "FAIL")

    def test_http_407_is_required_not_any_failure(self):
        for response, expected in (
                (b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n", "PASS"),
                (b"HTTP/1.1 502 Bad Gateway\r\n\r\n", "UNVERIFIED"),
                (b"HTTP/1.1 200 Connection Established\r\n\r\n", "FAIL"),
                (b"unexpected response\r\n", "UNVERIFIED")):
            with peer(response) as port:
                self.assertEqual(a.http_no_auth(URL, port, 2).status, expected)
        with patch.object(a.socket, "create_connection", side_effect=TimeoutError):
            self.assertEqual(a.http_no_auth(URL, PORT, 2).status, "UNVERIFIED")

    def test_untrusted_metrics_and_errors_are_not_printed(self):
        result = self.curl("http-auth", SECRET, 2)
        self.assertEqual(result.status, "UNVERIFIED")
        self.assertNotIn(SECRET, str(result))

    def test_curl_ignores_curlrc_bypasses_and_keeps_secrets_out_of_argv(self):
        inherited = {"NO_PROXY": "*", "https_proxy": "old", "ALL_PROXY": "old",
                     "MIHOMO_HTTPS_PROXY": HTTP_PROXY}
        with patch.dict(os.environ, inherited), patch.object(a, "run_command", return_value=None) as run:
            for kind, env_key, value in (("http-auth", "https_proxy", HTTP_PROXY),
                                         ("socks5h-auth", "all_proxy", SOCKS_PROXY)):
                a.curl_check(kind, URL, PORT, 2, 204, value)
                args, _, env = run.call_args.args
                self.assertEqual(args[:2], ["curl", "--disable"])
                self.assertIn("--head", args)
                self.assertIn("--globoff", args)
                self.assertEqual(args[args.index("--noproxy") + 1], "")
                self.assertNotIn(SECRET, " ".join(args))
                self.assertEqual(env[env_key], value)
                self.assertNotIn("NO_PROXY", env)
                self.assertNotIn("ALL_PROXY", env)
                self.assertNotIn("MIHOMO_HTTPS_PROXY", env)
                if kind == "socks5h-auth":
                    self.assertNotIn("https_proxy", env)

    def test_disabled_exit_one_is_valid_but_tool_error_is_not(self):
        with patch.object(a, "run_command", side_effect=[completed("active"), completed("disabled", 1)]):
            self.assertTrue(all(r.status == "PASS" for r in a.service_checks("mihomo", 2)))
        with patch.object(a, "run_command", return_value=completed("disabled", 2)):
            self.assertTrue(all(r.status == "UNVERIFIED" for r in a.service_checks("mihomo", 2)))

    def test_wildcard_listener_cannot_hide_behind_good_listener(self):
        lines = "LISTEN 0 4096 127.0.0.1:28443 0.0.0.0:*\nLISTEN 0 4096 [::]:28443 [::]:*\n"
        with patch.object(a, "run_command", return_value=completed(lines)):
            self.assertEqual(a.listener_check(PORT, 2).status, "FAIL")
        with patch.object(a, "run_command", return_value=completed("", 1)):
            self.assertEqual(a.listener_check(PORT, 2).status, "UNVERIFIED")

    def test_socks_rejection_and_bypass_over_real_loopback(self):
        for response, expected in ((b"\x05\xff", "PASS"), (b"\x05\x00", "FAIL"),
                                    (b"\x05\x02", "UNVERIFIED"), (b"", "UNVERIFIED")):
            with peer(response, fragment=True) as port:
                self.assertEqual(a.socks_no_auth(port, 2).status, expected)

    def test_socks_connection_error_is_unverified(self):
        with patch.object(a.socket, "create_connection", side_effect=TimeoutError):
            self.assertEqual(a.socks_no_auth(PORT, 2).status, "UNVERIFIED")

    def test_pending_and_deferred_never_produce_all_pass(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(a.report([a.Result("PASS", "sample", "ok")] + a.pending_checks(True)), 2)
            self.assertEqual(a.report([a.Result("FAIL", "sample", "bad")] + a.pending_checks(False)), 1)
        self.assertIn("DEFERRED\tvscode-remote", output.getvalue())

    def test_invalid_private_url_is_not_echoed(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit):
            a.main(["--unknown=" + SECRET])
        self.assertNotIn(SECRET, stderr.getvalue())

    def test_private_target_url_is_rejected_without_network_or_disclosure(self):
        env = {"MIHOMO_SERVICE": "mihomo", "MIHOMO_PORT": str(PORT), "MIHOMO_READY_URL": URL,
               "MIHOMO_HTTPS_PROXY": HTTP_PROXY, "MIHOMO_ALL_PROXY": SOCKS_PROXY}
        output = io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(output), \
                patch.object(a, "service_checks") as service:
            self.assertEqual(a.main(["--url", URL + "?key=" + SECRET]), 2)
            service.assert_not_called()
        self.assertNotIn(SECRET, output.getvalue())

    def test_binding_failure_prevents_network_probes(self):
        env = {"MIHOMO_SERVICE": "mihomo", "MIHOMO_PORT": str(PORT), "MIHOMO_READY_URL": URL,
               "MIHOMO_HTTPS_PROXY": HTTP_PROXY, "MIHOMO_ALL_PROXY": SOCKS_PROXY}
        with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()), \
                patch.object(a, "service_checks", return_value=[a.Result("PASS", "service", "ok")]), \
                patch.object(a, "listener_check", return_value=a.Result("FAIL", "binding", "bad")), \
                patch.object(a, "curl_check") as curl:
            self.assertEqual(a.main([]), 1)
            curl.assert_not_called()

    def test_direct_check_clears_proxy_and_requires_non_listener_peer(self):
        with patch.object(a, "run_command", return_value=completed("204\t192.0.2.10\t443")) as run:
            result = a.direct_check(URL, 2, 204)
        self.assertEqual(result.status, "PASS")
        args, _, env = run.call_args.args
        self.assertEqual(args[args.index("--noproxy") + 1], "*")
        self.assertFalse(any(key.lower() in ("http_proxy", "https_proxy", "all_proxy", "no_proxy")
                             for key in env))

    def test_test_url_json_has_no_pending_claims_or_secrets(self):
        env = {"MIHOMO_SERVICE": "mihomo", "MIHOMO_PORT": str(PORT), "MIHOMO_READY_URL": URL,
               "MIHOMO_HTTPS_PROXY": HTTP_PROXY, "MIHOMO_ALL_PROXY": SOCKS_PROXY}
        passing = a.Result("PASS", "measured", "ok")
        output = io.StringIO()
        with patch.dict(os.environ, env), contextlib.redirect_stdout(output), \
                patch.object(a, "direct_check", return_value=passing), \
                patch.object(a, "service_active_check", return_value=passing), \
                patch.object(a, "listener_check", return_value=passing), \
                patch.object(a, "curl_check", return_value=passing), \
                patch.object(a, "http_no_auth", return_value=passing), \
                patch.object(a, "socks_no_auth", return_value=passing):
            self.assertEqual(a.main(["--profile", "test-url", "--url", URL, "--json"]), 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["overall"], "PASS")
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn("proxy-route", output.getvalue())

    def test_direct_failure_does_not_skip_independent_proxy_checks(self):
        env = {"MIHOMO_SERVICE": "mihomo", "MIHOMO_PORT": str(PORT), "MIHOMO_READY_URL": URL,
               "MIHOMO_HTTPS_PROXY": HTTP_PROXY, "MIHOMO_ALL_PROXY": SOCKS_PROXY}
        passing = a.Result("PASS", "measured", "ok")
        with patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()), \
                patch.object(a, "direct_check", return_value=a.Result("FAIL", "direct-target", "failed")), \
                patch.object(a, "service_active_check", return_value=passing), \
                patch.object(a, "listener_check", return_value=passing), \
                patch.object(a, "curl_check", return_value=passing) as curl, \
                patch.object(a, "http_no_auth", return_value=passing), \
                patch.object(a, "socks_no_auth", return_value=passing):
            self.assertEqual(a.main(["--profile", "test-url", "--url", URL]), 1)
        self.assertEqual(curl.call_count, 2)

    def test_test_url_rejects_local_hostnames(self):
        self.assertFalse(a.public_https_url("https://localhost/"))
        self.assertFalse(a.public_https_url("https://service.local/"))


if __name__ == "__main__":
    unittest.main()
