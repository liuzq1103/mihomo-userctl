"""First-run recovery and provider-policy integration boundaries."""
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import select
import signal
import struct
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

if sys.platform != "linux":
    raise unittest.SkipTest("Linux private paths and controller ownership")

import fcntl
import pty
import termios

from scripts import controller_dashboard as dashboard, controller_transaction as transaction
from scripts import controller_subscriptions as subscriptions, controller as controller
from scripts.controller_config import read_config, endpoint
from scripts.controller_service import ConsoleService
from scripts.controller_types import ControlError
from scripts.controller_legacy import plain_console


class TaskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config.yaml"
        self.source = self.root / "subscription.yaml"
        self.write(self.config, 'mixed-port: 25000\nsecret: local-secret\nproxies: []\nproxy-groups: [{name: Old, type: select, proxies: [DIRECT]}]\nrules: ["MATCH,Old"]\n')
        self.original = self.config.read_bytes()
        self.env = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data"), "MIHOMO_CORE_BIN": "/fixture/mihomo"})
        self.env.start(); self.addCleanup(self.env.stop)
        self.core = patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0))
        self.run = self.core.start(); self.addCleanup(self.core.stop)
        self.sub = subscriptions.Subscriptions(self.config, str(self.root))

    def write(self, path, text):
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)

    def provider(self):
        self.write(self.source, '''mixed-port: 1
secret: PROVIDER-SECRET
dns: {enable: true}
proxy-providers: {Airport: {type: http, url: "https://example.com/PRIVATE-TOKEN", path: ./providers/airport.yaml, interval: 3600}}
proxy-groups:
- {name: 自动, type: url-test, use: [Airport], url: "https://example.com", interval: 300}
- {name: 出口, type: select, proxies: [自动, DIRECT]}
rule-providers: {Sites: {type: http, behavior: domain, url: "https://example.com/PRIVATE-RULE", path: ./rules/sites.yaml, interval: 3600}}
rules: ["RULE-SET,Sites,出口", "MATCH,出口"]
''')

    def test_initialize_idempotent_no_dashboard_and_persistent_pending(self):
        result = dashboard.initialize(self.config, str(self.root))
        _, data, _ = read_config(self.config)
        port, token = endpoint(data)
        self.assertNotEqual(port, 25000)
        self.assertGreaterEqual(len(token), 32)
        self.assertNotIn("external-ui", data)
        self.assertEqual(Path(result["backup"]).read_bytes(), self.original)
        initialized = self.config.read_bytes()
        self.assertEqual(dashboard.initialize(self.config, str(self.root))["state"], "unchanged")
        self.assertEqual(self.config.read_bytes(), initialized)
        self.assertEqual(self.run.call_count, 1)
        service = ConsoleService(self.config, str(self.root))
        self.assertTrue(service.pending_restart)
        service.restore()
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_initialize_rejects_exposed_listener_extra_listener_and_port_conflict(self):
        for extra in ('external-controller: 0.0.0.0:29000\nsecret: ' + 'a'*32 + '\n',
                      'external-controller-unix: /tmp/api.sock\n'):
            self.write(self.config, self.original.decode() + extra)
            before = self.config.read_bytes()
            with self.assertRaises(ControlError):
                dashboard.initialize(self.config, str(self.root))
            self.assertEqual(self.config.read_bytes(), before)
        self.write(self.config, self.original.decode())
        with self.assertRaisesRegex(ControlError, "conflicts-with-proxy"):
            dashboard.initialize(self.config, str(self.root), 25000)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            with self.assertRaisesRegex(ControlError, "port-in-use"):
                dashboard.initialize(self.config, str(self.root), listener.getsockname()[1])
        self.run.assert_not_called()

    def test_validation_failure_never_changes_active_config(self):
        self.run.return_value = subprocess.CompletedProcess([], 1)
        with self.assertRaisesRegex(ControlError, "validation-failed"):
            dashboard.initialize(self.config, str(self.root))
        self.assertEqual(self.config.read_bytes(), self.original)
        self.provider()
        with self.assertRaisesRegex(ControlError, "validation-failed"):
            self.sub.preview(source_file=self.source, policy="provider")
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_provider_keeps_groups_rules_and_runtime_and_clears_old_nodes(self):
        self.provider()
        plan = self.sub.preview(source_file=self.source, policy="provider")
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(plan["groups"], 2)
        self.assertEqual(plan["removed_groups"], 1)
        self.assertEqual(plan["ignored_fields"], ["dns", "mixed-port", "secret"])
        self.assertNotIn("PRIVATE", json.dumps(plan))
        self.sub.apply(plan["id"], plan["sha256"])
        _, after, _ = read_config(self.config)
        _, incoming, _ = read_config(self.source)
        for key in subscriptions.POLICY_FIELDS:
            self.assertEqual(after[key], incoming.get(key, subscriptions.POLICY_FIELDS[key]()))
        self.assertEqual(after["secret"], "local-secret")
        self.assertEqual(after["mixed-port"], 25000)
        self.assertNotIn("dns", after)

    def test_missing_policy_fields_clear_old_strategy(self):
        self.write(self.source, 'proxy-groups: [{name: New, type: select, proxies: [DIRECT]}]\n')
        plan = self.sub.preview(source_file=self.source, policy="provider")
        self.sub.apply(plan["id"], plan["sha256"])
        _, data, _ = read_config(self.config)
        self.assertEqual(data["rules"], [])
        self.assertEqual(data["proxy-providers"], {})
        self.assertEqual(data["rule-providers"], {})
        self.assertEqual([row["name"] for row in data["proxy-groups"]], ["New"])

    def test_invalid_references_names_and_paths_rejected_before_core(self):
        for content in ('proxy-groups: [{name: A, type: select, proxies: [Missing]}]',
                        'proxy-groups: [{name: A, type: select, use: [Missing]}]',
                        'proxy-groups: [{name: A, type: select}, {name: A, type: select}]',
                        'rules: ["MATCH,Missing"]', 'rules: ["RULE-SET,Missing,DIRECT"]',
                        'proxy-providers: {A: {type: http, path: ../escape}}',
                        'rule-providers: {A: {type: file, path: /tmp/escape}}',
                        'secret: only-runtime'):
            with self.subTest(content=content):
                self.write(self.source, content + '\n')
                with self.assertRaises(ControlError):
                    self.sub.preview(source_file=self.source, policy="provider")
        self.run.assert_not_called()

    def test_provider_symlink_cannot_escape_home(self):
        (self.root / "escape").symlink_to("/tmp", target_is_directory=True)
        self.write(self.source, 'proxy-providers: {A: {type: http, path: escape/nodes.yaml}}\n')
        with self.assertRaises((ControlError, subscriptions.files.InstallError)):
            self.sub.preview(source_file=self.source, policy="provider")
        self.run.assert_not_called()

    def test_provider_cache_cannot_overwrite_configuration_or_state(self):
        for path in ("config.yaml", "cache.db", "providers/config.yaml.before-policy-abc",
                     "providers/config.yaml.userctl-state.json"):
            self.write(self.source, 'proxy-providers: {A: {type: http, path: ' + path + '}}\n')
            with self.subTest(path=path), self.assertRaisesRegex(ControlError, "cache-path-unsafe"):
                self.sub.preview(source_file=self.source, policy="provider")
        self.write(self.source, 'proxy-providers: {A: {type: http}}\n')
        with self.assertRaisesRegex(ControlError, "cache-path-required"):
            self.sub.preview(source_file=self.source, policy="provider")
        self.write(self.source, 'proxy-providers: {A: {type: http, path: providers/shared.yaml}, B: {type: http, path: providers/shared.yaml}}\n')
        with self.assertRaisesRegex(ControlError, "cache-path-unsafe"):
            self.sub.preview(source_file=self.source, policy="provider")
        self.run.assert_not_called()
        self.assertEqual(self.config.read_bytes(), self.original)

        nested = subscriptions.Subscriptions(self.root / "providers/main.yaml", str(self.root))
        with self.assertRaisesRegex(ControlError, "cache-path-unsafe"):
            nested.check_provider_paths({"proxy-providers": {"A": {"type": "http", "path": "providers/main.yaml"}}, "rule-providers": {}})

    def test_builtin_global_policy_is_accepted(self):
        self.write(self.source, 'rules: ["MATCH,GLOBAL"]\n')
        plan = self.sub.preview(source_file=self.source, policy="provider")
        self.sub.apply(plan["id"], plan["sha256"])
        self.assertEqual(read_config(self.config)[1]["rules"], ["MATCH,GLOBAL"])
        self.write(self.source, 'proxy-groups: [{name: GLOBAL, type: select, proxies: [DIRECT]}]\nrules: ["MATCH,GLOBAL"]\n')
        plan = self.sub.preview(source_file=self.source, policy="provider")
        self.sub.apply(plan["id"], plan["sha256"])
        self.assertEqual(read_config(self.config)[1]["proxy-groups"][0]["name"], "GLOBAL")

    def test_initialize_accepts_null_listeners_and_documented_provider_directory(self):
        self.write(self.config, self.original.decode() + 'listeners: null\n')
        self.assertEqual(dashboard.initialize(self.config, str(self.root))["state"], "restart-required")
        self.write(self.source, 'proxy-providers: {A: {type: http, path: ./proxy_providers/subscription.yaml}}\n')
        self.assertEqual(self.sub.preview(source_file=self.source, policy="provider")["policy"], "provider")

    def test_active_start_preserves_pending_receipt_until_restart(self):
        from scripts import controller_runtime as runtime
        (self.root / "mihomo").mkdir(mode=0o700)
        self.config = self.root / "mihomo/config.yaml"
        self.write(self.config, self.original.decode())
        self.sub = subscriptions.Subscriptions(self.config, str(self.root))
        self.write(self.source, 'proxies: [{name: New, type: direct}]\n')
        plan = self.sub.preview(source_file=self.source)
        self.sub.apply(plan["id"], plan["sha256"])
        service = ConsoleService(self.config, str(self.root))
        receipt = self.config.with_name(self.config.name + ".userctl-state.json")
        self.assertTrue(service.pending_restart)
        self.run.return_value = subprocess.CompletedProcess([], 0, stdout=b"")
        with patch.object(runtime, "gate", return_value={"ActiveState": "active"}) as gate, \
                patch.object(runtime, "configured_ports", return_value=([25000], "digest")), \
                patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root)}), \
                contextlib.redirect_stdout(io.StringIO()):
            for state in ("active", "activating", "reloading"):
                gate.return_value = {"ActiveState": state}
                with self.subTest(state=state), patch.object(sys, "argv", ["runtime", "start", "fixture", "25000"]):
                    runtime.main()
                self.assertTrue(receipt.exists())
                service.shell("start")
                self.assertTrue(service.pending_restart)
            with patch.object(sys, "argv", ["runtime", "restart", "fixture", "25000"]):
                runtime.main()
        self.assertFalse(receipt.exists())
        service.shell("restart")
        self.assertFalse(service.pending_restart)

    def test_apply_detects_config_drift_and_candidate_tampering(self):
        self.provider()
        plan = self.sub.preview(source_file=self.source, policy="provider")
        self.write(self.config, self.original.decode() + '# concurrent\n')
        with self.assertRaisesRegex(ControlError, "config-changed"):
            self.sub.apply(plan["id"], plan["sha256"])
        self.write(self.config, self.original.decode())
        candidate = self.sub.root / (plan["id"] + '.candidate.yaml')
        candidate.write_bytes(candidate.read_bytes() + b'# tampered\n')
        with self.assertRaisesRegex(ControlError, "candidate-changed"):
            self.sub.apply(plan["id"], plan["sha256"])

    def test_missing_configuration_and_capability_do_not_block_home(self):
        service = ConsoleService(self.root / "missing.yaml", str(self.root))
        self.assertEqual(service.read("overview")["controller"], "unavailable")
        self.assertEqual(service.read("profiles")["configuration"], "missing")
        with self.assertRaisesRegex(ControlError, "config-missing"):
            service.initialize()
        class Partial:
            def request(self, path, **kwargs):
                if path == "/version": return {"version": "different-version"}
                raise ControlError("controller-capability-unsupported")
        with patch.object(service, "client", return_value=Partial()):
            home = service.read("overview")
        self.assertEqual(home["core"], "different-version")
        self.assertEqual(set(home["capabilities"]), {"groups", "connections", "mode"})

    def test_legacy_node_plan_without_policy_stays_node_only(self):
        self.write(self.source, 'proxies: [{name: New, type: direct}]\n')
        plan = self.sub.preview(source_file=self.source)
        record = self.sub.root / (plan["id"] + '.json')
        value = json.loads(record.read_text())
        value.pop("policy")
        self.write(record, json.dumps(value))
        self.sub.apply(plan["id"], plan["sha256"])
        _, after, _ = read_config(self.config)
        self.assertEqual(after["proxy-groups"][0]["name"], "Old")
        self.assertEqual(after["rules"], ["MATCH,Old"])

    def test_cli_provider_stdin_preview_is_private_and_compatible(self):
        stdin = io.TextIOWrapper(io.BytesIO(b'proxies: [{name: New, type: direct}]\nproxy-groups: [{name: Exit, type: select, proxies: [New]}]\nrules: ["MATCH,Exit"]\nsecret: PRIVATE-TOKEN\n'), encoding="utf-8")
        with patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(controller.main(["subscription", "preview", "--policy", "provider", "--stdin", "--config", str(self.config), "--home-dir", str(self.root), "--json"]), 0)
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["policy"], "provider")
        self.assertNotIn("PRIVATE-TOKEN", output.getvalue())
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_restore_refuses_external_config_changes(self):
        service = ConsoleService(self.config, str(self.root))
        service.initialize()
        self.write(self.config, self.config.read_text() + '# manual edit\n')
        before = self.config.read_bytes()
        with self.assertRaisesRegex(ControlError, "restore-cancelled"):
            service.restore()
        self.assertEqual(self.config.read_bytes(), before)

    def test_plain_menu_opens_without_config_and_quits(self):
        service = ConsoleService(self.root / "missing.yaml")
        with contextlib.redirect_stdout(io.StringIO()) as output, patch.object(sys.stdin, "isatty", return_value=True), patch.object(sys.stdout, "isatty", return_value=True), patch("builtins.input", side_effect=["1", "q"]):
            self.assertEqual(plain_console(service)["state"], "closed")
        self.assertIn("初始化", output.getvalue())

    def test_engine_auto_falls_back_without_downloading(self):
        with patch("scripts.controller_deps.interpreter", return_value=(None, None)), patch.object(controller.importlib.util, "find_spec", return_value=None), patch.object(controller, "plain_console", return_value={"state": "closed"}) as menu, contextlib.redirect_stdout(io.StringIO()):
            controller.main(["tui", "--config", str(self.config)])
        menu.assert_called_once()

    def test_piped_tui_stdin_restores_controlling_terminal_and_requires_save(self):
        self.check_piped_tui("plain")
        if importlib.util.find_spec("textual"):
            self.check_piped_tui("textual")

    def check_piped_tui(self, engine):
        core = self.root / "core"
        core.write_text('#!/bin/sh\nexit 0\n')
        core.chmod(0o700)
        reader, writer = os.pipe()
        os.write(writer, b'proxies: [{name: New, type: direct}]\nproxy-groups: [{name: Exit, type: select, proxies: [New]}]\nrules: ["MATCH,Exit"]\nsecret: PRIVATE-TOKEN\n')
        os.close(writer)
        pid, master = pty.fork()
        if pid == 0:
            fcntl.ioctl(1, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
            os.dup2(reader, 0)
            os.close(reader)
            os.execve(sys.executable, [sys.executable, controller.__file__, "tui", "--stdin", "--engine", engine, "--config", str(self.config), "--home-dir", str(self.root)], dict(os.environ, MIHOMO_CORE_BIN=str(core), TERM="xterm-256color"))
        os.close(reader)
        output, sent, waited = b"", False, False
        try:
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                if select.select([master], [], [], .1)[0]:
                    try:
                        output += os.read(master, 65536)
                    except OSError:
                        break
                marker = "已收到标准输入" if engine == "plain" else "预览（尚未保存）"
                if not sent and marker.encode() in output:
                    os.write(master, b'3\nn\nq\n' if engine == "plain" else b'q')
                    sent = True
            self.assertTrue(sent, output.decode(errors="replace"))
            child, status = os.waitpid(pid, os.WNOHANG)
            deadline = time.monotonic() + 1
            while not child and time.monotonic() < deadline:
                time.sleep(.01)
                child, status = os.waitpid(pid, os.WNOHANG)
            self.assertEqual(child, pid, "stdin UI did not exit after q")
            waited = True
            self.assertTrue(os.WIFEXITED(status))
            self.assertEqual(os.WEXITSTATUS(status), 0)
            self.assertNotIn(b'PRIVATE-TOKEN', output)
            self.assertEqual(self.config.read_bytes(), self.original)
        finally:
            if not waited:
                try:
                    os.kill(pid, signal.SIGTERM)
                    os.waitpid(pid, 0)
                except ProcessLookupError:
                    pass
            os.close(master)


if __name__ == "__main__":
    unittest.main()
