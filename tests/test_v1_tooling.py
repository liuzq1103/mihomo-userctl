"""Release inventory and compressed-artifact disclosure regression checks."""
import contextlib
import importlib
import io
import hashlib
import json
from pathlib import Path
import pkgutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import build_release, secret_scan, verify_release


class PublishGateTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.base = Path(self.folder.name)
        self.artifacts = self.base / "artifacts"
        self.evidence = self.base / "evidence"
        self.artifacts.mkdir()
        self.commit = "a" * 40
        hashes = {}
        for name in ("mihomoctl-1.0.0.tar.gz", "mihomoctl-1.0.0.zip",
                     "mihomoctl-1.0.0-py3-none-any.whl"):
            body = name.encode()
            (self.artifacts / name).write_bytes(body)
            hashes[name] = hashlib.sha256(body).hexdigest()
        self.save(self.artifacts / "build-receipt.json", {
            "commit": self.commit, "version": "1.0.0", "publishable": True,
            "source": "git-commit", "sha256": hashes})
        (self.artifacts / "SHA256SUMS").write_text(
            "".join(hashes[n] + "  " + n + "\n" for n in sorted(hashes)), encoding="utf-8")
        for ubuntu in ("22.04", "24.04"):
            self.save(self.report_path(ubuntu, "artifact-install"), {
                "commit": self.commit, "publishable_acceptance": True, "success": True,
                "tests": 3, "skipped": 0, "artifact_sha256": hashes})
            for suite in ("unit", "real-core", "privileged"):
                self.save(self.report_path(ubuntu, suite), {
                    "commit": self.commit, "source_dirty": False, "os": "ubuntu", "ubuntu": ubuntu,
                    "success": True, "tests": 200 if suite == "unit" else 8,
                    "failures": 0, "errors": 0, "skipped": 0, "core_sha256": "c" * 64,
                    "real_uids": True, "systemd": True, "tun": True,
                    "suites": {"test_real_core.py": 3, "test_v1_runtime_real.py": 6, "test_v1_ux.py": 1}})

    def save(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value), encoding="utf-8")

    def report_path(self, ubuntu, suite):
        return self.evidence / ("validation-ubuntu-" + ubuntu) / (suite + ".json")

    def alter_report(self, **values):
        path = self.report_path("24.04", "privileged")
        report = json.loads(path.read_text())
        report.update(values)
        self.save(path, report)

    def verify(self):
        return verify_release.verify(self.artifacts, self.evidence, self.commit)

    def test_matching_artifacts_and_two_platforms_pass(self):
        self.assertTrue(self.verify()["verified"])

    def test_other_commit_or_dirty_source_cannot_satisfy_gate(self):
        for values in ({"commit": "b" * 40}, {"source_dirty": True}):
            with self.subTest(values=values):
                self.alter_report(**dict({"commit": self.commit, "source_dirty": False}, **values))
                with self.assertRaises(verify_release.GateError):
                    self.verify()

    def test_skipped_or_failed_mandatory_acceptance_blocks(self):
        for values in ({"skipped": 1}, {"tests": 0}, {"success": False}, {"errors": 1}):
            with self.subTest(values=values):
                self.alter_report(**dict({"skipped": 0, "tests": 8, "success": True, "errors": 0}, **values))
                with self.assertRaises(verify_release.GateError):
                    self.verify()

    def test_missing_platform_report_blocks(self):
        self.report_path("22.04", "real-core").unlink()
        with self.assertRaises(verify_release.GateError):
            self.verify()

    def test_tampered_asset_blocks_even_with_successful_ci(self):
        (self.artifacts / "mihomoctl-1.0.0.zip").write_bytes(b"different content")
        with self.assertRaises(verify_release.GateError):
            self.verify()

    def test_missing_or_wrong_commit_full_artifact_install_blocks(self):
        path = self.report_path("22.04", "artifact-install")
        original = json.loads(path.read_text())
        for changes in ({"commit": "b" * 40}, {"publishable_acceptance": False},
                        {"tests": 2}, {"success": False}):
            self.save(path, dict(original, **changes))
            with self.subTest(changes=changes), self.assertRaises(verify_release.GateError):
                self.verify()
        path.unlink()
        with self.assertRaises(verify_release.GateError):
            self.verify()

    def test_selected_wheel_must_match_at_least_one_full_install_report(self):
        for ubuntu in ("22.04", "24.04"):
            path = self.report_path(ubuntu, "artifact-install")
            report = json.loads(path.read_text())
            report["artifact_sha256"]["mihomoctl-1.0.0-py3-none-any.whl"] = "d" * 64
            self.save(path, report)
        with self.assertRaisesRegex(verify_release.GateError, "not-installed"):
            self.verify()

    def test_worktree_build_cannot_be_published(self):
        path = self.artifacts / "build-receipt.json"
        receipt = json.loads(path.read_text())
        receipt.update(source="worktree", publishable=False)
        self.save(path, receipt)
        with self.assertRaises(verify_release.GateError):
            self.verify()


@unittest.skipUnless(sys.platform == "linux", "production package targets Linux")
class PackageIntegrityTests(unittest.TestCase):
    def test_every_shipped_core_module_imports_without_running_commands(self):
        import mihomoctl
        with patch("subprocess.run", side_effect=AssertionError("module import ran a command")), \
                patch("subprocess.Popen", side_effect=AssertionError("module import spawned a process")):
            for item in pkgutil.walk_packages(mihomoctl.__path__, "mihomoctl."):
                if item.name != "mihomoctl.__main__":
                    with self.subTest(module=item.name):
                        importlib.import_module(item.name)


class ReleaseInventoryTests(unittest.TestCase):
    def test_release_builder_refuses_directory_prefix_and_path_escape(self):
        for inventory in ({"roots": ["scripts"], "files": ["scripts/a.py"], "runtime_files": ["scripts/a.py"]},
                          {"roots": [], "files": ["../outside.py"], "runtime_files": ["../outside.py"]}):
            with self.subTest(inventory=inventory), self.assertRaises(ValueError):
                build_release.reviewed_files({"inventory": inventory})

    def test_wheel_cannot_add_an_unreviewed_runtime_module(self):
        manifest = {"inventory": {"runtime_files": ["mihomoctl/__init__.py"]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.whl"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr("mihomoctl/__init__.py", "")
                package.writestr("scripts/extra.py", "")
            with self.assertRaisesRegex(ValueError, "runtime-inventory"):
                build_release.verify_wheel_inventory(path, manifest)

    def test_compressed_wheel_contents_are_scanned_without_disclosing_match(self):
        with tempfile.TemporaryDirectory() as folder:
            wheel = Path(folder) / "sample.whl"
            private_value = b"token=" + b"Q" * 30
            with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as package:
                package.writestr("sample/config.txt", private_value)
            with self.assertRaisesRegex(ValueError, "possible-secret") as raised:
                secret_scan.scan_file(wheel)
            self.assertNotIn(private_value.decode(), str(raised.exception))

    def test_active_credentials_are_refused_even_without_a_pattern_match(self):
        with tempfile.TemporaryDirectory() as folder:
            credentials = Path(folder) / "credentials.yaml"
            credentials.write_text("username: fictional\npassword: short\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "active-secret-file"):
                secret_scan.scan_file(credentials)

    def test_scanner_filename_cannot_exempt_payload_in_a_wheel(self):
        with tempfile.TemporaryDirectory() as folder:
            wheel = Path(folder) / "sample.whl"
            with zipfile.ZipFile(wheel, "w") as package:
                package.writestr("untrusted/secret_scan.py", b"token=" + b"R" * 30)
            with self.assertRaisesRegex(ValueError, "possible-secret"):
                secret_scan.scan_file(wheel)

    def test_private_untracked_notes_are_not_release_inputs_but_staged_files_are(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            subprocess.run(["git", "init", "--quiet", root], check=True)
            (root / "README.md").write_text("public documentation\n", encoding="utf-8")
            subprocess.run(["git", "-C", root, "add", "README.md"], check=True)
            note = root / "private-notes.md"
            note.write_bytes(b"token=" + b"Q" * 30)
            with patch.object(secret_scan, "ROOT", root), patch("sys.argv", ["secret_scan.py"]):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(secret_scan.main(), 0)
                subprocess.run(["git", "-C", root, "add", note.name], check=True)
                captured = io.StringIO()
                with contextlib.redirect_stdout(captured):
                    self.assertEqual(secret_scan.main(), 1)
                self.assertNotIn("Q" * 30, captured.getvalue())

    def test_public_documentation_without_credentials_passes(self):
        with tempfile.TemporaryDirectory() as folder:
            document = Path(folder) / "README.md"
            document.write_text("Use HTTP_PROXY and explicit environment profiles.\n", encoding="utf-8")
            secret_scan.scan_file(document)


if __name__ == "__main__":
    unittest.main()
