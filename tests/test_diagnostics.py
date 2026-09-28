"""Unit tests for stable JSON and redacted same-user process diagnostics."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import diagnostics as d


HTTP = "http://fixture:private-value@127.0.0.1:28443"
SOCKS = "socks5h://fixture:private-value@127.0.0.1:28443"


def expected():
    bypass = "localhost,127.0.0.1,::1"
    return {"http_proxy": HTTP, "https_proxy": HTTP, "all_proxy": SOCKS,
            "no_proxy": bypass, "HTTP_PROXY": HTTP, "HTTPS_PROXY": HTTP,
            "ALL_PROXY": SOCKS, "NO_PROXY": bypass}


class DiagnosticTests(unittest.TestCase):
    def codex_fixture(self, root, pid=42, uid=1000, env=None, role=b"app-server"):
        proc = root / str(pid)
        proc.mkdir()
        (proc / "status").write_text("Uid:\t{0} {0} {0} {0}\nPPid:\t1\n".format(uid))
        (proc / "comm").write_text("codex\n")
        (proc / "stat").write_text(str(pid) + " (codex) " + " ".join(["S"] + ["0"] * 18 + ["123"]))
        (proc / "environ").write_bytes(b"\0".join(
            (k + "=" + v).encode() for k, v in (env or {}).items()))
        (proc / "cmdline").write_bytes(b"codex\0" + role + b"\0secret-prompt-token\0")
        return proc

    def codex_report(self, root, **options):
        args = type("Args", (), dict(json=True, launch_advice=False, **options))()
        output = io.StringIO()
        with patch.object(d, "expected_environment", return_value=expected()), \
                patch.object(d.os, "getuid", return_value=1000, create=True), \
                patch.object(d.shutil, "which", return_value="/private/bin/codex"), \
                contextlib.redirect_stdout(output):
            self.assertEqual(d.handle_codex(args, root), 2)
        return json.loads(output.getvalue())

    def test_codex_empty_snapshot_is_not_a_failed_model_request(self):
        with tempfile.TemporaryDirectory() as folder:
            data = self.codex_report(Path(folder))
        self.assertEqual(data["processes"], [])
        self.assertEqual(data["overall"], "UNVERIFIED")
        self.assertEqual(data["websocket"], "UNVERIFIED")

    def test_codex_old_server_is_actionable_but_not_proof_of_direct_traffic(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, expected()):
            root = Path(folder)
            self.codex_fixture(root)
            data = self.codex_report(root)
        self.assertEqual(data["current_environment"]["classification"], "proxied")
        self.assertIn("existing-process-environment-differs", data["issues"])
        self.assertEqual(data["processes"][0]["role"], "app-server")
        self.assertNotIn("secret-prompt-token", repr(data))
        self.assertNotIn("private-value", repr(data))

    def test_codex_matching_server_does_not_claim_websocket_success(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, expected()):
            root = Path(folder)
            self.codex_fixture(root, env=expected())
            data = self.codex_report(root)
        self.assertEqual(data["issues"], [])
        self.assertEqual(data["model_request"], "UNVERIFIED")

    def test_codex_foreign_user_is_skipped_before_private_reads(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc = self.codex_fixture(root, uid=2000)
            (proc / "environ").unlink()
            (proc / "cmdline").unlink()
            data = self.codex_report(root)
        self.assertEqual(data["processes"], [])
        self.assertEqual(data["unverified_entries"], 0)

    def test_codex_unreadable_environment_and_pid_reuse_are_unverified(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                proc = self.codex_fixture(root)
                if not changed:
                    (proc / "environ").unlink()
                with patch.object(d, "process_identity", side_effect=[123, 124]):
                    data = self.codex_report(root)
                self.assertIsNone(data["processes"][0]["proxy_environment"])
                self.assertIn("process-inspection-incomplete", data["issues"])

    def test_codex_renamed_comm_matches_executable(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            proc = self.codex_fixture(root)
            (proc / "comm").write_text("worker\n")
            with patch.object(d.os, "readlink", return_value="/private/bin/codex (deleted)"):
                data = self.codex_report(root)
        self.assertEqual(len(data["processes"]), 1)

    def test_codex_missing_proc_is_sanitized_json_error(self):
        output = io.StringIO()
        with patch.object(d, "codex_snapshot", side_effect=d.DiagnosticError("proc-unavailable")), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(d.main(["codex", "--port", "28443", "--json"]), 2)
        data = json.loads(output.getvalue())
        self.assertEqual(data["command"], "diagnose-codex")
        self.assertEqual(data["error"]["code"], "proc-unavailable")

    def test_codex_launch_advice_warns_without_stopping_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.codex_fixture(root)
            output, error = io.StringIO(), io.StringIO()
            args = type("Args", (), {"json": False, "launch_advice": True})()
            with patch.object(d, "expected_environment", return_value=expected()), \
                    patch.object(d.os, "getuid", return_value=1000, create=True), \
                    patch.object(d.os, "kill", side_effect=AssertionError("no signals")), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                self.assertEqual(d.handle_codex(args, root), 0)
            self.assertEqual(output.getvalue(), "")
            self.assertIn("existing Codex processes", error.getvalue())

    def test_proxy_environment_classifies_without_returning_values(self):
        self.assertEqual(d.proxy_environment({}, expected())["classification"], "direct")
        values = {name: value.encode() for name, value in expected().items()}
        result = d.proxy_environment(values, expected())
        self.assertEqual(result["classification"], "proxied")
        self.assertNotIn("private-value", repr(result))
        values["HTTP_PROXY"] = b"different"
        self.assertEqual(d.proxy_environment(values, expected())["classification"], "inconsistent")

    def test_connection_categories_intersects_process_socket_inodes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            net = root / "42/net"
            net.mkdir(parents=True)
            net.joinpath("tcp").write_text(
                "header\n 0: 0100007F:6F1B 0100007F:9C40 01 0 0 0 0 0 11\n"
                " 1: 0100000A:1111 08080808:01BB 01 0 0 0 0 0 12\n")
            net.joinpath("tcp6").write_text("header\n")
            with patch.object(d, "process_socket_inodes", return_value={"11", "12"}):
                result = d.connection_categories(root, 42, 28443)
            self.assertEqual(result, {"listener_established": 1,
                                      "other_non_loopback_established": 1})

    def test_inspect_enforces_owner_and_redacts_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "MIHOMO_HTTP_PROXY": HTTP, "MIHOMO_HTTPS_PROXY": HTTP,
                "MIHOMO_ALL_PROXY": SOCKS}, clear=False):
            root = Path(folder)
            for pid, parent in ((42, 7), (7, 0)):
                proc = root / str(pid)
                (proc / "fd").mkdir(parents=True)
                (proc / "net").mkdir()
                (proc / "net/tcp").write_text("header\n")
                (proc / "status").write_text("Uid:\t1000 1000 1000 1000\nPPid:\t{}\n".format(parent))
                (proc / "comm").write_text("codex\n" if pid == 42 else "parent\n")
                (proc / "environ").write_bytes(b"\0".join(
                    (name + "=" + value).encode() for name, value in expected().items()) + b"\0")
            item = d.inspect(root, 42, 28443, uid=1000)
            self.assertEqual(item["proxy_environment"]["classification"], "proxied")
            self.assertTrue(item["parent"]["same_user"])
            self.assertEqual(item["parent"], {"pid": 7, "same_user": True})
            self.assertNotIn("private-value", repr(item))
            with self.assertRaises(d.DiagnosticError) as caught:
                d.inspect(root, 42, 28443, uid=2000)
            self.assertEqual(caught.exception.code, "process-not-owned-by-current-user")

    def test_format_and_error_json_are_single_valid_objects(self):
        for argv, expected_rc in ((["format", "status", "--service", "up", "--enabled", "disabled",
                                    "--listener", "up", "--port", "28443"], 0),
                                  (["error", "status", "config-invalid"], 2)):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(d.main(argv), expected_rc)
            parsed = json.loads(output.getvalue())
            self.assertEqual(parsed["schema"], d.SCHEMA)

    def test_name_no_match_is_a_measured_failure(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {
                "MIHOMO_HTTP_PROXY": HTTP, "MIHOMO_HTTPS_PROXY": HTTP,
                "MIHOMO_ALL_PROXY": SOCKS}, clear=False):
            args = type("Args", (), {"target": "codex", "port": 28443, "json": True,
                                      "report_command": "diagnose-name"})()
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(d.os, "getuid", return_value=1000, create=True):
                self.assertEqual(d.handle_name(args, Path(folder)), 1)
            self.assertEqual(json.loads(output.getvalue())["overall"], "FAIL")

    def test_unreadable_socket_state_is_not_reported_as_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "42").mkdir()
            with self.assertRaises(d.DiagnosticError) as caught:
                d.connection_categories(root, 42, 28443)
            self.assertEqual(caught.exception.code, "process-sockets-unreadable")

    def test_name_checks_uid_before_reading_foreign_comm(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.object(d.os, "getuid", return_value=1000, create=True):
            root = Path(folder)
            proc = root / "42"
            proc.mkdir()
            (proc / "status").write_text("Uid:\t2000 2000 2000 2000\nPPid:\t1\n")
            args = type("Args", (), {"target": "foreign", "port": 28443, "json": True,
                                      "report_command": "diagnose-name"})()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(d.handle_name(args, root), 1)
            self.assertFalse((proc / "comm").exists())

    def test_canonical_and_legacy_report_commands_are_versioned(self):
        for command in ("diagnose-process", "inspect-process"):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                d.emit_json(command, "FAIL", {"process": None})
            document = json.loads(output.getvalue())
            self.assertEqual(document["schema"], d.SCHEMA)
            self.assertEqual(document["command"], command)

    def test_disappeared_and_unreadable_processes_are_unverified_errors(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with self.assertRaises(d.DiagnosticError) as caught:
                d.read_status(root, 999)
            self.assertEqual(caught.exception.code, "process-unreadable")
            proc = root / "42"
            proc.mkdir()
            with self.assertRaises(d.DiagnosticError) as caught:
                d.read_environment(root, 42)
            self.assertEqual(caught.exception.code, "process-environment-unreadable")


if __name__ == "__main__":
    unittest.main()
