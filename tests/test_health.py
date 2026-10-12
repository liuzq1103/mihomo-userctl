"""Synthetic routing graphs and scoped health-check transactions, no subscriptions."""
import json
import contextlib
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

if sys.platform == "win32":
    with patch.dict(sys.modules, {"fcntl": MagicMock()}):
        from scripts import controller_health as health, controller_transaction as tx
        from scripts.controller_service import ConsoleService, proxies, select
        from scripts import controller
else:
    from scripts import controller_health as health, controller_transaction as tx, controller
    from scripts.controller_service import ConsoleService, proxies, select
ControlError = health.ControlError
import yaml


class GraphTests(unittest.TestCase):
    def rows(self, selected="A", history=None, alive=True):
        class Client:
            def request(self, *args, **kwargs):
                return {"proxies": {
                    "Work": {"type": "Selector", "all": ["Entry"], "now": "Entry"},
                    "Web": {"type": "Selector", "all": ["Entry"], "now": "Entry"},
                    "Entry": {"type": "Selector", "all": ["Auto", "A"], "now": selected},
                    "Auto": {"type": "URLTest", "all": ["A", "B"], "now": "A", "fixed": ""},
                    "A": {"type": "Socks5", "alive": alive, "history": history or []},
                    "B": {"type": "Socks5", "alive": alive, "history": history or []}}}
        return proxies(Client())

    def test_nested_manual_bypass_and_shared_impact(self):
        rows = self.rows()
        self.assertEqual(rows["Work"]["selection_chain"], ["Work", "Entry", "A"])
        self.assertIn("manual-path-bypasses-automatic", rows["Work"]["warnings"])
        self.assertEqual(rows["Work"]["automatic_candidates"], [{"group": "Auto", "path": ["Work", "Entry", "Auto"]}])
        self.assertEqual(rows["Entry"]["affected_groups"], ["Web", "Work"])
        self.assertIn("no-probe-records", rows["Auto"]["warnings"])

    def test_selector_to_auto_is_not_a_risk(self):
        rows = self.rows("Auto")
        self.assertEqual(rows["Work"]["automatic_groups"], ["Auto"])
        self.assertEqual(rows["Work"]["warnings"], [])

    def test_unknown_cycles_missing_and_fixed(self):
        rows = self.rows()
        rows["Entry"]["selected"] = "Work"
        rows["Entry"]["members"].append("Work")
        self.assertEqual(health.annotate(rows)["Work"]["chain_state"], "cycle")
        rows["Entry"]["selected"] = "Gone"
        rows["Entry"]["members"].append("Gone")
        self.assertEqual(health.annotate(rows)["Work"]["chain_state"], "missing-reference")
        rows["Entry"]["selected"] = None
        self.assertEqual(health.annotate(rows)["Work"]["chain_state"], "unknown-selection")
        rows["Auto"]["fixed"] = "A"
        self.assertIn("automatic-fixed-selection", health.annotate(rows)["Auto"]["warnings"])

    def test_all_failed_requires_records_for_every_member(self):
        rows = self.rows(history=[{"time": "fixture", "delay": 0}], alive=False)
        self.assertEqual(rows["Auto"]["probe_state"], "all-observed-failed")
        rows["B"]["probe_observed"] = False
        self.assertEqual(health.annotate(rows)["Auto"]["probe_state"], "unknown")

    def test_selection_failure_never_reports_success(self):
        class Client:
            def verify(self):
                pass
            def request(self, path, method="GET", body=None, **kw):
                return {"proxies": {"Entry": {"type": "Selector", "all": ["A", "B"], "now": "A"},
                                    "A": {"type": "Socks5"}, "B": {"type": "Socks5"}}}
        with self.assertRaisesRegex(ControlError, "selection-not-confirmed"):
            select(Client(), "Entry", "B")

    def test_target_specific_status_failure_beats_generic_alive_and_hides_url(self):
        target = "https://example.com/?token=DO-NOT-DISCLOSE"
        class Client:
            def request(self, *args, **kwargs):
                return {"proxies": {
                    "Auto": {"type": "URLTest", "all": ["A"], "now": "A", "testUrl": target},
                    "A": {"type": "Socks5", "alive": True, "history": [{"delay": 1}],
                          "extra": {target: {"alive": False, "history": [{"delay": 0}]}}}}}
        rows = proxies(Client())
        self.assertEqual(rows["Auto"]["probe_state"], "all-observed-failed")
        self.assertNotIn("DO-NOT-DISCLOSE", json.dumps(rows))

    def test_malformed_or_partial_probe_evidence_remains_unknown(self):
        rows = self.rows(history=[{"delay": 0}], alive=False)
        rows["Auto"]["_test_url"] = "https://example.com/204"
        rows["A"]["_probe_states"] = {"https://example.com/204": {"alive": False, "history": [{"delay": 0}]}}
        rows["B"]["_probe_states"] = {"https://example.com/204": "invalid"}
        self.assertEqual(health.annotate(rows)["Auto"]["probe_state"], "unknown")
        self.assertFalse(health.observed([None]))
        self.assertFalse(health.observed([{"delay": True}]))


class HealthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.yaml"
        self.original = '''# host settings stay byte-identical
listeners: [{name: local, type: mixed, listen: 127.0.0.1, port: 17890}]
secret: fixture-private
proxy-providers:
  Source: {type: file, path: ./providers/nodes.yaml, health-check: {enable: true, url: https://example.com/204, interval: 600}}
proxy-groups:
  - {name: Auto, type: url-test, use: [Source], filter: stable, url: https://example.com/204, interval: 300}
  - {name: Backup, type: fallback, use: [Source], url: https://example.com/204, interval: 300}
  - {name: Entry, type: select, proxies: [Auto, Backup]}
rules: ["MATCH,Entry"]
'''
        self.config.write_bytes(self.original.encode())
        self.root.chmod(0o700)
        self.config.chmod(0o600)
        if sys.platform == "win32":
            p = patch.dict(health.read_config.__globals__, {"private": lambda p, directory=False: Path(p)})
            p.start(); self.addCleanup(p.stop)
            p = patch.object(tx, "private", lambda p, directory=False: Path(p))
            p.start(); self.addCleanup(p.stop)
            p = patch.object(tx.files, "atomic_bytes", lambda p, b: Path(p).write_bytes(b))
            p.start(); self.addCleanup(p.stop)

    def test_read_only_preset_override_preservation_and_idempotence(self):
        old, new, result = health.health_candidate(self.config, "group", "Auto")
        self.assertEqual(old, new)
        self.assertEqual(result["state"], "unchanged")
        old, new, result = health.health_candidate(self.config, "group", "Auto", {"preset": "resilient", "interval": 90})
        data = yaml.safe_load(new)
        group = data["proxy-groups"][0]
        self.assertEqual(group["interval"], 90)
        self.assertEqual(group["tolerance"], 50)
        self.assertFalse(group["lazy"])
        self.assertEqual(group["expected-status"], "204")
        self.assertEqual(group["filter"], "stable")
        self.assertEqual(group["use"], ["Source"])
        self.assertEqual(data["rules"], ["MATCH,Entry"])
        self.assertIn('# host settings stay byte-identical\nlisteners:', new)
        self.assertEqual(result["provider_settings"]["Source"]["interval"], 600)
        self.assertEqual(self.config.read_bytes(), self.original.encode())
        self.config.write_bytes(new.encode())
        self.assertEqual(health.health_candidate(self.config, "group", "Auto", {"preset": "resilient", "interval": 90})[2]["state"], "unchanged")

    def test_provider_scope_shared_impact_and_status_ranges(self):
        _, new, result = health.health_candidate(self.config, "provider", "Source", {"preset": "resilient", "expected-status": "200/204/400-405"})
        data = yaml.safe_load(new)
        self.assertEqual(data["proxy-groups"], yaml.safe_load(self.original)["proxy-groups"])
        self.assertTrue(data["proxy-providers"]["Source"]["health-check"]["enable"])
        self.assertEqual(result["affected_groups"], ["Auto", "Backup"])

    def test_invalid_options_rejected_without_edit(self):
        for scope, name, options in [
            ("group", "Entry", {"preset": "resilient"}), ("group", "Auto", {"interval": 0}),
            ("group", "Auto", {"timeout": -1}), ("group", "Auto", {"tolerance": 65536}),
            ("group", "Backup", {"tolerance": 50}), ("provider", "Source", {"tolerance": 50}),
            ("group", "Auto", {"url": "https://example.com/?token=private"}),
            ("group", "Auto", {"url": "https://127.0.0.1/204"}),
            ("group", "Auto", {"expected-status": "405-200"}), ("group", "Auto", {"expected-status": "*"}),
            ("group", "Auto", {"lazy": 1}), ("group", "Auto", {"interval": True})]:
            with self.subTest(options=options, scope=scope, name=name):
                with self.assertRaises(ControlError):
                    health.health_candidate(self.config, scope, name, options)
        self.assertEqual(self.config.read_bytes(), self.original.encode())

    def test_import_overwrite_summary_hides_sensitive_urls(self):
        before = yaml.safe_load(self.original)
        before["proxy-groups"][0]["url"] = "https://example.com/?token=DO-NOT-DISCLOSE"
        after = yaml.safe_load(self.original)
        summary = health.probe_overwrites(before, after)
        self.assertEqual(summary[0]["name"], "Auto")
        self.assertNotIn("DO-NOT-DISCLOSE", json.dumps(summary))

    def test_transaction_core_failure_and_config_drift(self):
        old, new, _ = health.health_candidate(self.config, "group", "Auto", {"preset": "resilient"})
        with patch.object(tx, "find_core", return_value="fixture"), patch.object(tx.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ControlError, "validation-failed"):
                tx.apply_policy(self.config, old, new, str(self.root))
        self.assertEqual(self.config.read_bytes(), old.encode())
        self.config.write_bytes((old + "# concurrent\n").encode())
        with patch.object(tx, "validate_candidate"):
            with self.assertRaisesRegex(ControlError, "config-changed"):
                tx.apply_policy(self.config, old, new, str(self.root))
        self.assertEqual(list(self.root.glob("*.before-policy-*")), [])

    def test_console_parser_handles_quoted_names_and_never_accepts_apply(self):
        scope, name, options = health.parse_console('group "Shared Auto" --preset resilient --lazy false')
        self.assertEqual((scope, name), ("group", "Shared Auto"))
        self.assertEqual(options["lazy"], "false")
        with self.assertRaises(ControlError):
            health.parse_console('group Auto --apply')

    @unittest.skipIf(sys.platform == "win32", "Linux locking/ownership")
    def test_cli_read_preview_apply_and_option_boundaries(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}):
            base = ["health-check", "group", "Auto", "--config", str(self.config), "--home-dir", str(self.root), "--json"]
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(controller.main(base), 0)
            self.assertEqual(json.loads(output.getvalue())["state"], "unchanged")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                controller.main(base + ["--preset", "resilient", "--interval", "90"])
            self.assertEqual(json.loads(output.getvalue())["after"]["interval"], 90)
            self.assertEqual(self.config.read_bytes(), self.original.encode())
            with patch.object(tx, "validate_candidate"), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(controller.main(base + ["--preset", "resilient", "--apply"]), 0)
            self.assertEqual(yaml.safe_load(self.config.read_bytes())["proxy-groups"][0]["interval"], 120)
            with self.assertRaisesRegex(ControlError, "probe-options-require-health-check"):
                controller.main(["groups", "--interval", "90"])

    @unittest.skipIf(sys.platform == "win32", "Linux locking/ownership")
    def test_service_preview_save_receipt_and_empty_journal(self):
        with patch.dict(os.environ, {"XDG_DATA_HOME": str(self.root / "data")}):
            service = ConsoleService(self.config, str(self.root))
            self.assertEqual(service.health_check("group", "Auto", {"preset": "resilient"})["state"], "preview")
            with patch.object(tx, "validate_candidate"):
                saved = service.health_check(apply=True)
            self.assertEqual(saved["state"], "restart-required")
            self.assertEqual(Path(saved["backup"]).read_bytes(), self.original.encode())
            with self.assertRaisesRegex(ControlError, "preview-required"):
                service.health_check(apply=True)
            with patch("scripts.controller_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0, stdout=b"")) as run:
                value = service.journal(since="2026-10-10 21:09", until="2026-10-10 21:14")
            self.assertEqual(value["state"], "no-records-in-window")
            self.assertIn("2026-10-10 21:09", run.call_args[0][0])
            with patch("scripts.controller_service.subprocess.run", return_value=subprocess.CompletedProcess([], 1, stdout=b"")):
                with self.assertRaisesRegex(ControlError, "journal-unavailable"):
                    service.journal()
