"""Launch policy and real CLI regression tests, isolated from live services."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import diagnostics as d
from scripts import acceptance as a
import test_diagnostics as fixtures
from test_diagnostics import expected, HTTP, SOCKS


ROOT = Path(__file__).resolve().parents[1]
CONFIG = {"MIHOMO_SERVICE": "mihomo", "MIHOMO_PORT": "28443",
          "MIHOMO_READY_URL": "https://example.com/", "MIHOMO_HTTP_PROXY": HTTP,
          "MIHOMO_HTTPS_PROXY": HTTP, "MIHOMO_ALL_PROXY": SOCKS}


@contextlib.contextmanager
def passing_proxy():
    with contextlib.ExitStack() as stack:
        for name in ("service_active_check", "listener_check", "http_no_auth", "socks_no_auth", "curl_check"):
            stack.enter_context(patch.object(a, name, return_value=a.Result("PASS", name, "fixture")))
        yield


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for context in (patch.dict(os.environ, CONFIG, clear=True),
                        patch.object(d.os, "getuid", return_value=1000, create=True),
                        patch.object(d.shutil, "which", return_value="/fixture/codex"), passing_proxy()):
            context.__enter__()
            self.addCleanup(context.__exit__, None, None, None)

    def fixture(self, **kwargs):
        return fixtures.DiagnosticTests.codex_fixture(self, self.root, **kwargs)

    def check(self, overall):
        state, payload, executable, env = d.codex_preflight(self.root)
        self.assertEqual(state, overall)
        self.assertEqual(payload["launch_safe"], state == "SAFE_TO_LAUNCH")
        self.assertEqual(payload["remote_transport"], "UNVERIFIED")
        self.assertEqual(payload["model_request"], "UNVERIFIED")
        self.assertEqual(payload["local_transport"], "DIRECT_EXPECTED")
        self.assertEqual(payload["levels"]["CODEX_E2E_VERIFIED"], "UNVERIFIED")
        self.assertNotIn("private-value", repr(payload))
        self.assertNotIn("secret-prompt-token", repr(payload))
        self.assertFalse(any(k.startswith("MIHOMO_") for k in env))
        self.assertTrue(all(env[k] == v for k, v in expected().items()))
        return payload

    def test_no_process_and_direct_parent_are_safe(self):
        data = self.check("SAFE_TO_LAUNCH")
        self.assertEqual(data["invoking_environment"]["classification"], "direct")
        self.assertEqual(data["codex"]["current_environment"], "PASS")

    def test_matching_app_server_is_safe_not_e2e(self):
        self.fixture(env=expected())
        self.check("SAFE_TO_LAUNCH")

    def test_direct_app_server_is_blocked(self):
        self.fixture()
        self.assertIn("stale-direct-app-server", self.check("BLOCKED")["reasons"])

    def test_inconsistent_server_and_cli_are_blocked(self):
        self.fixture(env={"HTTPS_PROXY": HTTP})
        self.fixture(pid=43, role=b"bridge")
        reasons = self.check("BLOCKED")["reasons"]
        self.assertIn("stale-inconsistent-app-server", reasons)
        self.assertIn("stale-direct-cli-or-helper", reasons)

    def test_unreadable_environment_is_not_safe(self):
        self.fixture().joinpath("environ").unlink()
        self.check("UNVERIFIED")

    def test_duplicate_proxy_environment_is_unverified(self):
        proc = self.fixture(env=expected())
        with (proc / "environ").open("ab") as stream:
            stream.write(b"\0HTTP_PROXY=different\0")
        self.check("UNVERIFIED")

    def test_unclassified_live_executable_is_incomplete(self):
        proc = self.fixture()
        (proc / "comm").write_text("worker\n")
        self.assertEqual(self.check("UNVERIFIED")["unverified_entries"], 1)

    def test_identified_non_candidate_does_not_need_environment_or_identity(self):
        proc = self.fixture()
        (proc / "comm").write_text("helper\n")
        (proc / "environ").unlink()
        (proc / "stat").unlink()
        with patch.object(d.os, "readlink", return_value="/usr/bin/python3"), \
                patch.object(d, "read_environment", side_effect=AssertionError("non-candidate read")):
            self.check("SAFE_TO_LAUNCH")

    def test_non_dumpable_helpers_use_corroborated_identity_not_environment(self):
        for pid, name in enumerate(("(sd-pam)", "fusermount3", "sshd"), 50):
            proc = self.fixture(pid=pid)
            (proc / "comm").write_text(name + "\n")
            (proc / "cmdline").write_bytes((name + (": user@pts/0" if name == "sshd" else "")).encode() + b"\0")
            (proc / "environ").unlink()
        with patch.object(d.os, "readlink", side_effect=PermissionError), \
                patch.object(d, "read_environment", side_effect=AssertionError("helper environ read")):
            self.check("SAFE_TO_LAUNCH")

    def test_helper_name_alone_does_not_suppress_unclassified_process(self):
        proc = self.fixture()
        (proc / "comm").write_text("sshd\n")
        with patch.object(d.os, "readlink", side_effect=PermissionError):
            self.assertEqual(self.check("UNVERIFIED")["unverified_entries"], 1)

    def test_zombie_non_candidate_does_not_block(self):
        proc = self.fixture()
        (proc / "comm").write_text("worker\n")
        p = proc / "stat"
        p.write_text(p.read_text().replace(") S ", ") Z "))
        self.check("SAFE_TO_LAUNCH")

    def test_node_wrapper_is_inspected(self):
        proc = self.fixture()
        (proc / "comm").write_text("node\n")
        (proc / "cmdline").write_bytes(b"node\0/pkg/codex.js\0app-server\0private-argument\0")
        with patch.object(d.os, "readlink", return_value="/usr/bin/node"):
            self.assertIn("stale-direct-app-server", self.check("BLOCKED")["reasons"])

    def test_foreign_uid_environment_and_arguments_never_read(self):
        self.fixture(uid=2000)
        with patch.object(d, "read_environment", side_effect=AssertionError("foreign read")):
            self.check("SAFE_TO_LAUNCH")

    def test_uid_change_before_private_read_is_unverified(self):
        self.fixture()
        with patch.object(d, "read_status", side_effect=[(1000, 1), (2000, 1)]), \
                patch.object(d, "read_environment", side_effect=AssertionError("foreign read")):
            self.check("UNVERIFIED")

    def test_missing_codex_blocks(self):
        with patch.object(d.shutil, "which", return_value=None):
            self.assertIn("codex-not-on-path", self.check("BLOCKED")["reasons"])

    def test_service_or_listener_failure_skips_network(self):
        for name in ("service_active_check", "listener_check"):
            with self.subTest(name=name), patch.object(a, name, return_value=a.Result("FAIL", name, "down")), \
                    patch.object(a, "curl_check") as curl, patch.object(a, "http_no_auth") as auth:
                self.check("BLOCKED")
                curl.assert_not_called()
                auth.assert_not_called()

    def test_tool_error_is_unverified_even_with_known_blocker(self):
        self.fixture()
        with patch.object(a, "listener_check", return_value=a.Result("UNVERIFIED", "listener", "ss-error")):
            self.check("UNVERIFIED")

    def test_auth_bypass_and_http_failure_block(self):
        for name in ("http_no_auth", "socks_no_auth", "curl_check"):
            with self.subTest(name=name), patch.object(a, name, return_value=a.Result("FAIL", name, "failed")):
                self.check("BLOCKED")

    def test_auth_inspection_failure_is_unverified(self):
        with patch.object(a, "http_no_auth", return_value=a.Result("UNVERIFIED", "http-no-auth", "timeout")):
            self.check("UNVERIFIED")

    def test_private_url_or_invalid_credentials_prevent_probes(self):
        for key, value in (("MIHOMO_READY_URL", "https://example.com/?subscription=private"),
                           ("MIHOMO_HTTPS_PROXY", "http://invalid")):
            with self.subTest(key=key), patch.dict(os.environ, {key: value}), \
                    patch.object(a, "service_active_check") as service, self.assertRaises(d.DiagnosticError):
                try:
                    d.codex_preflight(self.root)
                finally:
                    service.assert_not_called()

    def test_json_and_text_exit_mapping(self):
        for overall, code in (("SAFE_TO_LAUNCH", 0), ("BLOCKED", 1), ("UNVERIFIED", 2)):
            payload = d.preflight_error("fixture")
            payload["launch_safe"] = code == 0
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(d.report_preflight(overall, payload, True), code)
            data = json.loads(out.getvalue())
            self.assertEqual(data["schema"], d.SCHEMA)
            self.assertEqual(data["command"], "codex-preflight")
            self.assertEqual(data["overall"], overall)


@unittest.skipUnless(sys.platform == "linux", "real CLI needs Linux permissions")
class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-preflight-")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.lib = self.root / "lib"
        self.lib.mkdir(mode=0o700)
        self.proc = self.root / "proc"
        self.proc.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        for filename in ("diagnostics.py", "acceptance.py", "reporting.py"):
            shutil.copyfile(ROOT / "scripts" / filename, self.lib / filename)
        shutil.copyfile(ROOT / "src/common.bash", self.lib / "common.bash")
        # Only the disposable runtime redirects /proc and the two socket probes.
        # Production has no fixture-root or bypass switch. All CLI policy is real.
        p = self.lib / "diagnostics.py"
        p.write_text(p.read_text().replace('Path("/proc")', 'Path(' + repr(str(self.proc)) + ')'))
        p = self.lib / "acceptance.py"
        p.write_text(p.read_text() + '\nhttp_no_auth = lambda *a: Result("PASS", "http-no-auth", "fixture-407")\n'
                     + 'socks_no_auth = lambda *a: Result("PASS", "socks5h-no-auth", "fixture-ff")\n')
        self.put(self.bin / "codex", "#!/usr/bin/python3\nimport os,sys,json\n"
                 "assert not any(k.startswith('MIHOMO_') for k in os.environ)\n"
                 "assert os.environ['NO_PROXY'] == 'localhost,127.0.0.1,::1'\n"
                 "open(os.environ['RECORD'], 'w').write(json.dumps(sys.argv[1:]))\n"
                 "print('child-output')\nsys.exit(37)\n", 0o755)
        self.put(self.bin / "systemctl", "#!/bin/sh\nprintf 'active\\n'\n", 0o755)
        self.put(self.bin / "ss", "#!/bin/sh\nprintf 'LISTEN 0 4096 127.0.0.1:28443 0.0.0.0:*\\n'\n", 0o755)
        self.put(self.bin / "curl", "#!/bin/sh\nprintf '204\\t200\\t127.0.0.1\\t28443'\n", 0o755)
        self.put(self.root / "config", "MIHOMO_SERVICE=mihomo\nMIHOMO_PORT=28443\nMIHOMO_READY_URL=https://example.com/\n")
        self.put(self.root / "credentials", "\n".join(k + "='" + CONFIG[k] + "'" for k in
                 ("MIHOMO_HTTP_PROXY", "MIHOMO_HTTPS_PROXY", "MIHOMO_ALL_PROXY")) + "\n")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("MIHOMO_")}
        self.env.update(MIHOMO_USERCTL_LIB_DIR=str(self.lib), MIHOMO_USERCTL_CONFIG=str(self.root / "config"),
                        MIHOMO_USERCTL_CREDENTIALS=str(self.root / "credentials"), PATH=str(self.bin) + ":/usr/bin:/bin",
                        RECORD=str(self.root / "launched"))

    def put(self, path, text, mode=0o600):
        path.write_text(text)
        path.chmod(mode)

    def run_cli(self, *args):
        proc = subprocess.run(["bash", str(ROOT / "src/mihomoctl")] + list(args), env=self.env,
                              capture_output=True, text=True, timeout=20)
        self.assertNotIn("private-value", proc.stdout + proc.stderr)
        self.assertNotIn("secret-prompt-token", proc.stdout + proc.stderr)
        return proc

    def test_safe_launch_executes_with_literal_arguments_and_status(self):
        args = ["argument with spaces", "$(touch never)", "--version"]
        proc = self.run_cli("codex", "--", *args)
        self.assertEqual(proc.returncode, 37, proc.stderr)
        self.assertEqual(proc.stdout, "child-output\n")
        self.assertEqual(json.loads((self.root / "launched").read_text()), args)

    def test_preflight_only_never_executes(self):
        proc = self.run_cli("codex", "preflight", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["launch_safe"])
        self.assertFalse((self.root / "launched").exists())

    def test_blocked_and_unverified_never_execute_fake_codex(self):
        path = fixtures.DiagnosticTests.codex_fixture(self, self.proc, uid=os.getuid())
        for expected_rc in (1, 2):
            if expected_rc == 2:
                (path / "environ").unlink()
            result = self.run_cli("codex")
            self.assertEqual(result.returncode, expected_rc, result.stderr)
            self.assertFalse((self.root / "launched").exists())
            self.assertTrue(path.exists())
            result = self.run_cli("codex", "preflight", "--json")
            self.assertEqual(result.returncode, expected_rc)
            self.assertFalse(json.loads(result.stdout)["launch_safe"])

    def test_configuration_and_arguments_are_redacted_json_errors(self):
        for args in (("codex", "preflight", "--bad=private-value", "--json"),
                     ("codex", "preflight", "--json", "--json")):
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(json.loads(result.stdout)["launch_safe"])
        (self.root / "credentials").chmod(0o644)
        result = self.run_cli("codex", "preflight", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["overall"], "UNVERIFIED")
        self.assertEqual(self.run_cli("codex").returncode, 2)
        self.assertFalse((self.root / "launched").exists())

    def test_unsafe_runtime_dependency_never_launches(self):
        (self.lib / "acceptance.py").chmod(0o666)
        result = self.run_cli("codex", "preflight", "--json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["error"]["code"], "runtime-unavailable")
        self.assertEqual(self.run_cli("codex").returncode, 2)
        self.assertFalse((self.root / "launched").exists())

    def test_proxy_failures_and_missing_binary_never_execute(self):
        for name, text, code in (
                ("systemctl", "#!/bin/sh\necho inactive\nexit 3\n", 1),
                ("ss", "#!/bin/sh\nexit 0\n", 1),
                ("ss", "#!/bin/sh\nexit 2\n", 2),
                ("curl", "#!/bin/sh\nprintf '000\\t407\\t127.0.0.1\\t28443'\nexit 22\n", 1)):
            path = self.bin / name
            original = path.read_text()
            with self.subTest(name=name, code=code):
                self.put(path, text, 0o755)
                result = self.run_cli("codex")
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertFalse((self.root / "launched").exists())
                self.put(path, original, 0o755)
        (self.bin / "codex").unlink()
        self.assertEqual(self.run_cli("codex").returncode, 1)
        self.assertFalse((self.root / "launched").exists())

    def test_inconsistent_server_never_executes(self):
        fixtures.DiagnosticTests.codex_fixture(self, self.proc, uid=os.getuid(), env={"HTTPS_PROXY": HTTP})
        result = self.run_cli("codex")
        self.assertEqual(result.returncode, 1)
        self.assertIn("stale-inconsistent-app-server", result.stderr)
        self.assertFalse((self.root / "launched").exists())


if __name__ == "__main__":
    unittest.main()
