"""State, real socket ownership, bounded jobs and node-only transactions."""
import json
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

if sys.platform != "linux":
    raise unittest.SkipTest("Linux ownership, private paths and sockets")

from scripts import controller_state as state, controller_runtime as runtime
from scripts import controller_subscriptions as subscriptions, controller_transaction as transaction
from scripts.controller_types import ControlError
from scripts.controller_service import ConsoleService


class StoreTests(unittest.TestCase):
    def test_stream_stop_prevents_late_data_and_redacts_reader_failure(self):
        store = state.Store()
        self.addCleanup(store.close)
        entered, release = threading.Event(), threading.Event()
        def stream(emit, stop):
            emit({"message": "safe"})
            entered.set()
            release.wait(2)
            emit({"message": "late"})
        self.assertTrue(store.stream("logs", stream))
        self.assertTrue(entered.wait(1))
        self.assertFalse(store.stream("logs", stream))
        store.stop_stream("logs")
        release.set()
        time.sleep(.03)
        self.assertEqual(list(store.state.logs), [{"message": "safe"}])
        def failed(emit, stop):
            raise RuntimeError("PRIVATE-CREDENTIAL")
        store.stream("logs", failed)
        for _ in range(100):
            if store.state.snapshots["logs"].error:
                break
            time.sleep(.01)
        self.assertEqual(store.state.snapshots["logs"].error, "stream-unverified")
        self.assertEqual(store.state.snapshots["logs"].freshness, "stale")

    def test_late_result_does_not_replace_newer_snapshot(self):
        store = state.Store()
        self.addCleanup(store.close)
        entered, release = threading.Event(), threading.Event()
        def old():
            entered.set(); release.wait(2)
            return "old"
        store.submit("nodes", old)
        self.assertTrue(entered.wait(1))
        self.assertFalse(store.submit("nodes", lambda: "duplicate"))
        store.invalidate("nodes")
        store.submit("nodes", lambda: "new")
        for _ in range(100):
            if store.state.snapshots["nodes"].value == "new":
                break
            time.sleep(.01)
        release.set(); time.sleep(.03)
        self.assertEqual(store.state.snapshots["nodes"].value, "new")

    def test_failed_refresh_retains_stale_data_and_redacts_exception(self):
        store = state.Store()
        self.addCleanup(store.close)
        store.state.snapshots["runtime"] = state.Snapshot(value={"service": "active"}, freshness="fresh")
        def failed():
            raise RuntimeError("https://private-token@private-host/")
        store.submit("runtime", failed)
        for _ in range(100):
            if store.drain():
                break
            time.sleep(.01)
        snapshot = store.state.snapshots["runtime"]
        self.assertEqual(snapshot.freshness, "stale")
        self.assertEqual(snapshot.value, {"service": "active"})
        self.assertEqual(snapshot.error, "operation-unverified")
        for index in range(3000):
            store.state.logs.append(index)
        self.assertEqual(len(store.state.logs), 2000)


class RuntimeTests(unittest.TestCase):
    def test_conflict_prevents_service_action_in_real_dispatcher(self):
        with tempfile.TemporaryDirectory() as folder, socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            port = listener.getsockname()[1]
            environment = {"HOME": folder, "XDG_CONFIG_HOME": folder + "/config", "XDG_DATA_HOME": folder + "/data"}
            with patch.dict(os.environ, environment), patch.object(sys, "argv", ["runtime", "start", "mihomo", str(port)]), patch.object(runtime, "service_properties", return_value={"MainPID": "0"}), patch.object(runtime.subprocess, "run") as mutation:
                with self.assertRaisesRegex(ControlError, "ownership-unverified"):
                    runtime.main()
                mutation.assert_not_called()

    def test_live_socket_owned_by_service_allowed_other_service_blocked(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            port = listener.getsockname()[1]
            properties = {"MainPID": str(os.getpid()), "ControlGroup": "", "ActiveState": "active"}
            with patch.object(runtime, "service_properties", return_value=properties):
                runtime.gate("mihomo", [port], after=True)
            with patch.object(runtime, "service_properties", return_value={"MainPID": "0"}):
                with self.assertRaisesRegex(ControlError, "ownership-unverified"):
                    runtime.gate("mihomo", [port])

    def test_wildcard_and_foreign_uid_are_blocked(self):
        with socket.socket() as listener:
            listener.bind(("0.0.0.0", 0)); listener.listen()
            with patch.object(runtime, "service_properties", return_value={"MainPID": str(os.getpid())}):
                with self.assertRaisesRegex(ControlError, "port-collision"):
                    runtime.gate("mihomo", [listener.getsockname()[1]])
        with patch.object(runtime, "listeners", return_value=[{"uid": os.getuid()+1, "family": "tcp", "address": "0100007F"}]), patch.object(runtime, "service_properties", return_value={}):
            with self.assertRaisesRegex(ControlError, "port-collision"):
                runtime.gate("mihomo", [17890])

    def test_missing_listener_cannot_pass_post_start(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        with patch.object(runtime, "service_properties", return_value={}):
            runtime.gate("mihomo", [port])
            with self.assertRaisesRegex(ControlError, "listener-missing"):
                runtime.gate("mihomo", [port], after=True)


class DiagnosisTests(unittest.TestCase):
    def test_invalid_private_url_never_enters_subprocess_argv(self):
        service = ConsoleService("/not/read/by/this/test")
        with patch.object(subprocess, "run") as run:
            for target in ("https://user:private@example.com/", "https://example.com/?token=private", "http://example.com/", "https://localhost/"):
                with self.assertRaises(ControlError):
                    service.diagnose("url", target)
            with self.assertRaises(ControlError):
                service.diagnose("process", "1;kill")
            run.assert_not_called()

    def test_process_report_keeps_original_status_and_strips_terminal_controls(self):
        service = ConsoleService("/not/read/by/this/test")
        response = {"overall": "UNVERIFIED", "process": {"name": "untrusted\u001b[31m", "pid": 123}}
        with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 2, json.dumps(response).encode(), b"")) as run:
            result = service.diagnose("process", "123")
        self.assertEqual(run.call_args.args[0][-3:], ["process", "123", "--json"])
        self.assertEqual(result["overall"], "UNVERIFIED")
        self.assertNotIn("\u001b", result["process"]["name"])


@unittest.skipUnless(importlib.util.find_spec("yaml"), "optional Controller YAML dependency")
class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        environment = patch.dict(os.environ, {"HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "data")})
        environment.start(); self.addCleanup(environment.stop)
        self.config = self.root / "config.yaml"
        self.original = '# private listener\nmixed-port: 17890\nsecret: unchanged-secret\nproxies: [{name: old, type: ss, password: KEEP}]\nproxy-groups: [{name: Proxy, type: select, proxies: [old]}]\nrules: [MATCH,DIRECT]\n'
        self.write(self.config, self.original)
        self.source = self.root / "source.yaml"
        self.write(self.source, 'proxies: [{name: new, type: ss, server: PRIVATE, port: 443, password: PRIVATE-TOKEN}]\n')
        self.service = subscriptions.Subscriptions(self.config, str(self.root))

    def write(self, path, content):
        path.write_text(content, encoding="utf-8"); path.chmod(0o600)

    def test_preview_private_apply_preserves_non_node_fields(self):
        plan = self.service.preview(source_file=self.source)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertNotIn("PRIVATE", json.dumps(plan))
        for path in self.service.root.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/core"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(result["state"], "restart-required")
        self.assertEqual(Path(result["backup"]).read_text(), self.original)
        import yaml
        before, after = yaml.safe_load(self.original), yaml.safe_load(self.config.read_text())
        before.pop("proxies"); after.pop("proxies")
        self.assertEqual(before, after)

    def test_full_config_alias_duplicate_and_nonprivate_rejected(self):
        for content in ('proxies: []\nsecret: bad\n', 'proxies: &n []\n', 'proxies: []\nproxies: []\n'):
            self.write(self.source, content)
            with self.assertRaises(ControlError):
                self.service.preview(source_file=self.source)
        self.source.chmod(0o644)
        with self.assertRaises(ControlError):
            self.service.preview(source_file=self.source)
        self.assertEqual(self.config.read_text(), self.original)

    def test_drift_tampering_validation_failure_leave_active_bytes(self):
        plan = self.service.preview(source_file=self.source)
        self.write(self.config, self.original + "# concurrent edit\n")
        with self.assertRaisesRegex(ControlError, "subscription-config-changed"):
            self.service.apply(plan["id"], plan["sha256"])
        self.write(self.config, self.original)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/core"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ControlError, "validation-failed"):
                self.service.apply(plan["id"], plan["sha256"])
        candidate = self.service.root / (plan["id"] + ".candidate.yaml")
        self.write(candidate, candidate.read_text() + "secret: replaced\n")
        with self.assertRaisesRegex(ControlError, "candidate-changed"):
            self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.root.glob("*.before-policy-*")), [])

    def test_download_rejects_insecure_url_before_connection(self):
        with patch.object(subscriptions.http.client, "HTTPSConnection") as connect:
            for url in ("http://example.com/private", "https://u:p@example.com/", "https://example.com/#token", "https://example.com/\nsecret"):
                with self.assertRaises(ControlError):
                    subscriptions.download(url)
            connect.assert_not_called()

    def test_post_replace_failure_restores_original_and_retains_private_backup(self):
        plan = self.service.preview(source_file=self.source)
        atomic = transaction.files.atomic_bytes
        failed = False
        def fail_after_replace(path, data, *args):
            nonlocal failed
            atomic(path, data, *args)
            if Path(path) == self.config and not failed:
                failed = True
                raise OSError("simulated directory fsync failure")
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/core"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), patch.object(transaction.files, "atomic_bytes", side_effect=fail_after_replace):
            with self.assertRaisesRegex(ControlError, "original-restored"):
                self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(len(list(self.root.glob("*.before-policy-*"))), 1)

    def test_crlf_bytes_are_preserved_in_backup_and_unmodified_sections(self):
        original = self.original.replace("\n", "\r\n").encode()
        self.config.write_bytes(original)
        plan = self.service.preview(source_file=self.source)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/fake/core"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(Path(result["backup"]).read_bytes(), original)
        self.assertIn(b"mixed-port: 17890\r\nsecret: unchanged-secret\r\n", self.config.read_bytes())


class BatchTests(unittest.TestCase):
    def test_bounded_batch_and_cancellation(self):
        service = ConsoleService("/not/read/by/this/test")
        cancelled, started, release = threading.Event(), [], threading.Event()
        lock = threading.Lock()
        def latency(node):
            with lock:
                started.append(node)
                if len(started) == 4:
                    cancelled.set(); release.set()
            release.wait(2)
            return {"name": node, "delay_ms": 1}
        with patch.object(service, "latency", side_effect=latency):
            result = service.batch_latency([str(n) for n in range(20)], cancelled)
        self.assertEqual(len(started), 4)
        self.assertEqual(sum(row["state"] == "cancelled" for row in result["results"]), 16)
