"""Real-core process acceptance, with only local HTTP targets and private homes."""
import base64
import gzip
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import unquote, urlsplit

import yaml

CORE = os.environ.get("MIHOMO_TEST_CORE")
KEYS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
        "http_proxy", "https_proxy", "all_proxy", "no_proxy")


def unused_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@unittest.skipUnless(CORE and sys.platform == "linux", "real Mihomo core required")
class ProcessAcceptance(unittest.TestCase):
    def test_documented_private_rules_with_manager_core_and_json(self):
        root = Path(__file__).resolve().parents[1]
        tutorial = (root / 'docs/en/rules.md').read_text()
        shell = re.findall(r'```bash\n(.*?)```', tutorial, re.S)[0]
        subprocess.run(['bash', '-c', shell], env=self.env, check=True, capture_output=True)
        config = yaml.safe_load(self.core_path.read_text())
        rules = yaml.safe_load(re.findall(r'```yaml\n(.*?)```', tutorial, re.S)[0])
        rules['proxy-groups'][0]['proxies'] = ['fixture-node']
        config['proxies'] = [{'name': 'fixture-node', 'type': 'direct'}]
        config.update(rules)
        self.core_path.write_text(yaml.safe_dump(config, sort_keys=False))
        fake_bin = self.home / 'fake-bin'
        fake_bin.mkdir(mode=0o700)
        impostor = fake_bin / 'mihomo'
        impostor.write_text('#!/bin/sh\nexit 99\n')
        impostor.chmod(0o700)
        self.env['PATH'] = str(fake_bin) + ':' + self.env['PATH']
        home = self.home / 'data/mihomoctl/core-home'
        before = {p.relative_to(home).as_posix(): p.read_bytes() for p in home.rglob('*') if p.is_file()}
        result = self.cli('rules', 'check')
        self.assertEqual(result['overall'], 'PASS')
        self.assertEqual(result['data']['rules']['overall'], 'PASS')
        self.assertEqual(before, {p.relative_to(home).as_posix(): p.read_bytes() for p in home.rglob('*') if p.is_file()})

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="mihomoctl-real-user-")
        self.home = Path(self.folder.name)
        self.home.chmod(0o700)
        self.env = {"HOME": str(self.home), "PATH": os.environ["PATH"], "LANG": "C.UTF-8",
                    "XDG_CONFIG_HOME": str(self.home / "config"),
                    "XDG_DATA_HOME": str(self.home / "data"),
                    "XDG_STATE_HOME": str(self.home / "state"),
                    "XDG_CACHE_HOME": str(self.home / "cache")}
        self.manager_path = self.home / "config/mihomoctl/manager.yaml"
        self.shells = {name: b"# untouched startup file\n" for name in (".bashrc", ".zshrc", ".profile")}
        for name, value in self.shells.items():
            (self.home / name).write_bytes(value)
        self.port = unused_port()
        self.cli("init", "--core", CORE, "--port", self.port)
        self.manager = yaml.safe_load(self.manager_path.read_text())
        self.core_path = Path(self.manager["core"]["config"])
        class Target(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(204)
                self.end_headers()
            do_GET = do_HEAD
            def log_message(self, *args):
                pass
        self.target = ThreadingHTTPServer(("127.0.0.1", 0), Target)
        threading.Thread(target=self.target.serve_forever, daemon=True).start()

    def tearDown(self):
        try:
            # Best effort stop uses the normal ownership-checked lifecycle API.
            subprocess.run([sys.executable, "-m", "mihomoctl", "stop"], env=self.env,
                           capture_output=True, timeout=30)
        finally:
            if hasattr(self, "target"):
                self.target.shutdown()
                self.target.server_close()
            self.folder.cleanup()

    def cli(self, *args, expected=0):
        result = subprocess.run([sys.executable, "-m", "mihomoctl", *map(str, args), "--json"],
                                env=self.env, capture_output=True, text=True, timeout=60)
        try:
            value = json.loads(result.stdout)
        except ValueError:
            self.fail("CLI returned invalid JSON; command=" + str(args[0]))
        codes = [e.get("code", "unknown") for e in value.get("errors", []) if isinstance(e, dict)]
        self.assertEqual(result.returncode, expected,
                         "command=%s error-codes=%s" % (args[0], codes))
        self.assertEqual(value.get("schema"), "mihomoctl/v1")
        return value

    def export(self):
        path = self.home / "proxy.env"
        self.cli("env", "export", "--output", path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        result = {line.split("=", 1)[0]: shlex.split(line.split("=", 1)[1])[0]
                  for line in path.read_text().splitlines() if "=" in line and not line.startswith("#")}
        self.assertTrue(all(result.get(k) for k in KEYS), "missing environment key")
        return result

    def http_probe(self, endpoint, authenticated):
        headers = {}
        if authenticated:
            credential = unquote(endpoint.username or "") + ":" + unquote(endpoint.password or "")
            headers["Proxy-Authorization"] = "Basic " + base64.b64encode(credential.encode()).decode()
        connection = http.client.HTTPConnection(endpoint.hostname, endpoint.port, timeout=5)
        try:
            connection.request("HEAD", "http://127.0.0.1:%d/" % self.target.server_port, headers=headers)
            response = connection.getresponse()
            status = response.status
            response.read()
            return status
        finally:
            connection.close()

    def socks_probe(self, endpoint, authenticated):
        with socket.create_connection((endpoint.hostname, endpoint.port), timeout=5) as connection:
            connection.sendall(b"\x05\x01" + (b"\x02" if authenticated else b"\x00"))
            selected = connection.recv(2)
            if not authenticated:
                self.assertIn(selected, (b"\x05\xff", b"\x05\x02"),
                              "anonymous SOCKS unexpectedly accepted")
                if selected == b"\x05\x02":
                    # Mihomo requests credentials even when only no-auth was
                    # offered. A client cannot skip that authentication step.
                    connection.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01"
                                       + self.target.server_port.to_bytes(2, "big")
                                       + b"HEAD / HTTP/1.0\r\nHost: localhost\r\n\r\n")
                    rejected = connection.recv(1024)
                    self.assertNotEqual(rejected[:2], b"\x05\x00",
                                        "SOCKS CONNECT bypassed authentication")
                    self.assertNotIn(b"204", rejected, "anonymous request reached target")
                return
            self.assertEqual(selected, b"\x05\x02", "SOCKS authentication not negotiated")
            username, password = unquote(endpoint.username).encode(), unquote(endpoint.password).encode()
            connection.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
            self.assertEqual(connection.recv(2), b"\x01\x00", "SOCKS credentials rejected")
            connection.sendall(b"\x05\x01\x00\x01\x7f\x00\x00\x01" + self.target.server_port.to_bytes(2, "big"))
            reply = connection.recv(10)
            self.assertEqual(reply[:2], b"\x05\x00", "SOCKS local CONNECT failed")
            connection.sendall(b"HEAD / HTTP/1.0\r\nHost: localhost\r\n\r\n")
            self.assertTrue(b"204" in connection.recv(1024).split(b"\r\n")[0], "SOCKS target did not respond")

    def write_yaml(self, path, value):
        path.write_text(yaml.safe_dump(value, sort_keys=False))
        path.chmod(0o600)

    def test_authenticated_mixed_lifecycle_and_empty_environment_exec(self):
        self.env.update(CLASH_OVERRIDE_SECRET="UNTRUSTED_INHERITED_OVERRIDE",
                        CLASH_OVERRIDE_EXTERNAL_CONTROLLER="127.0.0.1:" + str(unused_port()))
        self.cli("config", "validate")
        self.cli("start")
        self.cli("status")
        environment = self.export()
        http = urlsplit(environment["HTTP_PROXY"])
        socks = urlsplit(environment["ALL_PROXY"])
        self.assertEqual(http.port, self.port)
        self.assertEqual(socks.port, self.port)
        self.assertEqual(self.http_probe(http, False), 407)
        self.assertEqual(self.http_probe(http, True), 204)
        self.socks_probe(socks, False)
        self.socks_probe(socks, True)
        shown = self.cli("env", "show")
        self.assertNotIn(unquote(http.password), json.dumps(shown), "status exposed credentials")
        target = self.home / "inherited.json"
        worker = "import json,os,pathlib;pathlib.Path(%r).write_text(json.dumps({k:os.environ.get(k) for k in %r}));raise SystemExit(19)" % (str(target), KEYS)
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "exec", "--", sys.executable, "-c", worker],
                                env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 19)
        inherited = json.loads(target.read_text())
        self.assertTrue(all(inherited[k] == environment[k] for k in KEYS), "empty-environment injection drifted")
        arguments = ["", "--json", "--system", "value with spaces", "--", "尾部"]
        argv_dump = self.home / "arguments.json"
        child = "import json,pathlib,sys;pathlib.Path(%r).write_text(json.dumps(sys.argv[1:]))" % str(argv_dump)
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "exec", "--",
                                 sys.executable, "-c", child, *arguments],
                                env=self.env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, "child flags were interpreted as manager flags")
        self.assertEqual(json.loads(argv_dump.read_text()), arguments, "child argv was changed")
        direct_env = dict(self.env, **environment)
        child = "import os;raise SystemExit(1 if any(k in os.environ for k in %r) else 0)" % (KEYS,)
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "direct", "--", sys.executable, "-c", child],
                                env=direct_env, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0)
        self.cli("restart")
        self.cli("stop")
        self.cli("status", expected=1)
        forbidden = self.home / "must-not-run"
        child = "import pathlib;pathlib.Path(%r).touch()" % str(forbidden)
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "exec", "--",
                                 sys.executable, "-c", child], env=self.env,
                                capture_output=True, timeout=30)
        self.assertNotEqual(result.returncode, 0, "exec accepted a stopped proxy runtime")
        self.assertFalse(forbidden.exists(), "health gate launched the child after failure")
        for name, value in self.shells.items():
            self.assertTrue((self.home / name).read_bytes() == value, "shell startup file changed")

    def test_separate_named_listeners_and_disabled_legacy_port(self):
        config = yaml.safe_load(self.core_path.read_text())
        credentials = yaml.safe_load(Path(self.manager["profiles"]["default"]["credentials_file"]).read_text())
        second = unused_port()
        config["mixed-port"] = 0
        config["listeners"] = [
            {"name": "web", "type": "http", "listen": "127.0.0.1", "port": self.port, "users": [dict(credentials)]},
            {"name": "socks", "type": "socks", "listen": "127.0.0.1", "port": second, "users": [dict(credentials)]},
        ]
        self.manager["profiles"]["default"].update(http_listener="web", socks_listener="socks")
        self.write_yaml(self.core_path, config)
        self.write_yaml(self.manager_path, self.manager)
        self.cli("config", "validate")
        self.cli("start")
        environment = self.export()
        http, socks = urlsplit(environment["HTTP_PROXY"]), urlsplit(environment["ALL_PROXY"])
        self.assertEqual(http.port, self.port)
        self.assertEqual(socks.port, second)
        self.assertEqual(self.http_probe(http, False), 407)
        self.assertEqual(self.http_probe(http, True), 204)
        self.socks_probe(socks, False)
        self.socks_probe(socks, True)

    def test_port_conflict_does_not_kill_or_claim_foreign_listener(self):
        with socket.socket() as foreign:
            foreign.bind(("127.0.0.1", self.port))
            foreign.listen()
            self.cli("start", expected=1)
            self.assertEqual(foreign.getsockname()[1], self.port)
            self.assertNotEqual(self.cli("status", expected=1)["overall"], "PASS")

    def test_crash_is_reported_and_explicit_restart_recovers(self):
        self.cli("start")
        config_argument = str(self.core_path).encode()
        candidates = []
        for path in Path("/proc").iterdir():
            if path.name.isdigit():
                try:
                    if config_argument in (path / "cmdline").read_bytes().split(b"\0"):
                        candidates.append(int(path.name))
                except (OSError, PermissionError):
                    pass
        self.assertEqual(len(candidates), 1, "cannot identify exactly the isolated core")
        os.kill(candidates[0], signal.SIGKILL)
        import time
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = Path("/proc") / str(candidates[0]) / "stat"
            if not state.exists() or state.read_text().split(") ", 1)[1].startswith("Z"):
                break
            time.sleep(.05)
        self.cli("status", expected=1)
        self.cli("restart")
        self.cli("status")

    def test_invalid_yaml_and_forbidden_tun_fail_without_echoing_secret(self):
        self.cli("start")
        original_pid = self.cli("status")["data"]["runtime"]["pid"]
        original = self.core_path.read_bytes()
        marker = "FICTIONAL_VALUE_NOT_FOR_LOGS"
        self.core_path.write_text("secret: [" + marker + "\n")
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "config", "validate", "--json"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr)
        self.core_path.write_bytes(original)
        semantic = yaml.safe_load(original)
        semantic["proxies"] = [{"name": "invalid", "type": marker}]
        self.write_yaml(self.core_path, semantic)
        result = subprocess.run([sys.executable, "-m", "mihomoctl", "config", "validate", "--json"],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(marker, result.stdout + result.stderr, "core validation output exposed candidate data")
        try:
            self.cli("restart", expected=2)
            self.assertTrue(Path("/proc", str(original_pid)).exists(), "invalid restart stopped the old core")
        finally:
            self.core_path.write_bytes(original)
        self.assertEqual(self.cli("status")["data"]["runtime"]["pid"], original_pid,
                         "invalid restart replaced the running old core")
        self.cli("stop")
        config = yaml.safe_load(original)
        config["tun"] = {"enable": True, "auto-route": True}
        self.write_yaml(self.core_path, config)
        self.cli("start", expected=2)
        self.cli("tun", "enable", expected=2)

    def test_core_install_rolls_back_failed_activation_and_replaces_only_managed_binary(self):
        from mihomoctl import coreinstall
        from mihomoctl.errors import ObservedStateError
        from mihomoctl.lifecycle.process import ProcessBackend
        from mihomoctl.scope import Scope
        self.cli("start")
        original_manager = self.manager_path.read_bytes()
        original_config = self.core_path.read_bytes()
        external = Path(CORE).read_bytes()
        archive = gzip.compress(external, mtime=0)
        digest = hashlib.sha256(archive).hexdigest()
        original_start = ProcessBackend.start

        def fail_new_backend(backend, *args, **kwargs):
            if backend.manager.core.binary != CORE:
                raise ObservedStateError("injected-activation-failure")
            return original_start(backend, *args, **kwargs)

        with patch.dict(os.environ, self.env, clear=True), \
                patch.object(coreinstall, "_download", return_value=archive), \
                patch.object(coreinstall.digests, "lookup", return_value={"sha256": digest}):
            scope = Scope()
            with patch.object(ProcessBackend, "start", fail_new_backend):
                with self.assertRaises(ObservedStateError):
                    coreinstall.install(scope, "v1.19.32")
            self.assertTrue(self.manager_path.read_bytes() == original_manager,
                            "failed activation did not restore original binding")
            self.assertFalse((scope.cores_root / "v1.19.32/mihomo").exists(),
                             "failed activation left a published candidate")
            self.assertEqual(coreinstall._application(scope).status()["overall"], "PASS",
                             "failed update did not restore the running old core")
            # Receipt durability can fail after activation; recover the old runtime too.
            with patch("mihomoctl.transaction.Transaction.commit", side_effect=OSError("injected-journal-failure")):
                with self.assertRaises(OSError):
                    coreinstall.install(scope, "v1.19.32")
            self.assertTrue(self.manager_path.read_bytes() == original_manager,
                            "failed commit did not restore original binding")
            self.assertFalse((scope.cores_root / "v1.19.32/mihomo").exists(),
                             "failed commit left a published candidate")
            self.assertEqual(coreinstall._application(scope).status()["overall"], "PASS",
                             "failed commit did not restore the running old core")
            installed = coreinstall.install(scope, "v1.19.32")
            self.assertTrue(installed["activated"])
            self.assertNotEqual(installed["binary"], CORE)
            self.assertEqual(coreinstall._application(scope).status()["overall"], "PASS")
        self.assertTrue(self.core_path.read_bytes() == original_config, "core update changed proxy policy")
        self.assertTrue(Path(CORE).read_bytes() == external, "core installer replaced an adopted external binary")


if __name__ == "__main__":
    unittest.main()
