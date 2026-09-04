"""Isolated custom-rule contract tests; no real Mihomo files or service."""

import contextlib
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts import rules as r


GOOD_CONFIG = """mixed-port: 28443
proxy-groups:
  - name: Proxy
    type: select
    proxies: [DIRECT]
rule-providers:
  custom-direct:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-direct.yaml
  custom-proxy:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-proxy.yaml
  custom-reject:
    type: file
    behavior: classical
    format: yaml
    path: ./rules/custom-reject.yaml
rules:
  - RULE-SET,custom-direct,DIRECT
  - RULE-SET,custom-proxy,Proxy
  - RULE-SET,custom-reject,REJECT
  - MATCH,DIRECT
"""


class RuleTests(unittest.TestCase):
    def config(self, text=GOOD_CONFIG):
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "config.yaml"
        path.write_text(text)
        self.addCleanup(temporary.cleanup)
        return path

    def test_contract_accepts_standard_providers_and_order(self):
        with patch.object(r, "inspect_owned"):
            self.assertFalse(r.parse_config(self.config()))

    def test_missing_fallback_is_warning_only(self):
        with patch.object(r, "inspect_owned"):
            self.assertTrue(r.parse_config(self.config(GOOD_CONFIG.replace("  - MATCH,DIRECT\n", ""))))

    def test_duplicate_provider_unknown_group_and_late_rule_fail(self):
        cases = (
            GOOD_CONFIG.replace("  custom-direct:\n", "  custom-direct:\n  custom-direct:\n", 1),
            GOOD_CONFIG.replace("    type: file\n", "    type: file\n    type: file\n", 1),
            GOOD_CONFIG.replace("path: ./rules/custom-direct.yaml", "path: ./rules/other.yaml"),
            GOOD_CONFIG.replace("RULE-SET,custom-direct,DIRECT", "RULE-SET,custom-direct,Proxy"),
            GOOD_CONFIG.replace("RULE-SET,custom-proxy,Proxy", "RULE-SET,custom-proxy,Missing"),
            GOOD_CONFIG.replace("  - MATCH,DIRECT\n", "  - MATCH,DIRECT\n  - RULE-SET,custom-direct,DIRECT\n"),
        )
        with patch.object(r, "inspect_owned"):
            for text in cases:
                with self.subTest(text=text[-80:]), self.assertRaises(r.RuleError):
                    r.parse_config(self.config(text))

    def test_rule_file_reports_count_hash_and_never_content(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "custom-proxy.yaml"
        secret = "private-domain-should-not-print.example"
        path.write_text("payload:\n  - DOMAIN-SUFFIX," + secret + "\n")
        fake_info = type("Info", (), {"st_size": path.stat().st_size, "st_mtime": 0})()
        with patch.object(r, "inspect_owned", return_value=fake_info):
            result = r.parse_rule_file(path)
        self.assertEqual(result["rules"], 1)
        self.assertNotIn(secret, json.dumps(result))

    def test_unsupported_yaml_fails_closed(self):
        for text in ("rule-providers: {custom-direct: {type: file}}\n",
                     GOOD_CONFIG.replace("  custom-direct:\n", "  custom-direct: &provider\n"),
                     GOOD_CONFIG.replace("    type: file\n", "    <<: *provider\n", 1)):
            path = self.config(text)
            with self.subTest(text=text[:40]), patch.object(r, "inspect_owned"), \
                    self.assertRaises(r.RuleError):
                r.parse_config(path)

    def test_rule_file_anchors_tags_and_flow_values_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "custom-direct.yaml"
            for item in ("&anchor DOMAIN,example.com", "*anchor", "!tag DOMAIN,example.com",
                         "[DOMAIN,example.com]", "{DOMAIN: example.com}"):
                path.write_text("payload:\n  - " + item + "\n")
                fake_info = type("Info", (), {"st_size": path.stat().st_size, "st_mtime": 0})()
                with self.subTest(item=item), patch.object(r, "inspect_owned", return_value=fake_info), \
                        self.assertRaises(r.RuleError) as caught:
                    r.parse_rule_file(path)
                self.assertEqual(caught.exception.code, "rule-file-unsupported-yaml")

    def test_status_json_has_no_rule_content(self):
        files = [{"name": name, "exists": True, "rules": 1, "sha256": "a" * 64,
                  "modified_utc": "1970-01-01T00:00:00+00:00", "mode": "600", "status": "PASS"}
                 for name in r.FILES]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(r.output_status(files, True), 0)
        document = json.loads(output.getvalue())
        self.assertEqual(document["schema"], r.SCHEMA)
        self.assertEqual(document["overall"], "PASS")

    def test_unverified_status_is_not_reported_as_pass(self):
        files = [{"name": "custom-direct.yaml", "exists": True, "rules": None,
                  "sha256": None, "modified_utc": None, "mode": None,
                  "status": "UNVERIFIED", "error": "rule-file-unsupported-yaml"}]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(r.output_status(files, True), 2)
        self.assertEqual(json.loads(output.getvalue())["overall"], "UNVERIFIED")

    def test_owner_and_symlink_checks_fail_closed(self):
        info = type("Info", (), {"st_mode": stat.S_IFREG | 0o600, "st_uid": 2000})()
        with patch.object(Path, "lstat", return_value=info), \
                patch.object(r.os, "getuid", return_value=1000, create=True), \
                self.assertRaises(r.RuleError) as caught:
            r.inspect_owned(Path("/fixture"), 0o600, "rule-file")
        self.assertEqual(caught.exception.code, "rule-file-not-owned-by-current-user")
        link = type("Info", (), {"st_mode": stat.S_IFLNK | 0o777, "st_uid": 1000})()
        with patch.object(Path, "lstat", return_value=link), \
                patch.object(r.os, "getuid", return_value=1000, create=True), \
                self.assertRaises(r.RuleError) as caught:
            r.inspect_owned(Path("/fixture"), 0o600, "rule-file")
        self.assertEqual(caught.exception.code, "rule-file-symlink-not-supported")

    def test_wrong_type_and_wide_mode_fail_closed(self):
        cases = ((stat.S_IFDIR | 0o600, "rule-file-wrong-type"),
                 (stat.S_IFREG | 0o644, "rule-file-mode-must-be-600"))
        for mode, code in cases:
            info = type("Info", (), {"st_mode": mode, "st_uid": 1000})()
            with self.subTest(code=code), patch.object(Path, "lstat", return_value=info), \
                    patch.object(r.os, "getuid", return_value=1000, create=True), \
                    self.assertRaises(r.RuleError) as caught:
                r.inspect_owned(Path("/fixture"), 0o600, "rule-file")
            self.assertEqual(caught.exception.code, code)

    def test_mihomo_failure_is_generic_and_redacted(self):
        secret = "private-value-that-must-not-print"
        failed = subprocess.CompletedProcess([], 1, secret, secret)
        with patch.object(r.subprocess, "run", return_value=failed), \
                self.assertRaises(r.RuleError) as caught:
            r.config_test("mihomo", Path("/home"), Path("/config"))
        self.assertEqual(caught.exception.code, "mihomo-config-test-failed")
        self.assertNotIn(secret, str(caught.exception))

    def test_mihomo_missing_and_timeout_are_unverified(self):
        for failure in (FileNotFoundError("private path"),
                        subprocess.TimeoutExpired(["mihomo"], 60, output="private")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(r.subprocess, "run", side_effect=failure), \
                    self.assertRaises(r.RuleError) as caught:
                r.config_test("mihomo", Path("/home"), Path("/config"))
            self.assertEqual(caught.exception.code, "mihomo-config-test-unverified")

    @unittest.skipUnless(os.name == "posix", "POSIX permission integration")
    def test_status_does_not_modify_files(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / "home"
            rules = home / "rules"
            rules.mkdir(parents=True, mode=0o700)
            for name in r.FILES:
                path = rules / name
                path.write_text("payload:\n  - DOMAIN-SUFFIX,example.com\n")
                path.chmod(0o600)
            before = {path: path.read_bytes() for path in rules.iterdir()}
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(r.main(["status", "--home-dir", str(home), "--json"]), 0)
            self.assertEqual(before, {path: path.read_bytes() for path in rules.iterdir()})

    @unittest.skipUnless(os.name == "posix", "POSIX Mihomo check integration")
    def test_full_check_uses_fake_mihomo_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            home = root / "home"
            rules = home / "rules"
            rules.mkdir(parents=True, mode=0o700)
            private = "private-rule.example"
            for name in r.FILES:
                path = rules / name
                path.write_text("payload:\n  - DOMAIN-SUFFIX," + private + "\n")
                path.chmod(0o600)
            config = root / "config.yaml"
            config.write_text(GOOD_CONFIG)
            config.chmod(0o600)
            mihomo = root / "mihomo"
            mihomo.write_text("#!/bin/sh\nexit 0\n")
            mihomo.chmod(0o700)
            before = {path: path.read_bytes() for path in list(rules.iterdir()) + [config]}
            output = io.StringIO()
            with patch.dict(os.environ, {"MIHOMO_CORE_BIN": str(mihomo)}, clear=False), \
                    contextlib.redirect_stdout(output):
                self.assertEqual(r.main(["check", "--home-dir", str(home),
                                         "--config", str(config)]), 0)
            self.assertNotIn(private, output.getvalue())
            self.assertEqual(before, {path: path.read_bytes() for path in list(rules.iterdir()) + [config]})


if __name__ == "__main__":
    unittest.main()
