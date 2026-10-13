"""Offline dependency preflight, clean kits and provenance regression checks."""
import hashlib
import io
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile

from scripts.release import build_release, build_offline_bundle, verify_offline_bundle
from scripts.release import verify_artifact_install

if sys.platform == "linux":
    from mihomoctl import installation
    from test_v1_installation import InstallationTestBase, build_wheel, write_source


@unittest.skipUnless(sys.platform == "linux", "Linux installation engine")
class OfflineBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.source = write_source(self.base / "source")
        self.artifacts = self.base / "artifacts"
        self.artifacts.mkdir()
        self.wheelhouse = self.base / "wheelhouse"
        self.wheelhouse.mkdir()
        self.dependency = build_wheel(self.wheelhouse, name="pyyaml", version="6.0.3", requires=(),
                                      files={"yaml/__init__.py": b"__version__ = '6.0.3'\n"})
        self.lock = "PyYAML==6.0.3 --hash=sha256:" + build_offline_bundle.digest(self.dependency) + "\n"
        (self.source / "requirements-lock.txt").write_text(self.lock)
        self.manifest = installation.load_manifest(self.source)
        self.manifest["inventory"]["files"].append("requirements-lock.txt")
        (self.source / "release-manifest.json").write_text(json.dumps(self.manifest))
        runtime = {name: (self.source / name).read_bytes() for name in self.manifest["inventory"]["runtime_files"]}
        build_wheel(self.artifacts, files=runtime)
        self.archive_source()
        self.target = "ubuntu22.04-x86_64-py310"

    def archive_source(self):
        with zipfile.ZipFile(self.artifacts / "mihomoctl-1.0.0.zip", "w") as archive:
            for name in self.manifest["inventory"]["files"]:
                archive.write(self.source / name, "mihomoctl-1.0.0/" + name)
        with tarfile.open(self.artifacts / "mihomoctl-1.0.0.tar.gz", "w:gz") as archive:
            for name in self.manifest["inventory"]["files"]:
                archive.add(self.source / name, arcname="mihomoctl-1.0.0/" + name)
        hashes = {path.name: build_offline_bundle.digest(path) for path in self.artifacts.iterdir()
                  if path.name.endswith((".tar.gz", ".zip", ".whl"))}
        (self.artifacts / "SHA256SUMS").write_text("".join(hashes[n] + "  " + n + "\n" for n in sorted(hashes)))
        receipt = {"version": "1.0.0", "commit": "a" * 40, "source": "git-commit",
                   "publishable": True, "source_epoch": 0, "sha256": hashes}
        (self.artifacts / "build-receipt.json").write_text(json.dumps(receipt))

    def build(self, output=None):
        return build_offline_bundle.build(self.artifacts, self.wheelhouse, self.target, output or self.base / "kits")

    def test_complete_kit_checksums_and_dependency_provenance(self):
        result = self.build()
        kit = self.base / "kits" / result["file"]
        manifest, payload = verify_offline_bundle.load_bundle(kit, self.target)
        self.assertEqual(manifest["commit"], "a" * 40)
        self.assertEqual(manifest["dependencies"][0]["sha256"], build_offline_bundle.digest(self.dependency))
        self.assertEqual(payload["wheelhouse/" + self.dependency.name], self.dependency.read_bytes())
        self.assertFalse(any("__pycache__" in name or name.endswith(".pyc") for name in payload))
        with self.assertRaisesRegex(ValueError, "already-exists"):
            self.build()

    def test_reproducible_kit(self):
        first = self.build(self.base / "first")
        second = self.build(self.base / "second")
        self.assertEqual(first["sha256"], second["sha256"])

    def test_acceptance_unpack_is_private_under_sudo_group_writable_umask(self):
        archive = self.base / "acceptance.tar.gz"
        with tarfile.open(archive, "w:gz") as package:
            for name in (".github/workflows/test.yml", "scripts/bootstrap.py"):
                member = tarfile.TarInfo("mihomoctl-1.0.0/" + name)
                package.addfile(member, io.BytesIO(b""))
        previous = os.umask(0o002)
        try:
            destination = self.base / "unpacked"
            verify_artifact_install.unpack(archive, destination, "mihomoctl-1.0.0")
            self.assertTrue(all(not path.stat().st_mode & 0o022 for path in [destination, *destination.rglob("*")]))
            self.assertEqual(os.umask(0o002), 0o002)
        finally:
            os.umask(previous)

    def test_existing_or_linked_checksum_is_never_overwritten(self):
        output = self.base / "kits"
        output.mkdir()
        sidecar = output / ("mihomoctl-1.0.0-offline-" + self.target + ".tar.gz.sha256")
        outside = self.base / "untouched"
        sidecar.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "already-exists"):
            self.build()
        self.assertTrue(sidecar.is_symlink())
        self.assertFalse(outside.exists())

    def test_missing_or_wrong_platform_wheel_refused(self):
        self.dependency.unlink()
        for tag in (("cp312", "cp312", "manylinux_2_17_x86_64"), ("cp310", "cp310", "win_amd64")):
            wrong = build_wheel(self.wheelhouse, name="pyyaml", version="6.0.3", requires=(), tag=tag,
                                files={"yaml/__init__.py": b""})
            with self.subTest(tag=tag), self.assertRaisesRegex(installation.InstallationError, "dependency-wheel-missing"):
                self.build()
            wrong.unlink()
        with self.assertRaisesRegex(installation.InstallationError, "dependency-wheel-missing"):
            self.build()

    def test_valid_but_unpinned_dependency_refused(self):
        # A structurally valid wheel whose bytes differ from the reviewed lock.
        self.dependency.unlink()
        build_wheel(self.wheelhouse, name="pyyaml", version="6.0.3", requires=(),
                    files={"yaml/__init__.py": b"__version__ = '6.0.3'\n# changed\n"})
        with self.assertRaisesRegex(ValueError, "dependency-lock-digest-mismatch"):
            self.build()

    def test_missing_and_tampered_outer_checksums_refused(self):
        result = self.build()
        kit = self.base / "kits" / result["file"]
        sidecar = kit.with_name(kit.name + ".sha256")
        for body in ("", "0" * 64 + "  " + kit.name + "\n"):
            sidecar.write_text(body)
            with self.assertRaisesRegex(ValueError, "checksum"):
                verify_offline_bundle.load_bundle(kit, self.target)
        sidecar.unlink()
        with self.assertRaisesRegex(ValueError, "checksum"):
            verify_offline_bundle.load_bundle(kit, self.target)

    def test_inner_checksum_cannot_be_bypassed_by_rehashing_outer_archive(self):
        result = self.build()
        kit = self.base / "kits" / result["file"]
        with tarfile.open(kit, "r:gz") as archive:
            members = [(entry.name, archive.extractfile(entry).read()) for entry in archive]
        with tarfile.open(kit, "w:gz") as archive:
            for name, body in members:
                if name.endswith("/README.txt"):
                    body += b"changed"
                entry = tarfile.TarInfo(name)
                entry.size = len(body)
                archive.addfile(entry, io.BytesIO(body))
        kit.with_name(kit.name + ".sha256").write_text(build_offline_bundle.digest(kit) + "  " + kit.name + "\n")
        with self.assertRaisesRegex(ValueError, "internal-checksum"):
            verify_offline_bundle.load_bundle(kit, self.target)

    def test_source_bytecode_and_unreviewed_payload_refused(self):
        for name in ("mihomoctl/__pycache__/x.cpython-311.pyc", "extra.py"):
            with zipfile.ZipFile(self.artifacts / "mihomoctl-1.0.0.zip", "a") as archive:
                archive.writestr("mihomoctl-1.0.0/" + name, b"extra")
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "bytecode|inventory"):
                build_release.verify_source_inventory(self.artifacts / "mihomoctl-1.0.0.zip", self.manifest)
            self.archive_source()


if sys.platform == "linux":
    class PreflightTests(InstallationTestBase):
        def test_all_source_markers_missing_duplicate_or_wrong_fail_before_writes(self):
            for name, marker in (("mihomoctl/__init__.py", "__version__"), ("pyproject.toml", "version")):
                path = self.source / name
                original = path.read_text()
                assignment = next(line for line in original.splitlines() if re.match(r"^" + marker + r"\s*=", line))
                for text in (original.replace(marker, "removed_marker", 1),
                             original.replace("1.0.0", "0.9.3"),
                             original.replace(assignment, assignment + "\n" + assignment, 1)):
                    path.write_text(text)
                    before = self.snapshot_home()
                    with self.subTest(name=name, text=text), self.assertRaises(installation.InstallationError):
                        self.install(dry_run=True)
                    self.assertEqual(before, self.snapshot_home())
                    self.assertFalse(self.paths.install_root.exists())
                path.write_text(original)

        def isolated_python(self, version=None):
            venv = self.base / "python"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True,
                           capture_output=True, timeout=60)
            if version:
                package = venv / "lib" / ("python%d.%d" % sys.version_info[:2]) / "site-packages"
                wheel = build_wheel(self.base, name="pyyaml", version=version, requires=(),
                                    files={"yaml/__init__.py": ("__version__ = '%s'\n" % version).encode()})
                installation.unpack_wheel(wheel, package)
            return venv / "bin/python"

        def test_importable_541_without_wheelhouse_fails_dry_run_and_install(self):
            python = self.isolated_python("5.4.1")
            for dry_run in (True, False):
                before = self.snapshot_home()
                with self.subTest(dry_run=dry_run), self.assertRaisesRegex(
                        installation.InstallationError, "dependency-version-unsatisfied"):
                    self.install(python=python, wheelhouse=None, dry_run=dry_run)
                self.assertEqual(before, self.snapshot_home())
                self.assertFalse(self.paths.install_root.exists())

        def test_missing_dependency_without_wheelhouse_is_rejected(self):
            python = self.isolated_python()
            with self.assertRaisesRegex(installation.InstallationError, "dependency-missing"):
                self.install(python=python, wheelhouse=None, dry_run=True)
            self.assertFalse(self.paths.install_root.exists())

        def test_wheel_install_without_wheelhouse_uses_qualified_interpreter_dependency(self):
            from test_v1_installation import WheelInstallTests
            python = self.isolated_python("6.0.3")
            source = WheelInstallTests.wheel_source(self)
            self.assertTrue(self.install(source=source, python=python, wheelhouse=None, dry_run=True)["dry_run"])
            self.assertEqual(self.install(source=source, python=python, wheelhouse=None)["version"], "1.0.0")

        def test_wheel_install_without_wheelhouse_rejects_importable_old_dependency(self):
            from test_v1_installation import WheelInstallTests
            python = self.isolated_python("5.4.1")
            source = WheelInstallTests.wheel_source(self)
            for dry_run in (True, False):
                before = self.snapshot_home()
                with self.subTest(dry_run=dry_run), self.assertRaisesRegex(
                        installation.InstallationError, "dependency-version-unsatisfied"):
                    self.install(source=source, python=python, wheelhouse=None, dry_run=dry_run)
                self.assertEqual(before, self.snapshot_home())
                self.assertFalse(self.paths.install_root.exists())

        def test_dependency_corruption_is_rejected_in_preflight(self):
            for wheel in self.wheelhouse.glob("*.whl"):
                wheel.unlink()
            build_wheel(self.wheelhouse, name="pyyaml", version="6.0.3", requires=(),
                        files={"yaml/__init__.py": b"__version__ = '6.0.3'\n"},
                        corrupt=("yaml/__init__.py", b"changed"))
            for dry_run in (True, False):
                before = self.snapshot_home()
                with self.subTest(dry_run=dry_run), self.assertRaisesRegex(
                        installation.InstallationError, "wheel-record-digest-mismatch"):
                    self.install(dry_run=dry_run)
                self.assertEqual(before, self.snapshot_home())
                self.assertFalse(self.paths.install_root.exists())

        def test_mismatched_internal_wheel_tags_are_rejected_before_writes(self):
            for wheel in self.wheelhouse.glob("*.whl"):
                wheel.unlink()
            build_wheel(self.wheelhouse, name="pyyaml", version="6.0.3", requires=(),
                        files={"yaml/__init__.py": b"__version__ = '6.0.3'\n"},
                        wheel_tag=("cp312", "cp312", "win_amd64"))
            for dry_run in (True, False):
                before = self.snapshot_home()
                with self.subTest(dry_run=dry_run), self.assertRaisesRegex(
                        installation.InstallationError, "wheel-tags-disagree-with-filename"):
                    self.install(dry_run=dry_run)
                self.assertEqual(before, self.snapshot_home())
                self.assertFalse(self.paths.install_root.exists())

        def test_duplicate_manifest_version_is_rejected(self):
            manifest = self.source / "release-manifest.json"
            manifest.write_text(manifest.read_text().replace('"version": "1.0.0"',
                                '"version": "1.0.0", "version": "1.0.0"', 1))
            with self.assertRaisesRegex(installation.InstallationError, "release-manifest-unreadable"):
                self.install(dry_run=True)
            self.assertFalse(self.paths.install_root.exists())

        def test_qualified_existing_dependency_and_bundle_override(self):
            python = self.isolated_python("6.0.3")
            self.assertTrue(self.install(python=python, wheelhouse=None, dry_run=True)["dry_run"])
            self.assertTrue(self.install(python=python, dry_run=True)["dry_run"])

        def test_matching_wheels_override_old_systemlike_dependency(self):
            python = self.isolated_python("5.4.1")
            installed = self.install(python=python)
            self.assertEqual(installed["version"], "1.0.0")
            probe = subprocess.run([str(python), "-I", "-c", "import yaml; print(yaml.__version__)"],
                                   capture_output=True, text=True, check=True)
            self.assertEqual(probe.stdout.strip(), "5.4.1")

        def test_target_wheel_compatibility_is_independent_of_bootstrap_python(self):
            target = build_offline_bundle.target_environment("ubuntu24.04-x86_64-py312")
            wheel = {"py": "cp312", "abi": "cp312", "plat": "manylinux_2_39_x86_64"}
            self.assertTrue(installation.wheel_compatible_here(wheel, target))
            older = build_offline_bundle.target_environment("ubuntu22.04-x86_64-py310")
            self.assertFalse(installation.wheel_compatible_here(wheel, older))
            wheel.update(py="cp310", abi="cp310")
            self.assertFalse(installation.wheel_compatible_here(wheel, older))


if __name__ == "__main__":
    unittest.main()
