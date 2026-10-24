"""Release inventory and compressed-artifact disclosure regression checks."""
import contextlib
import importlib
import io
import hashlib
import json
import os
from pathlib import Path
import pkgutil
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts.release import build_release, verify_release
from scripts.release.portable_policy import BASELINE
from scripts.ci import secret_scan


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
            self.save(self.report_path(ubuntu, 'release-acquisition'), {
                'commit': self.commit, 'source_dirty': False, 'success': True,
                'network_isolated': True, 'tests': 26, 'skipped': 0, 'failures': 0, 'errors': 0,
                'suites': {'test_v1_release.py': 14, 'test_v1_release_fetch.py': 12}})
            self.save(self.report_path(ubuntu, "artifact-install"), {
                "commit": self.commit, "publishable_acceptance": True, "success": True,
                "tests": 4, "skipped": 0, "artifact_sha256": hashes,
                "previous_upgrade": {"result": "PASS", "previous_version": "1.0.3", "version": "1.0.0",
                                     "no_history": True, "protected_files_unchanged": True}})
            target = "ubuntu" + ubuntu + "-x86_64-py" + ("310" if ubuntu == "22.04" else "312")
            payload = {"release/" + name: (self.artifacts / name).read_bytes()
                       for name in (*hashes, "SHA256SUMS", "build-receipt.json")}
            payload["README.txt"] = b"Fixture kit; not executable."
            manifest = {"format": 1, "version": "1.0.0", "commit": self.commit,
                        "target": target, "source": "git-commit", "publishable": True,
                        "dependencies": [], "files": {name: hashlib.sha256(body).hexdigest()
                                                        for name, body in payload.items()}}
            payload["bundle-manifest.json"] = json.dumps(manifest).encode()
            payload["SHA256SUMS"] = "".join(hashlib.sha256(body).hexdigest() + "  " + name + "\n"
                                              for name, body in sorted(payload.items())).encode()
            root = "mihomoctl-1.0.0-offline-" + target
            kit = self.artifacts / (root + ".tar.gz")
            with tarfile.open(kit, "w:gz") as archive:
                for name, body in payload.items():
                    info = tarfile.TarInfo(root + "/" + name)
                    info.size = len(body)
                    archive.addfile(info, io.BytesIO(body))
            digest = hashlib.sha256(kit.read_bytes()).hexdigest()
            kit.with_name(kit.name + ".sha256").write_text(digest + "  " + kit.name + "\n", encoding="utf-8")
            self.save(self.report_path(ubuntu, "offline-bundle-install"), {
                "commit": self.commit, "version": "1.0.0", "target": target, "source_dirty": False,
                "bundle_file": kit.name, "bundle_sha256": digest,
                "publishable_acceptance": True, "network_isolated": True,
                "success": True, "tests": 3, "skipped": 0, "errors": 0, "failures": 0})
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
        result = self.verify()
        self.assertTrue(result["verified"])
        self.assertEqual(len([name for name in result["assets"] if "-offline-" in name]), 4)

    def test_acquisition_requires_exact_commit_isolation_and_both_suites(self):
        path = self.report_path('24.04', 'release-acquisition')
        original = json.loads(path.read_text())
        for changes in ({'commit': 'b' * 40}, {'network_isolated': False}, {'skipped': 1}, {'suites': {}}):
            self.save(path, dict(original, **changes))
            with self.assertRaisesRegex(verify_release.GateError, 'release-acquisition'):
                self.verify()

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
                        {"tests": 2}, {"success": False}, {"previous_upgrade": {}}):
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
        with self.assertRaisesRegex(verify_release.GateError, "not-installed|offline-bundle-release-assets-differ"):
            self.verify()

    def test_worktree_build_cannot_be_published(self):
        path = self.artifacts / "build-receipt.json"
        receipt = json.loads(path.read_text())
        receipt.update(source="worktree", publishable=False)
        self.save(path, receipt)
        with self.assertRaises(verify_release.GateError):
            self.verify()

    def test_offline_kit_and_isolated_acceptance_are_mandatory(self):
        path = self.report_path("22.04", "offline-bundle-install")
        original = json.loads(path.read_text())
        for changes in ({"network_isolated": False}, {"bundle_sha256": "e" * 64},
                        {"commit": "b" * 40}, {"skipped": 1}, {"success": False}):
            self.save(path, dict(original, **changes))
            with self.subTest(changes=changes), self.assertRaises(verify_release.GateError):
                self.verify()
        self.save(path, original)
        kit = next(self.artifacts.glob("*-offline-ubuntu22*.tar.gz"))
        sidecar = kit.with_name(kit.name + ".sha256")
        sidecar.unlink()
        with self.assertRaisesRegex(verify_release.GateError, "offline-bundle-invalid"):
            self.verify()

    def test_portable_gate_requires_two_distinct_users_and_matching_offline_evidence(self):
        archive = self.artifacts / 'mihomoctl-1.0.0-portable-linux-x86_64.tar.gz'
        archive.write_bytes(b'fixture archive identity')
        checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
        archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
        for ubuntu in ('22.04', '24.04'):
            self.save(self.report_path(ubuntu, 'portable-acceptance'), {
                'success': True, 'network_isolated': True, 'real_uids': True,
                'publishable': True, 'os': 'ubuntu', 'ubuntu': ubuntu,
                'commit': self.commit, 'version': '1.0.0', 'bundle_sha256': checksum,
                'bundle_bytes': archive.stat().st_size, 'expanded_bytes': 100,
                'baseline': BASELINE,
                'users': [{'uid': uid, 'controller_port': 30000 + uid,
                           'installed_bytes': 100,
                           'previous_upgrade': {'success': True, 'previous_version': BASELINE['version'],
                               'previous_commit': BASELINE['commit'], 'previous_bundle_sha256': BASELINE['sha256'],
                               'version': '1.0.0', 'core_identity_unchanged': True, 'core_digest_unchanged': True,
                               'authentication_preserved': True, 'selection_preserved': True,
                               'protected_files_unchanged': True, 'no_history': True},
                           'core_sha256': 'c' * 64, 'no_history': True,
                           'authentication_rejected': True, 'system_python_absent_from_path': True,
                           'ssh_transport': uid == 1002, 'active_ui_update_refused': True,
                           'terminal_unicode_resize_search': True,
                           'extraction_umask_0002': True,
                           'ui_rss_kib': 40000} for uid in (1001, 1002)]})
        def verify():
            return verify_release.verify(self.artifacts, self.evidence, self.commit,
                                         portable_artifacts=self.artifacts)
        self.assertIn(archive.name, verify()['assets'])
        path = self.report_path('24.04', 'portable-acceptance')
        original = json.loads(path.read_text())
        invalid = json.loads(json.dumps(original))
        invalid['users'][0]['previous_upgrade']['core_identity_unchanged'] = False
        self.save(path, invalid)
        with self.assertRaisesRegex(verify_release.GateError, 'previous-upgrade'):
            verify()
        invalid = dict(original, expanded_bytes=160000001)
        self.save(path, invalid)
        with self.assertRaisesRegex(verify_release.GateError, 'size-evidence'):
            verify()
        for key, value in (('bundle_sha256', 'd' * 64), ('network_isolated', False)):
            self.save(path, dict(original, **{key: value}))
            with self.assertRaisesRegex(verify_release.GateError, 'portable-acceptance'):
                verify()
        repeated = json.loads(json.dumps(original))
        repeated['users'][1]['uid'] = repeated['users'][0]['uid']
        self.save(path, repeated)
        with self.assertRaisesRegex(verify_release.GateError, 'portable-acceptance'):
            verify()


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
    @unittest.skipUnless(sys.platform == "linux", "Linux installation inventory")
    def test_legacy_payload_references_and_reviewed_source_inventory_cover_each_other(self):
        from mihomoctl import installation
        root = Path(__file__).resolve().parents[1]
        manifest = installation.load_manifest(root)
        installation.verify_inventory(root, manifest)
        self.assertTrue((root / "legacy/v0.9/scripts/paseo.py").is_file())
        self.assertTrue(all(name.startswith('mihomoctl/') for name in manifest['inventory']['runtime_files']))

    @unittest.skipUnless(sys.platform == "linux", "Linux package trust permissions")
    def test_real_builder_normalizes_git_archive_modes_under_group_writable_umask(self):
        root = Path(__file__).resolve().parents[1]
        manifest = json.loads((root / "release-manifest.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory(prefix="mihomoctl-builder-test-") as folder:
            repository = Path(folder) / "repository"
            repository.mkdir(mode=0o700)
            for name in build_release.reviewed_files(manifest):
                target = repository / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root / name, target)
                target.chmod(0o775 if name.endswith((".sh", ".bash")) else 0o664)
            def git(*args):
                return subprocess.check_output(["git", "-C", str(repository), *args],
                                               stderr=subprocess.PIPE)
            git("init", "--quiet")
            git("config", "user.name", "Build fixture")
            git("config", "user.email", "build@example.invalid")
            git("config", "tar.umask", "0002")
            git("add", ".")
            git("commit", "--quiet", "-m", "Reviewed build fixture")
            archive = git("archive", "--format=tar", "HEAD")
            with tarfile.open(fileobj=io.BytesIO(archive)) as package:
                self.assertTrue(any(entry.mode & 0o022 for entry in package.getmembers()))
            original = {name: ((repository / name).stat().st_mode & 0o777,
                               hashlib.sha256((repository / name).read_bytes()).hexdigest())
                        for name in manifest["inventory"]["files"]}
            for mode in ("git-commit", "worktree"):
                output = Path(folder) / mode
                command = [sys.executable, "-c",
                           "import os,runpy,sys; os.umask(0o002); "
                           "path=sys.argv.pop(1); runpy.run_path(path,run_name='__main__')",
                           str(repository / "scripts" / "release" / "build_release.py"), "--output", str(output)]
                if mode == "worktree":
                    command.append("--worktree")
                completed = subprocess.run(command, text=True, capture_output=True, timeout=180,
                                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
                self.assertEqual(completed.returncode, 0, completed.stderr[-3000:])
                wheels = list(output.glob("mihomoctl-*.whl"))
                self.assertEqual(len(wheels), 1)
                build_release.verify_wheel_inventory(wheels[0], manifest)
                receipt = json.loads((output / "build-receipt.json").read_text())
                self.assertEqual(receipt["commit"], git("rev-parse", "HEAD").decode().strip())
                self.assertEqual(receipt["source"], mode)
                self.assertEqual(receipt["publishable"], mode == "git-commit")
                self.assertTrue(all(not (p.stat().st_mode & 0o022) for p in output.rglob("*")))
            for name, identity in original.items():
                with self.subTest(name=name):
                    self.assertEqual((repository / name).stat().st_mode & 0o777, identity[0])
                    self.assertEqual(hashlib.sha256((repository / name).read_bytes()).hexdigest(), identity[1])
            # Exercise the real builder's version gate, before wheel creation.
            for name, marker in (("mihomoctl/__init__.py", "__version__"),):
                path = repository / name
                previous = path.read_bytes()
                invalid = re.sub(r"(?m)^" + marker + r"\s*=.*$", marker + '="0.9.3"', previous.decode())
                path.write_text(invalid, encoding="utf-8")
                output = Path(folder) / ("bad-" + name.replace("/", "-"))
                completed = subprocess.run([sys.executable, repository / "scripts/release/build_release.py",
                                            "--worktree", "--output", output],
                                           text=True, capture_output=True, timeout=60)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("release-version-mismatch", completed.stderr)
                self.assertFalse(list(output.glob("*.whl")))
                path.write_bytes(previous)

    def test_release_builder_refuses_directory_prefix_and_path_escape(self):
        for inventory in ({"roots": ["scripts"], "files": ["scripts/a.py"], "runtime_files": ["scripts/a.py"]},
                          {"roots": [], "files": ["../outside.py"], "runtime_files": ["../outside.py"]},
                          {"roots": [], "files": ["scripts/a.pyc"], "runtime_files": ["scripts/a.pyc"]}):
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

    def test_wheel_cannot_hide_unreviewed_files_in_metadata(self):
        manifest = {"version": "1.0.0", "inventory": {"runtime_files": ["mihomoctl/__init__.py"]}}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "mihomoctl-1.0.0-py3-none-any.whl"
            with zipfile.ZipFile(path, "w") as package:
                package.writestr("mihomoctl/__init__.py", "")
                package.writestr("mihomoctl-1.0.0.dist-info/extra.py", "")
            with self.assertRaisesRegex(ValueError, "metadata-inventory"):
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
