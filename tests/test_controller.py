"""Real loopback HTTP contract and private configuration mutation tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import stat
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
import zipfile
import hashlib
import importlib.util
import select
import time

if sys.platform != "linux":
    raise unittest.SkipTest("Linux ownership and controller integration")
import pty
import fcntl
import struct
import termios
from scripts import controller as c
from scripts.controller_service import ConsoleService

TOKEN = "fixture-" + "a" * 40
ROWS = {"Proxy / 中文": {"type": "Selector", "now": "Node A", "all": ["Node A", "Node B"]},
        "Auto": {"type": "URLTest", "now": "Node A", "all": ["Node A"]},
        "Node A": {"type": "SS", "password": "DO-NOT-PRINT"}, "Node B": {"type": "SS"}}


class Server(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        self.server.paths.append(self.path)
        if not self.server.anonymous and self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401); self.end_headers(); return
        if self.path == "/version":
            data = {"version": "fixture"}
        elif self.path == "/proxies":
            data = {"proxies": self.server.rows}
        elif self.path == "/connections":
            data = {"connections": [{"metadata": {"host": "PRIVATE-HOST"}, "chains": ["Node B", "Proxy"], "rule": "Match"}]}
        elif self.path == "/traffic":
            data = {"up": 10, "down": 20}
        elif self.path == "/memory":
            data = {"inuse": 4096, "oslimit": 0, "private": "DO-NOT-PRINT"}
        elif self.path == "/rules":
            data = {"rules": [{"type": "Domain", "payload": "PRIVATE-HOST"}, {"type": "Match"}]}
        elif self.path == "/providers/proxies":
            data = {"providers": {"provider / fixture": {"vehicleType": "HTTP", "updatedAt": "now", "proxies": [{"password": "DO-NOT-PRINT"}], "url": "PRIVATE-URL"}}}
        elif self.path == "/providers/rules":
            data = {"providers": {"rules fixture": {"vehicleType": "Inline", "behavior": "Domain", "ruleCount": 7, "updatedAt": "now", "payload": ["PRIVATE-HOST"], "url": "PRIVATE-URL"}}}
        elif self.path == "/configs":
            data = {"mode": getattr(self.server, "mode", "rule"), "secret": TOKEN}
        elif self.path.startswith("/dns/query?"):
            data = {"Answer": [{"name": "example.com", "type": 1, "TTL": 60, "data": "192.0.2.1"}]}
        elif self.path.startswith("/logs?"):
            self.send_response(200); self.end_headers()
            for message in ("private host PRIVATE-HOST", TOKEN + " PRIVATE-LOG-CREDENTIAL", "https://user:pass@example.com/?token=private-value\x1b[31m"):
                self.wfile.write(json.dumps({"type": "info", "payload": message}).encode() + b"\n")
            return
        elif self.path == "/unsupported":
            self.send_response(404); self.end_headers(); return
        elif "/delay?" in self.path:
            data = {"delay": 32}
        else:
            self.send_response(302); self.send_header("Location", "http://example.com/"); self.end_headers(); return
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps(data).encode() + b"\n")

    def do_PUT(self):
        self.server.puts += 1
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401); self.end_headers(); return
        if self.path.startswith("/providers/proxies/"):
            self.send_response(204); self.end_headers(); return
        value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.rows["Proxy / 中文"]["now"] = value["name"]
        self.send_response(204); self.end_headers()

    def do_PATCH(self):
        if self.headers.get("Authorization") != "Bearer " + TOKEN:
            self.send_response(401); self.end_headers(); return
        self.server.patch = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.server.mode = self.server.patch["mode"]
        self.send_response(204); self.end_headers()


class ControllerTests(unittest.TestCase):
    def service(self, root, details=False):
        config = Path(root) / "config.yaml"
        config.write_text('external-controller: 127.0.0.1:' + str(self.server.server_port) + '\nsecret: ' + TOKEN + '\nproxies: [{name: test, type: ss, password: PRIVATE-LOG-CREDENTIAL}]\n')
        config.chmod(0o600)
        return ConsoleService(config, details=details)

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "optional Controller YAML dependency")
    def test_new_services_whitelist_and_mode_only_patch(self):
        with tempfile.TemporaryDirectory() as root:
            service = self.service(root)
            result = [service.read(page) for page in ("rules", "providers", "memory")]
            value = json.dumps(result)
            self.assertEqual(result[0]["providers"][0]["rules"], 7)
            for private in (TOKEN, "PRIVATE-HOST", "PRIVATE-URL", "DO-NOT-PRINT"):
                self.assertNotIn(private, value)
            self.assertEqual(service.mode("direct")["shell"], "unchanged")
            self.assertEqual(self.server.patch, {"mode": "direct"})
            self.assertEqual(service.dns("example.com")["answers"][0]["data"], "192.0.2.1")
            self.assertEqual(service.provider_refresh("provider / fixture")["state"], "refresh-requested")

    def test_capability_404_is_distinct_from_redirect_and_authentication(self):
        with self.assertRaisesRegex(c.ControlError, "capability-unsupported"):
            self.client.request("/unsupported", optional=True)
        with self.assertRaisesRegex(c.ControlError, "request-failed"):
            self.client.request("/redirect", optional=True)
        with self.assertRaisesRegex(c.ControlError, "authentication-failed"):
            c.Client(self.server.server_port, "wrong").request("/unsupported", optional=True)

    def test_plain_menu_selector_switch_and_automatic_group_remains_read_only(self):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys.stdin, "isatty", return_value=True), patch.object(sys.stdout, "isatty", return_value=True), patch("builtins.input", side_effect=["2", "1", "2", "q"]):
            result = c.plain_tui(self.client)
        self.assertEqual(result["state"], "closed")
        self.assertEqual(self.server.puts, 1)
        self.assertEqual(self.server.rows["Proxy / 中文"]["now"], "Node B")

    def test_conflicting_engines_rejected_before_configuration_or_network(self):
        with self.assertRaisesRegex(c.ControlError, "conflicting-tui-engines"):
            c.main(["tui", "--plain", "--engine", "textual"])

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "optional Controller YAML dependency")
    def test_log_stream_private_projection_and_detail_credential_redaction(self):
        for details in (False, True):
            with self.subTest(details=details), tempfile.TemporaryDirectory() as root:
                service = self.service(root, details)
                stop, rows = threading.Event(), []
                def emit(value=None, error=""):
                    self.assertFalse(error)
                    if value:
                        rows.append(value)
                    if len(rows) >= 4:
                        stop.set()
                service.logs(emit, stop)
                output = json.dumps(rows)
                for credential in (TOKEN, "PRIVATE-LOG-CREDENTIAL", "user:pass", "private-value", "\\u001b"):
                    self.assertNotIn(credential, output)
                if not details:
                    self.assertNotIn("PRIVATE-HOST", output)

    def setUp(self):
        # The updater's own fixture PATH contains a fake ss for its proxy tests.
        # This suite measures a real disposable loopback server instead.
        self.environment = patch.dict(os.environ, {"PATH": "/usr/bin:/bin"})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Server)
        self.server.rows = json.loads(json.dumps(ROWS))
        self.server.paths, self.server.puts, self.server.anonymous = [], 0, False
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = c.Client(self.server.server_port, TOKEN)

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def test_authenticated_loopback_ignores_proxy_environment(self):
        with patch.dict(os.environ, {"http_proxy": "http://127.0.0.1:1", "HTTP_PROXY": "http://127.0.0.1:1"}):
            self.client.verify()
            self.assertEqual(c.snapshot(self.client, "groups")["groups"][0]["selected"], "Node A")

    def test_select_unicode_and_verify(self):
        result = c.select(self.client, "Proxy / 中文", "Node B")
        self.assertEqual(result["selected"], "Node B")
        self.assertEqual(self.server.puts, 1)

    def test_invalid_selection_never_mutates(self):
        for group, node in (("Auto", "Node A"), ("Proxy / 中文", "unknown"), ("missing", "Node A")):
            with self.assertRaises(c.ControlError):
                c.select(self.client, group, node)
        self.assertEqual(self.server.puts, 0)

    def test_anonymous_bypass_blocks_before_authenticated_request(self):
        self.server.anonymous = True
        with self.assertRaisesRegex(c.ControlError, "authentication-not-enforced"):
            self.client.verify()
        self.assertEqual(self.server.paths, ["/version"])

    def test_wildcard_listener_blocks(self):
        with patch.object(c.acceptance, "listener_check", return_value=c.acceptance.Result("FAIL", "binding", "non-loopback")):
            with self.assertRaises(c.ControlError): self.client.verify()
        self.assertEqual(self.server.paths, [])

    def test_redirect_is_not_followed_and_wrong_secret_fails(self):
        with self.assertRaises(c.ControlError): self.client.request("/redirect")
        with self.assertRaises(c.ControlError): c.Client(self.server.server_port, "wrong").request("/version")

    def test_output_whitelist(self):
        value = json.dumps([c.snapshot(self.client, name) for name in ("nodes", "connections", "traffic")])
        for secret in (TOKEN, "PRIVATE-HOST", "DO-NOT-PRINT", "metadata", "password"):
            self.assertNotIn(secret, value)
        self.assertIn("Node B", value)

    def test_control_characters_rejected(self):
        self.server.rows["bad\x1b[31m"] = {"type": "SS"}
        with self.assertRaises(c.ControlError): c.proxies(self.client)

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "optional controller PyYAML dependency")
    def test_real_mihomoctl_dispatch_json(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); lib = root / "lib"; lib.mkdir(mode=0o700)
            source = Path(c.__file__).resolve().parents[1]
            for name in ("controller.py", "acceptance.py", "reporting.py", "install_support.py", "dashboard.html") + tuple(n + ".py" for n in c._COMPONENTS):
                shutil.copyfile(source / "scripts" / name, lib / name)
                (lib / name).chmod(0o644)
            shutil.copyfile(source / "src/common.bash", lib / "common.bash")
            (lib / "common.bash").chmod(0o644)
            config = root / "config.yaml"
            config.write_text('external-controller: 127.0.0.1:'+str(self.server.server_port)+'\nsecret: '+TOKEN+'\n')
            config.chmod(0o600)
            result = subprocess.run(["bash", str(source / "src/mihomoctl"), "groups", "--json", "--config", str(config)],
                                    env=dict(os.environ, MIHOMO_USERCTL_LIB_DIR=str(lib)), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)["groups"][0]["selected"], "Node A")
            self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_foreign_uid_rejected_before_token(self):
        with patch.object(c.os, "getuid", return_value=os.getuid()+1):
            with self.assertRaisesRegex(c.ControlError, "not-owned"):
                self.client.verify()
        self.assertEqual(self.server.paths, [])

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "optional controller PyYAML dependency")
    def test_fullscreen_tui_runs_in_real_pty_and_quits_cleanly(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / "config.yaml"
            config.write_text('external-controller: 127.0.0.1:'+str(self.server.server_port)+'\nsecret: '+TOKEN+'\n')
            config.chmod(0o600)
            master, slave = pty.openpty()
            fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 100, 0, 0))
            original_terminal = termios.tcgetattr(slave)
            process = subprocess.Popen([sys.executable, str(Path(c.__file__)), "tui", "--engine", "curses", "--config", str(config)],
                                       stdin=slave, stdout=slave, stderr=slave, env=dict(os.environ, TERM="xterm-256color"))
            os.close(slave)
            data = b""
            try:
                deadline = time.monotonic()+8
                while time.monotonic() < deadline:
                    if select.select([master], [], [], .1)[0]:
                        data += os.read(master, 65536)
                        # Wait for the complete first frame before injecting keys.
                        if b'q quit' in data:
                            break
                # Enter the current group, move down to Node B, confirm.
                os.write(master, b'\n\x1bOB\n')
                deadline = time.monotonic()+5
                while time.monotonic() < deadline and self.server.puts == 0:
                    if select.select([master], [], [], .1)[0]:
                        data += os.read(master, 65536)
                self.assertEqual(self.server.rows["Proxy / 中文"]["now"], "Node B")
                os.write(master, b'q')
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertEqual(termios.tcgetattr(master), original_terminal)
                self.assertIn(b'MIHOMO', data)
                self.assertNotIn(TOKEN.encode(), data)
            finally:
                if process.poll() is None:
                    process.terminate(); process.wait(timeout=5)
                os.close(master)

    @unittest.skipUnless(importlib.util.find_spec("textual"), "optional Textual PTY integration")
    def test_textual_real_pty_quit_ctrl_c_and_terminal_restore(self):
        for key in (b"q", b"\x03"):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as folder:
                config = Path(folder) / "config.yaml"
                config.write_text('external-controller: 127.0.0.1:' + str(self.server.server_port) + '\nsecret: ' + TOKEN + '\n')
                config.chmod(0o600)
                master, slave = pty.openpty()
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
                original = termios.tcgetattr(slave)
                process = subprocess.Popen([sys.executable, c.__file__, "tui", "--engine", "textual", "--config", str(config)],
                                           stdin=slave, stdout=slave, stderr=slave, env=dict(os.environ, TERM="xterm-256color"))
                os.close(slave)
                output = b""
                try:
                    deadline = time.monotonic() + 10
                    while time.monotonic() < deadline and "当前用户的代理服务".encode() not in output:
                        if select.select([master], [], [], .1)[0]:
                            output += os.read(master, 65536)
                    self.assertIn("当前用户的代理服务".encode(), output)
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", 14, 60, 0, 0))
                    os.write(master, key)
                    self.assertEqual(process.wait(timeout=5), 0)
                    self.assertEqual(termios.tcgetattr(master), original)
                    self.assertNotIn(TOKEN.encode(), output)
                finally:
                    if process.poll() is None:
                        process.terminate(); process.wait(timeout=5)
                    os.close(master)


@unittest.skipUnless(importlib.util.find_spec("yaml"), "optional controller PyYAML dependency")
class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.home = self.root / "core"; self.home.mkdir(mode=0o700)
        self.config = self.root / "config.yaml"
        self.original = '# retain comment\nmixed-port: 25000\nproxies: []\nprofile:\n  store-fake-ip: false\n'
        self.config.write_text(self.original); self.config.chmod(0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def args(self):
        return c.argparse.Namespace(home_dir=str(self.home), port=None, archive=None, sha256=None)

    def test_setup_backup_and_preservation_no_service_restart(self):
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/mihomo"}), patch.object(c.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
            result = c.setup(self.args(), self.config)
        self.assertEqual(run.call_args.args[0][1], "-t")
        self.assertEqual(Path(result["backup"]).read_text(), self.original)
        self.assertEqual(result["state"], "restart-required")
        text, data, _ = c.read_config(self.config)
        self.assertIn("# retain comment", text)
        self.assertFalse(data["profile"]["store-fake-ip"])
        self.assertTrue(data["profile"]["store-selected"])
        self.assertGreaterEqual(len(c.endpoint(data)[1]), 32)
        self.assertEqual(stat.S_IMODE(self.config.stat().st_mode), 0o600)
        self.assertTrue((Path(data["external-ui"]) / "index.html").is_file())

    def test_validation_failure_leaves_config_unchanged_and_no_assets(self):
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/mihomo"}), patch.object(c.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaises(c.ControlError): c.setup(self.args(), self.config)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.home.iterdir()), [])

    def test_private_modes_symlink_duplicates_and_aliases(self):
        self.config.chmod(0o644)
        with self.assertRaises(c.ControlError): c.read_config(self.config)
        self.config.chmod(0o600)
        for content in ('secret: a\nsecret: b\n', 'x: &x {}\ny: *x\n'):
            self.config.write_text(content)
            with self.assertRaises(c.ControlError): c.read_config(self.config)
        link = self.root / "link"; link.symlink_to(self.config)
        with self.assertRaises(c.files.InstallError): c.read_config(link)

    def test_endpoint_rejects_public_weak_and_extra_listener(self):
        for data in ({"external-controller": "0.0.0.0:9000", "secret": TOKEN},
                     {"external-controller": "127.0.0.1:9000", "secret": "short"},
                     {"external-controller": "127.0.0.1:9000", "secret": TOKEN, "external-controller-unix": "x"}):
            with self.assertRaises(c.ControlError): c.endpoint(data)

    def test_archive_checksum_and_traversal(self):
        archive = self.root / "ui.zip"
        for bad in (False, True):
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("dist/index.html", "ok")
                if bad: z.writestr("../escape", "bad")
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            out = self.root / ("bad" if bad else "good"); out.mkdir()
            if bad:
                with self.assertRaises(c.ControlError): c.archive_ui(archive, digest, out)
            else:
                c.archive_ui(archive, digest, out)
                self.assertEqual((out / "index.html").read_text(), "ok")
            with self.assertRaises(c.ControlError): c.archive_ui(archive, "0" * 64, out)

    def test_cli_json_and_token_never_piped(self):
        self.config.write_text('external-controller: 127.0.0.1:29998\nsecret: '+TOKEN+'\n')
        result = subprocess.run([sys.executable, str(Path(c.__file__)), "controller", "token", "--config", str(self.config)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(TOKEN, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["overall"], "UNVERIFIED")

    def test_noninteractive_tui_refuses(self):
        with patch.object(sys.stdin, "isatty", return_value=False):
            with self.assertRaises(c.ControlError): c.tui(None)


if __name__ == "__main__":
    unittest.main()
