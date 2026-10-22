"""V1 installation engine tests (protocol 2).

Covers the installation product contract:
- CLI installation is fully separate from init/core download/start;
- no shell startup file is ever touched; no services are started;
- offline wheelhouse / source-tree / release-archive / wheel installs;
- atomic immutable generation switching, locking, private permissions,
  safe path checks and self-contained backup rollback;
- old (protocol 1) sources are refused before any write;
- default user scope; system scope requires explicit opt-in and root;
- existing Mihomo cores are never adopted or replaced.

Filesystem tests require Linux and run under scripts/ci/v1_ci.py --unit from
the private source copy.  The module imports mihomoctl.locks (fcntl), so
everything is Linux-gated.
"""
import base64
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

try:
    from mihomoctl import installation, locks
    from mihomoctl.errors import MihomoctlError, PermissionScopeError
    from mihomoctl.scope import Scope
    LINUX = sys.platform == "linux"
except ImportError:  # Windows hosts without fcntl: everything is skipped.
    LINUX = False

TEST_PYTHON = Path("/tmp/mihomoctl-v1-test-env/bin/python")
SHELL_DECOYS = (".bashrc", ".zshrc", ".profile", ".bash_profile")
# The repository's own release identity is whatever release-manifest.json says;
# fixture versions below stay literal so a version bump needs no test edit.
REPOSITORY_VERSION = json.loads(
    (ROOT / "release-manifest.json").read_text(encoding="utf-8"))["version"]

FIXTURE_MANIFEST = {
    "format": 2,
    "version": "1.0.0",
    "update_protocol": 2,
    "validation_profile": "installation-v2",
    "requires_python": ">=3.10",
    "console_script": "mihomoctl",
    "entry_point": "mihomoctl.cli:main",
    "dependencies": ["PyYAML>=6.0.1"],
    "packages": ["mihomoctl", "scripts"],
    "inventory": {
        "roots": [],
        "runtime_files": [],
        "files": ["pyproject.toml", "release-manifest.json", "install.sh", "uninstall.sh"],
    },
}

FIXTURE_PYPROJECT = """\
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "mihomoctl"
version = "{version}"
description = "fixture"
requires-python = ">=3.10"

[project.scripts]
mihomoctl = "{entry}"

[tool.setuptools]
packages = ["mihomoctl", "scripts"]
"""

FIXTURE_CLI = """\
import sys


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if args[:1] == ["--version"]:
        import mihomoctl
        print("mihomoctl " + mihomoctl.__version__)
        return 0
    print("fixture-cli-ok")
    return 0
"""


def write_source(root, version="1.0.0", *, entry=installation.ENTRY_POINT,
                 init_version=None, manifest=None):
    """Build a minimal reviewed protocol-2 fixture source tree."""
    root = Path(root)
    (root / "mihomoctl").mkdir(parents=True)
    (root / "mihomoctl" / "__init__.py").write_text(
        '__version__ = "%s"\n' % (init_version or version), encoding="utf-8")
    (root / "install.sh").write_text('# fixture installer entry\n', encoding="utf-8")
    (root / "mihomoctl" / "cli.py").write_text(FIXTURE_CLI, encoding="utf-8")
    (root / "mihomoctl" / "lifecycle").mkdir()
    (root / "mihomoctl" / "lifecycle" / "__init__.py").write_text(
        "# subpackage marker\n", encoding="utf-8")
    (root / "scripts").mkdir()
    (root / "scripts" / "__init__.py").write_text("# scripts package\n", encoding="utf-8")
    (root / "scripts" / "controller.py").write_text(
        "def info():\n    return 'controller-ok'\n", encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "guide.md").write_text("# guide\n", encoding="utf-8")
    manifest_data = json.loads(json.dumps(manifest if manifest is not None else FIXTURE_MANIFEST))
    if manifest is None:
        manifest_data["version"] = version
    (root / "release-manifest.json").write_text(
        json.dumps(manifest_data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        FIXTURE_PYPROJECT.format(version=version, entry=entry), encoding="utf-8")
    manifest_data["inventory"]["files"] = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    manifest_data["inventory"]["runtime_files"] = [f for f in manifest_data["inventory"]["files"] if f.startswith(("mihomoctl/", "scripts/"))]
    (root / "release-manifest.json").write_text(json.dumps(manifest_data) + "\n", encoding="utf8")
    # Reviewed release trees carry explicit modes; never depend on the ambient
    # umask (isolated CI steps inherit a permissive one from the sudo chain).
    for path in (root, *root.rglob("*")):
        path.chmod(0o755 if path.is_dir() else 0o644)
    return root


def old_protocol_source(root):
    root = Path(root)
    root.mkdir(parents=True)
    (root / "release-manifest.json").write_text(json.dumps({
        "format": 1, "version": "0.9.3", "update_protocol": 1,
        "validation_profile": "installation-v1"}) + "\n", encoding="utf-8")
    (root / "install.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    return root


def _record_digest(payload):
    return base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=").decode()


def build_wheel(dest, name="mihomoctl", version="1.0.0", files=None, entry=None,
                requires=("PyYAML>=6.0.1",), requires_python=">=3.10",
                tag=("py3", "none", "any"), wheel_tag=None, corrupt=None, unlisted=None):
    """Construct a wheel with a correct RECORD, or deliberate defects.

    ``corrupt`` rewrites payload bytes after RECORD digests are computed;
    ``unlisted`` adds a member that RECORD never mentions."""
    dest = Path(dest)
    dist = "%s-%s" % (name.replace("-", "_"), version)
    members = {}
    if name.lower() == "mihomoctl":
        members.update(files if files is not None else {
            "mihomoctl/__init__.py": ('__version__ = "%s"\n' % version).encode(),
            "mihomoctl/cli.py": FIXTURE_CLI.encode(),
            "mihomoctl/lifecycle/__init__.py": b"# subpackage marker\n",
            "scripts/__init__.py": b"# scripts package\n",
            "scripts/controller.py": b"def info():\n    return 'controller-ok'\n",
        })
        metadata = ["Metadata-Version: 2.1", "Name: %s" % name, "Version: %s" % version]
        if requires_python:
            metadata.append("Requires-Python: %s" % requires_python)
        metadata += ["Requires-Dist: %s" % r for r in requires]
        members[dist + ".dist-info/METADATA"] = ("\n".join(metadata) + "\n\n").encode()
        members[dist + ".dist-info/entry_points.txt"] = (
            "[console_scripts]\nmihomoctl = %s\n" % (entry or installation.ENTRY_POINT)).encode()
    else:
        members.update(files or {})
        metadata = ["Metadata-Version: 2.1", "Name: %s" % name, "Version: %s" % version]
        if requires_python:
            metadata.append("Requires-Python: %s" % requires_python)
        metadata += ["Requires-Dist: %s" % r for r in requires]
        members[dist + ".dist-info/METADATA"] = ("\n".join(metadata) + "\n\n").encode()
    members[dist + ".dist-info/WHEEL"] = (
        "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: %s\n"
        % "-".join(wheel_tag or tag)).encode()
    record = ["%s,sha256=%s,%d" % (member, _record_digest(payload), len(payload))
              for member, payload in sorted(members.items())]
    # Defects are applied only after the RECORD has been finalized.
    if corrupt:
        members[corrupt[0]] = corrupt[1]
    if unlisted:
        members[unlisted[0]] = unlisted[1]
    members[dist + ".dist-info/RECORD"] = (
        "\n".join(record + [dist + ".dist-info/RECORD,,"]) + "\n").encode()
    path = dest / ("%s-%s-%s-%s-%s.whl" % (name, version, *tag))
    with zipfile.ZipFile(path, "w") as zf:
        for member, payload in sorted(members.items()):
            info = zipfile.ZipInfo(member, date_time=(2026, 1, 1, 0, 0, 0))
            info.external_attr = 0o644 << 16
            zf.writestr(info, payload)
    path.chmod(0o644)
    return path


def fake_pyyaml_wheel(dest, version="6.0.3"):
    return build_wheel(dest, name="PyYAML", version=version, requires=(),
                       requires_python=None,
                       files={"yaml/__init__.py": ("VERSION = '%s'\n" % version).encode()})


def linux_only(cls):
    return unittest.skipUnless(LINUX, "Linux filesystem semantics required")(cls)


# ---------------------------------------------------------------------------
# parsing / pure logic
# ---------------------------------------------------------------------------


@linux_only
class ManifestProtocolTests(unittest.TestCase):
    def test_repository_manifest_is_valid_protocol_2(self):
        manifest = installation.load_manifest(ROOT)
        self.assertEqual(manifest["update_protocol"], installation.PROTOCOL)
        self.assertEqual(manifest["version"], REPOSITORY_VERSION)
        init = (ROOT / "mihomoctl" / "__init__.py").read_text(encoding="utf-8")
        self.assertRegex(init, r"__version__\s*=\s*[\"']" + re.escape(manifest["version"]) + r"[\"']")

    def test_protocol_1_refused_with_guidance(self):
        with tempfile.TemporaryDirectory() as folder:
            root = old_protocol_source(Path(folder) / "old")
            with self.assertRaises(installation.OldProtocolError) as raised:
                installation.load_manifest(root)
            self.assertIn("no files were changed", raised.exception.render())

    def test_unknown_protocol_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_source(Path(folder) / "src")
            manifest = json.loads((root / "release-manifest.json").read_text())
            manifest["update_protocol"] = 3
            (root / "release-manifest.json").write_text(json.dumps(manifest))
            with self.assertRaises(installation.OldProtocolError):
                installation.load_manifest(root)

    def test_unknown_and_missing_keys_refused(self):
        for mutate in (lambda m: m.update({"extra": 1}),
                       lambda m: m.pop("entry_point"),
                       lambda m: m.update({"entry_point": "other.module:main"}),
                       lambda m: m.update({"version": "1.0.0.0-rc1"}),
                       lambda m: m.update({"packages": ["mihomoctl", "not an identifier"]})):
            with tempfile.TemporaryDirectory() as folder:
                root = write_source(Path(folder) / "src")
                manifest = json.loads((root / "release-manifest.json").read_text())
                mutate(manifest)
                (root / "release-manifest.json").write_text(json.dumps(manifest))
                with self.assertRaises(installation.InstallationError):
                    installation.load_manifest(root)

    def test_deeply_nested_manifest_is_unreadable_not_a_crash(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "src"
            root.mkdir()
            (root / "release-manifest.json").write_text("[" * 100000, encoding="utf-8")
            with self.assertRaisesRegex(installation.InstallationError, "release-manifest-unreadable"):
                installation.load_manifest(root)


@linux_only
class InventoryTests(unittest.TestCase):
    def test_unreviewed_files_refused_and_reviewed_accepted(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_source(Path(folder) / "src")
            installation.verify_inventory(root, installation.load_manifest(root))
            (root / "MainServer_private_notes.md").write_text("private\n", encoding="utf-8")
            with self.assertRaises(installation.InventoryError):
                installation.verify_inventory(root, installation.load_manifest(root))
            (root / "MainServer_private_notes.md").unlink()
            (root / "notes").mkdir()
            (root / "notes" / "random.md").write_text("x\n", encoding="utf-8")
            with self.assertRaises(installation.InventoryError):
                installation.verify_inventory(root, installation.load_manifest(root))

    def test_credential_like_names_refused_even_inside_allowed_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_source(Path(folder) / "src")
            (root / "mihomoctl" / "credentials.yaml").write_text("password: x\n", encoding="utf-8")
            with self.assertRaisesRegex(installation.InventoryError, "private"):
                installation.verify_inventory(root, installation.load_manifest(root))

    def test_local_tooling_noise_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_source(Path(folder) / "src")
            (root / ".git").mkdir()
            (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
            (root / "paseo.json").write_text("{}", encoding="utf-8")
            (root / "mihomoctl" / "__pycache__").mkdir()
            (root / "mihomoctl" / "__pycache__" / "x.cpython-310.pyc").write_bytes(b"")
            installation.verify_inventory(root, installation.load_manifest(root))


@linux_only
class PyprojectTests(unittest.TestCase):
    def test_repository_pyproject_cross_checks(self):
        installation.cross_check_pyproject(ROOT, installation.load_manifest(ROOT))

    def test_multiline_array_and_mismatch(self):
        with tempfile.TemporaryDirectory() as folder:
            root = write_source(Path(folder) / "src")
            (root / "pyproject.toml").write_text(
                '[project]\nname = "mihomoctl"\nversion = "1.0.0"\n\n'
                '[project.scripts]\nmihomoctl = "mihomoctl.cli:main"\n\n'
                '[tool.suptools]\nkey = "other"\n\n'
                '[tool.setuptools]\npackages = [\n  "mihomoctl",\n  "scripts",\n]\n',
                encoding="utf-8")
            installation.cross_check_pyproject(root, installation.load_manifest(root))
            (root / "pyproject.toml").write_text(
                '[project]\nname = "mihomoctl"\nversion = "0.9.9"\n\n'
                '[project.scripts]\nmihomoctl = "mihomoctl.cli:main"\n',
                encoding="utf-8")
            with self.assertRaises(installation.InstallationError):
                installation.cross_check_pyproject(root, installation.load_manifest(root))


@linux_only
class WheelLogicTests(unittest.TestCase):
    def test_selected_nested_extra_and_environment_markers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            # An already resolved dependency may acquire an extra later.
            build_wheel(root, 'markdown_it_py', '3.0.0', requires=[
                'linkify-it-py>=1,<3 ; extra == "linkify"'], files={'markdown_it/__init__.py': b''})
            build_wheel(root, 'textual', '8.2.8', requires=[
                'markdown-it-py[linkify] (>=2.1.0)',
                'tree-sitter ; (python_version >= "3.10") and (extra == "syntax")'],
                files={'textual/__init__.py': b''})
            build_wheel(root, 'linkify_it_py', '2.0.3', requires=(), files={'linkify_it/__init__.py': b''})
            result = installation.resolve_dependency_wheels([
                'markdown-it-py>=2', 'textual==8.2.8 ; extra == "tui"'], root, extras=['tui'])
            self.assertCountEqual([wheel['name'] for wheel in result], ['textual', 'markdown-it-py', 'linkify-it-py'])
            result = installation.resolve_dependency_wheels(['textual==8.2.8 ; extra == "tui"'], root)
            self.assertEqual(result, [])
            with self.assertRaisesRegex(installation.InstallationError, 'unsupported-environment-marker'):
                installation.resolve_dependency_wheels(['textual ; python_version >= "3.10"'], root, extras=['tui'])
            result = installation.resolve_dependency_wheels([
                'textual ; extra == "tui" and python_version >= "3.10"'], root, extras=['tui'], origin='tui')
            self.assertTrue(all(wheel['origin'] == 'tui' for wheel in result))
            self.assertIn('textual', [wheel['name'] for wheel in result])
            build_wheel(root, 'tree_sitter', '0.25.0', requires=(), files={'tree_sitter/__init__.py': b''})
            result = installation.resolve_dependency_wheels(['textual[syntax]==8.2.8'], root, origin='tui')
            self.assertIn('tree-sitter', [wheel['name'] for wheel in result])

    def test_version_ordering_and_specifiers(self):
        self.assertLess(installation.parse_version("1.0.0rc1"), installation.parse_version("1.0.0"))
        self.assertLess(installation.parse_version("1.0.0"), installation.parse_version("1.0.1"))
        self.assertLess(installation.parse_version("1.9"), installation.parse_version("1.10"))
        self.assertTrue(installation._specifier_satisfied(">=6.0.1", installation.parse_version("6.0.3")))
        self.assertFalse(installation._specifier_satisfied("==6.0.2", installation.parse_version("6.0.3")))
        self.assertTrue(installation._specifier_satisfied("~=6.0", installation.parse_version("6.0.3")))
        with self.assertRaises(installation.InstallationError):
            installation.parse_version("1.0.0-dev1")

    def test_requirement_parsing(self):
        name, spec, marker = installation.parse_requirement("PyYAML[extra] >= 6.0.1 ; extra == 'tui'")
        self.assertEqual((name, marker), ("pyyaml", "extra == 'tui'"))
        self.assertEqual(installation.parse_requirement("textual>=0.40")[:2], ("textual", ">=0.40"))

    def test_wheel_tag_compatibility(self):
        def compatible(name):
            return installation.wheel_compatible_here(installation.parse_wheel_filename(name))
        self.assertTrue(compatible("mihomoctl-1.0.0-py3-none-any.whl"))
        if sys.version_info[:2] == (3, 10) and platform.machine() == "x86_64":
            self.assertTrue(compatible("PyYAML-6.0.3-cp310-cp310-manylinux2014_x86_64.whl"))
        self.assertFalse(compatible("mihomoctl-1.0.0-cp39-cp39-linux_x86_64.whl"))
        self.assertFalse(compatible("mihomoctl-1.0.0-py3-none-musllinux_1_1_x86_64.whl"))
        with self.assertRaises(installation.InstallationError):
            installation.parse_wheel_filename("not-a-wheel.zip")

    def test_entry_stub_references_generation_lib(self):
        stub = installation._entry_stub("/usr/bin/python3", Path("/x/lib"),
                                        installation.load_manifest(ROOT))
        self.assertIn("#!/usr/bin/python3", stub)
        self.assertIn("sys.path.insert(0, '/x/lib')", stub)
        self.assertIn("from mihomoctl.cli import main", stub)


# ---------------------------------------------------------------------------
# filesystem lifecycle
# ---------------------------------------------------------------------------


@linux_only
class InstallationTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="muc-install-")
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.base.chmod(0o700)
        self.home = self.base / "home"
        self.home.mkdir(mode=0o700)
        (self.home / "runtime").mkdir(mode=0o700)
        self.env = patch.dict(os.environ, {
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / "config"),
            "XDG_DATA_HOME": str(self.home / "data"),
            "XDG_STATE_HOME": str(self.home / "state"),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "XDG_RUNTIME_DIR": str(self.home / "runtime"),
            "PATH": "/usr/bin:/bin",
        }, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        for name in SHELL_DECOYS:
            (self.home / name).write_text("# decoy %s\n" % name, encoding="utf-8")
        self.source = write_source(self.base / "source")
        self.wheelhouse = self.base / "wheelhouse"
        self.wheelhouse.mkdir()
        fake_pyyaml_wheel(self.wheelhouse)
        self.scope = Scope(system=False)
        self.paths = installation.InstallPaths(self.scope)
        self.python = TEST_PYTHON if TEST_PYTHON.is_file() and os.access(
            str(TEST_PYTHON), os.X_OK) else None

    # -- helpers -----------------------------------------------------------
    def install(self, source=None, **kwargs):
        kwargs.setdefault("python", self.python)
        kwargs.setdefault("wheelhouse", self.wheelhouse)
        return installation.install(self.scope, source or self.source, **kwargs)

    def snapshot_home(self):
        return {str(p.relative_to(self.home)): p.read_bytes()
                for p in self.home.rglob("*") if p.is_file()}

    def assert_shell_untouched(self, before):
        for name in SHELL_DECOYS:
            self.assertEqual((self.home / name).read_bytes(), before[str(name)],
                             "%s must never be modified" % name)

    def assert_no_outside_changes(self, before, *extra_allowed):
        allowed = ("data/mihomoctl/install/", "data/mihomoctl/install-pending.json",
                   "state/mihomoctl/install-backups/", ".local/bin/mihomoctl",
                   "runtime/mihomoctl/operation.lock") + tuple(extra_allowed)
        after = self.snapshot_home()
        for path in sorted(set(before) | set(after)):
            if path.startswith(allowed):
                continue
            self.assertEqual(before.get(path), after.get(path),
                             "unexpected change outside install paths: %s" % path)

    def run_cli(self, *args):
        return subprocess.run([str(self.paths.bin_link), *args], capture_output=True,
                              text=True, timeout=60)


@linux_only
class UserInstallTests(InstallationTestBase):
    def test_in_place_drift_during_lock_acquisition_refuses_upgrade(self):
        installed = self.install()
        current = installation.current_target(self.paths)
        generation = self.paths.generations / installed['generation']
        module = generation / 'lib/mihomoctl/cli.py'
        before_generations = set(self.paths.generations.iterdir())
        before_backups = set(self.paths.backups_root.iterdir())
        source = write_source(self.base / 'upgrade-source', version='1.0.1')
        operation_lock = locks.operation_lock

        @contextlib.contextmanager
        def lock_with_in_place_drift(scope):
            with operation_lock(scope):
                module.chmod(0o644)
                module.write_bytes(b'# changed after preflight verification\n')
                self.assertEqual(installation.current_target(self.paths), current)
                yield

        with patch.object(locks, 'operation_lock', side_effect=lock_with_in_place_drift), \
                patch.object(installation, 'verify_installed', wraps=installation.verify_installed) as verify:
            with self.assertRaisesRegex(installation.InstallationDriftError, 'installed-code-modified'):
                self.install(source=source)
        # The preflight and version checks share one installed record; the
        # separate in-lock digest check must reject drift before staging a new generation.
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(installation.current_target(self.paths), current)
        self.assertEqual(set(self.paths.generations.iterdir()), before_generations)
        self.assertEqual(set(self.paths.backups_root.iterdir()), before_backups)

    def test_inherited_extra_survives_base_only_or_absent_wheelhouse_and_can_be_cleared(self):
        self.add_tui()
        build_wheel(self.wheelhouse, name='rich', version='14.2.0', requires=(), files={'rich/__init__.py': b''})
        # Rebuild Textual with transitive and shared-base dependencies to test attribution.
        build_wheel(self.wheelhouse, name='textual', version='8.2.8',
                    requires=('rich>=14.2.0', 'PyYAML>=6.0.1'),
                    files={'textual/__init__.py': b'__version__ = "8.2.8"\n'})
        self.install(extras=['tui'])
        record = installation.verify_installed(self.scope)
        self.assertIn('textual', record['extra_packages']['tui'])
        self.assertIn('rich', record['extra_packages']['tui'])
        self.assertNotIn('yaml', record['extra_packages']['tui'])
        for wheel in self.wheelhouse.glob('*.whl'):
            if not wheel.name.startswith('PyYAML-'):
                wheel.unlink()
        for wheelhouse in (self.wheelhouse, None):
            old_generation = installation.current_record(self.scope)['generation']
            with patch('socket.socket', side_effect=AssertionError('upgrade connected')), \
                    patch.object(installation, 'verify_generation', wraps=installation.verify_generation) as verify:
                result = self.install(allow_same_version=True, wheelhouse=wheelhouse)
            self.assertEqual(sum(call.args[0]['generation'] == old_generation for call in verify.call_args_list), 2)
            self.assertEqual(result['extras_carried_forward'], ['tui'])
            record = installation.verify_installed(self.scope)
            self.assertEqual(record['extras_carried_forward'], ['tui'])
            self.assertIn('lib/textual/__init__.py', record['file_digests'])
            lib = self.paths.generations / result['generation'] / 'lib'
            code = 'import sys; sys.path.insert(0, sys.argv[1]); import textual,rich; assert textual.__file__.startswith(sys.argv[1]); assert rich.__file__.startswith(sys.argv[1])'
            subprocess.run([str(self.python), '-I', '-B', '-c', code, str(lib)], check=True)
        with self.assertRaises(installation.InstallationError) as caught:
            self.install(extras=['tui'], allow_same_version=True)
        self.assertEqual(caught.exception.code, 'extra-wheels-unavailable')
        self.assertEqual(caught.exception.detail, 'tui')
        self.assertIn('textual', caught.exception.remediation)
        self.assertIn('--wheelhouse', caught.exception.remediation)
        result = self.install(extras=[], allow_same_version=True)
        self.assertEqual(result['extras'], [])
        self.assertFalse((self.paths.generations / result['generation'] / 'lib/textual').exists())

    def test_unattributed_inherited_extra_is_loudly_dropped(self):
        self.add_tui()
        self.install(extras=['tui'])
        record = installation.verify_installed(self.scope)
        record.pop('extra_packages')  # An older generation has no safe attribution.
        generation = self.paths.generations / record['generation']
        generation.chmod(0o755)
        (generation / 'record.json').chmod(0o600)
        (generation / 'record.json').write_text(json.dumps(record))
        next(self.wheelhouse.glob('textual-*.whl')).unlink()
        result = self.install(allow_same_version=True)
        self.assertEqual(result['extras'], [])
        self.assertEqual(result['warnings'][0]['code'], 'extras-dropped')
        self.assertEqual(result['warnings'][0]['detail'], 'tui')
        self.assertEqual(installation.verify_installed(self.scope)['warnings'], result['warnings'])

    def add_tui(self):
        with (self.source / 'pyproject.toml').open('a', encoding='utf-8') as stream:
            stream.write('\n[project.optional-dependencies]\ntui = ["textual==8.2.8"]\n')
        build_wheel(self.wheelhouse, name='textual', version='8.2.8', requires=(),
                    files={'textual/__init__.py': b'__version__ = "8.2.8"\n'})

    def test_extra_stays_private_is_verified_and_survives_upgrade(self):
        self.add_tui()
        before = self.snapshot_home()
        with patch('socket.socket', side_effect=AssertionError('offline install connected')):
            result = self.install(extras=['tui'])
        generation = self.paths.generations / result['generation']
        module = generation / 'lib/textual/__init__.py'
        self.assertTrue(module.is_file())
        self.assertEqual(module.stat().st_mode & 0o222, 0)
        record = installation.verify_installed(self.scope)
        self.assertEqual(record['extras'], ['tui'])
        self.assertIn('lib/textual/__init__.py', record['file_digests'])
        self.assertEqual(installation.installation_status(self.scope)['extras'], ['tui'])
        self.assert_no_outside_changes(before)
        result = self.install(allow_same_version=True)
        self.assertTrue((self.paths.generations / result['generation'] / 'lib/textual/__init__.py').is_file())
        self.assertEqual(installation.verify_installed(self.scope)['extras'], ['tui'])

    def test_extra_not_installed_implicitly_and_unknown_extra_fails(self):
        self.add_tui()
        result = self.install()
        self.assertFalse((self.paths.generations / result['generation'] / 'lib/textual').exists())
        self.assertEqual(installation.verify_installed(self.scope)['extras'], [])
        with self.assertRaisesRegex(installation.InstallationError, 'unknown-extra'):
            self.install(extras=['typo'], allow_same_version=True)

    def test_selected_extra_requires_local_wheels(self):
        self.add_tui()
        with self.assertRaisesRegex(installation.InstallationError, 'extra-wheels-unavailable'):
            self.install(extras=['tui'], wheelhouse=None)
        next(self.wheelhouse.glob('textual-*.whl')).unlink()
        with self.assertRaisesRegex(installation.InstallationError, 'extra-wheels-unavailable'):
            self.install(extras=['tui'])

    def test_full_user_install_from_source_tree(self):
        before = self.snapshot_home()
        result = self.install()
        self.assertEqual(result["version"], "1.0.0")
        self.assertTrue(re.fullmatch(r"[a-f0-9]{32}", result["generation"]))
        self.assertEqual(os.readlink(self.paths.bin_link),
                         str(self.paths.install_root / "current" / "bin" / "mihomoctl"))
        record = installation.verify_installed(self.scope)
        self.assertEqual(record["scope"], "user")
        self.assertEqual(record["entry_point"], "mihomoctl.cli:main")
        self.assertEqual(stat.S_IMODE(self.paths.install_root.stat().st_mode), 0o700)
        generation = self.paths.generations / result["generation"]
        self.assertEqual(stat.S_IMODE((generation / "record.json").stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE((generation / "lib" / "mihomoctl" / "cli.py").stat().st_mode), 0o444)
        self.assertEqual(stat.S_IMODE((generation / "lib").stat().st_mode), 0o555)
        self.assertEqual(stat.S_IMODE((generation / "bin" / "mihomoctl").stat().st_mode), 0o555)
        self.assertEqual(stat.S_IMODE(generation.stat().st_mode), 0o555)
        probe = self.run_cli()
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertIn("fixture-cli-ok", probe.stdout)
        self.assertIn("mihomoctl 1.0.0", self.run_cli("--version").stdout)
        # controller capability is packaged and importable from the generation
        probe = subprocess.run(
            [str(record["python"]), "-c",
             "import sys; sys.path.insert(0, sys.argv[1]); "
             "import scripts.controller as c; print(c.info())",
             str(generation / "lib")], capture_output=True, text=True, timeout=60)
        self.assertIn("controller-ok", probe.stdout, probe.stderr)
        # offline: no network touch (the engine never opens sockets; nothing
        # to assert beyond the static contract) — assert nothing else changed
        self.assert_no_outside_changes(before)
        self.assert_shell_untouched(before)

    def test_dry_run_validates_and_changes_nothing(self):
        before = self.snapshot_home()
        result = self.install(dry_run=True)
        self.assertTrue(result["dry_run"])
        self.assertFalse(self.paths.install_root.exists())
        self.assertFalse(self.paths.bin_link.exists())
        self.assert_no_outside_changes(before)

    def test_same_version_reinstall_requires_opt_in(self):
        first = self.install()
        with self.assertRaisesRegex(installation.InstallationError, "same-version"):
            self.install()
        second = self.install(allow_same_version=True)
        self.assertEqual(second["replaced"], "generations/" + first["generation"])
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
        self.assertEqual(len(list(self.paths.generations.iterdir())), 2)

    def test_update_to_newer_version_and_retention(self):
        first = self.install()
        newer = write_source(self.base / "source-1.1.0", version="1.1.0")
        result = self.install(source=newer)
        self.assertEqual(result["replaced"], "generations/" + first["generation"])
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.1.0")
        self.assertTrue((self.paths.generations / first["generation"]).is_dir())

    def test_downgrade_requires_opt_in(self):
        self.install()
        older = write_source(self.base / "source-0.9.9", version="0.9.9")
        with self.assertRaisesRegex(installation.InstallationError, "downgrade"):
            self.install(source=older)
        self.install(source=older, allow_downgrade=True)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 0.9.9")

    def test_update_over_drifted_installation_refused(self):
        first = self.install()
        target = self.paths.generations / first["generation"] / "lib" / "mihomoctl" / "cli.py"
        os.chmod(target, 0o644)
        target.write_text("modified\n", encoding="utf-8")
        with self.assertRaises(installation.InstallationDriftError):
            self.install()

    def test_unreviewed_source_refused_before_writes(self):
        before = self.snapshot_home()
        (self.source / "MainServer_notes.md").write_text("private\n", encoding="utf-8")
        with self.assertRaises(installation.InventoryError):
            self.install()
        self.assertFalse(self.paths.install_root.exists())
        self.assert_no_outside_changes(before)

    def test_version_marker_disagreement_refused(self):
        bad = write_source(self.base / "bad-version", init_version="0.0.1")
        with self.assertRaisesRegex(installation.InstallationError, "version-markers"):
            self.install(source=bad)

    def test_entry_point_disagreement_refused(self):
        bad = write_source(self.base / "bad-entry",
                           manifest=dict(FIXTURE_MANIFEST, entry_point="mihomoctl.other:main"))
        with self.assertRaisesRegex(installation.InstallationError, "entry-point"):
            self.install(source=bad)


@linux_only
class InstallRefusalTests(InstallationTestBase):
    def test_old_protocol_source_refused_before_any_write(self):
        before = self.snapshot_home()
        legacy = old_protocol_source(self.base / "old-source")
        with self.assertRaises(installation.OldProtocolError):
            self.install(source=legacy)
        self.assertFalse((self.home / "data" / "mihomoctl").exists())
        self.assertFalse(self.paths.bin_link.exists())
        self.assert_no_outside_changes(before)

    def test_legacy_09x_installation_blocks_with_guidance(self):
        before = self.snapshot_home()
        legacy_root = self.home / ".local" / "share" / "mihomo-userctl"
        legacy_root.mkdir(parents=True)
        (legacy_root / "common.bash").write_text("# legacy\n", encoding="utf-8")
        with self.assertRaisesRegex(installation.InstallationError, "0.9.x"):
            self.install()
        self.assertFalse(self.paths.install_root.exists())
        self.assertIn("# legacy", (legacy_root / "common.bash").read_text())
        self.assert_no_outside_changes(before, ".local/share/mihomo-userctl")

    def test_occupied_launcher_path_refused(self):
        self.paths.bin_dir.mkdir(parents=True)
        (self.paths.bin_link).write_text("#!/bin/sh\n", encoding="utf-8")
        with self.assertRaisesRegex(installation.InstallationError, "launcher-path-occupied"):
            self.install()

    def test_system_scope_requires_root(self):
        if os.geteuid() == 0:
            self.skipTest("non-root context required")
        scope = Scope(system=True)
        with self.assertRaises(PermissionScopeError):
            installation.install(scope, self.source, python=self.python,
                                 wheelhouse=self.wheelhouse)

    def test_generation_ownership_enforced_for_system(self):
        if os.geteuid() == 0:
            self.skipTest("non-root context required")
        system_scope = Scope(system=True)
        system_paths = installation.InstallPaths(system_scope)
        generation = self.base / "system-generation"
        generation.mkdir(parents=True)
        with self.assertRaisesRegex(installation.InstallationError, "ownership"):
            installation._enforce_generation_ownership(generation, system_scope)


@linux_only
class WheelInstallTests(InstallationTestBase):
    def test_wheel_metadata_extra_is_private_and_unknown_name_fails(self):
        source = self.wheel_source(requires=('PyYAML>=6.0.1', 'textual==8.2.8 ; python_version >= "3.10" and extra == "tui"'))
        build_wheel(self.wheelhouse, name='textual', version='8.2.8', requires=(),
                    files={'textual/__init__.py': b'__version__ = "8.2.8"\n'})
        base = self.install(source=source, extras=[])
        self.assertFalse((self.paths.generations / base['generation'] / 'lib/textual').exists())
        result = self.install(source=source, extras=['tui'], allow_same_version=True)
        self.assertTrue((self.paths.generations / result['generation'] / 'lib/textual/__init__.py').is_file())
        self.assertEqual(installation.verify_installed(self.scope)['extras'], ['tui'])
        with self.assertRaisesRegex(installation.InstallationError, 'unknown-extra'):
            self.install(source=source, extras=['typo'], allow_same_version=True)

    def wheel_source(self, **kwargs):
        directory = self.base / ("wheel-src-" + kwargs.get("version", "1.0.0"))
        directory.mkdir(parents=True, exist_ok=True)
        build_wheel(directory, **kwargs)
        manifest = json.loads(json.dumps(FIXTURE_MANIFEST))
        manifest["version"] = kwargs.get("version", "1.0.0")
        manifest["inventory"]["runtime_files"] = ["mihomoctl/__init__.py", "mihomoctl/cli.py", "mihomoctl/lifecycle/__init__.py", "scripts/__init__.py", "scripts/controller.py"]
        manifest["inventory"]["files"] = manifest["inventory"]["runtime_files"] + ["release-manifest.json"]
        (directory / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return directory

    def test_install_from_wheel_dir_with_wheelhouse(self):
        source = self.wheel_source()
        result = self.install(source=source)
        self.assertEqual(result["source_kind"], "wheel-dir")
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
        generation = self.paths.generations / result["generation"]
        self.assertTrue((generation / "lib" / "yaml" / "__init__.py").is_file())
        installation.verify_installed(self.scope)

    def test_wheel_install_under_group_writable_umask_keeps_trusted_directories(self):
        source = self.wheel_source()
        original = os.umask(0o002)
        try:
            self.install(source=source)
            installation.verify_installed(self.scope)
            self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
            self.assertTrue(all(not (p.stat().st_mode & 0o022)
                                for p in self.paths.generations.rglob("*") if not p.is_symlink()))
        finally:
            os.umask(original)

    def test_tampered_wheel_record_refused(self):
        source = self.base / "wheel-tampered"
        source.mkdir()
        build_wheel(source, corrupt=("mihomoctl/cli.py", b"tampered\n"))
        (source / "release-manifest.json").write_text(json.dumps(FIXTURE_MANIFEST))
        with self.assertRaisesRegex(installation.InstallationError, "digest-mismatch"):
            self.install(source=source)

    def test_unlisted_wheel_member_refused(self):
        source = self.base / "wheel-unlisted"
        source.mkdir()
        build_wheel(source, unlisted=("sneaky/unreviewed.py", b"x = 1\n"))
        (source / "release-manifest.json").write_text(json.dumps(FIXTURE_MANIFEST))
        with self.assertRaisesRegex(installation.InstallationError, "not-covered-by-record"):
            self.install(source=source)

    def test_incompatible_tag_refused(self):
        source = self.wheel_source(tag=("cp39", "cp39", "linux_x86_64"))
        with self.assertRaisesRegex(installation.InstallationError, "incompatible"):
            self.install(source=source)

    def test_missing_dependency_wheel_refused(self):
        source = self.wheel_source()
        empty_house = self.base / "empty-wheelhouse"
        empty_house.mkdir()
        with self.assertRaisesRegex(installation.InstallationError, "dependency-wheel-missing"):
            self.install(source=source, wheelhouse=empty_house)

    def test_wheel_version_disagrees_with_manifest(self):
        source = self.wheel_source(version="1.2.3")
        (source / "release-manifest.json").write_text(json.dumps(FIXTURE_MANIFEST))
        with self.assertRaisesRegex(installation.InstallationError, "version-disagrees"):
            self.install(source=source)

    def test_wheel_top_level_not_in_manifest_refused(self):
        source = self.base / "wheel-extra-top"
        source.mkdir()
        build_wheel(source, files={
            "mihomoctl/__init__.py": b'__version__ = "1.0.0"\n',
            "mihomoctl/cli.py": FIXTURE_CLI.encode(),
            "mihomoctl/lifecycle/__init__.py": b"# subpackage marker\n",
            "vendor_tool/__init__.py": b""})
        (source / "release-manifest.json").write_text(json.dumps(FIXTURE_MANIFEST))
        with self.assertRaises(installation.InventoryError):
            self.install(source=source)


@linux_only
class ArchiveSourceTests(InstallationTestBase):
    def zip_release(self, dest, version="1.0.0"):
        buffer = io.BytesIO()
        root = "mihomoctl-%s" % version
        with zipfile.ZipFile(buffer, "w") as zf:
            for path in sorted(self.source.rglob("*")):
                if path.is_file():
                    zf.writestr("%s/%s" % (root, path.relative_to(self.source).as_posix()),
                                path.read_bytes())
        dest.write_bytes(buffer.getvalue())
        return dest

    def test_install_from_release_zip(self):
        archive = self.zip_release(self.base / "release-1.0.0.zip")
        result = self.install(source=archive)
        self.assertEqual(result["source_kind"], "source-tree")
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")

    def test_install_from_release_tar_gz(self):
        buffer = io.BytesIO()
        root = "mihomoctl-1.0.0"
        with tarfile.open(fileobj=buffer, mode="w:gz") as tf:
            for path in sorted(self.source.rglob("*")):
                if path.is_file():
                    info = tarfile.TarInfo("%s/%s" % (root, path.relative_to(self.source).as_posix()))
                    payload = path.read_bytes()
                    info.size = len(payload)
                    tf.addfile(info, io.BytesIO(payload))
        archive = self.base / "release-1.0.0.tar.gz"
        archive.write_bytes(buffer.getvalue())
        self.install(source=archive)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")

    def test_archive_path_escape_refused(self):
        archive = self.base / "evil.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("../escape.txt", b"x")
        with self.assertRaisesRegex(installation.InstallationError, "unsafe-archive-member"):
            self.install(source=archive)


@linux_only
class RollbackTests(InstallationTestBase):
    def test_rollback_update_restores_previous_generation(self):
        first = self.install()
        newer = write_source(self.base / "source-1.1.0", version="1.1.0")
        second = self.install(source=newer)
        before = self.snapshot_home()
        installation.rollback(self.scope, second["backup"])
        self.assertEqual(installation.current_target(self.paths),
                         "generations/" + first["generation"])
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
        installation.verify_installed(self.scope)
        self.assertFalse((self.paths.generations / second["generation"]).is_dir())
        self.assert_no_outside_changes(before)

    def test_rollback_first_install_removes_everything(self):
        result = self.install()
        before = self.snapshot_home()
        installation.rollback(self.scope, result["backup"])
        self.assertFalse(self.paths.bin_link.is_symlink())
        self.assertFalse(self.paths.install_root.exists())
        self.assertIsNone(installation.current_record(self.scope))
        self.assert_no_outside_changes(before)

    def test_rollback_is_idempotent(self):
        result = self.install()
        installation.rollback(self.scope, result["backup"])
        outcome = installation.rollback(self.scope, result["backup"])
        self.assertTrue(outcome["restored"])

    def test_stale_backup_refused_after_later_install(self):
        self.install()
        second = self.install(source=write_source(self.base / "s2", version="1.0.1"))
        self.install(source=write_source(self.base / "s3", version="1.0.2"))
        with self.assertRaisesRegex(installation.InstallationError, "stale-backup"):
            installation.rollback(self.scope, second["backup"])

    def test_pending_operation_blocks_new_ones_and_names_backup(self):
        result = self.install()
        installation._write_private_json(self.paths.pending,
                                         {"kind": "install", "backup": result["backup"]})
        with self.assertRaisesRegex(installation.InstallationError, "interrupted-installation"):
            self.install(source=write_source(self.base / "s2", version="1.0.1"))
        with self.assertRaisesRegex(installation.InstallationError, "interrupted-installation"):
            installation.uninstall(self.scope)
        installation.rollback(self.scope, result["backup"])


@linux_only
class UninstallTests(InstallationTestBase):
    def test_uninstall_preserves_config_cores_and_shell(self):
        self.install()
        config = self.home / "config" / "mihomoctl"
        config.mkdir(parents=True)
        (config / "manager.yaml").write_text("version: 1\n", encoding="utf-8")
        core = self.home / "data" / "mihomoctl" / "cores" / "mihomo"
        core.parent.mkdir(parents=True)
        core.write_bytes(b"\x7fELF-fake-core")
        before = self.snapshot_home()
        outcome = installation.uninstall(self.scope)
        self.assertFalse(self.paths.install_root.exists())
        self.assertFalse(self.paths.bin_link.is_symlink())
        self.assertTrue((Path(outcome["backup"]) / "tree").is_dir())
        self.assertEqual(core.read_bytes(), b"\x7fELF-fake-core")  # never adopted or removed
        self.assertIn("version: 1", (config / "manager.yaml").read_text())
        self.assert_shell_untouched(before)
        self.assert_no_outside_changes(before)

    def test_uninstall_rollback_restores_working_install(self):
        self.install()
        outcome = installation.uninstall(self.scope)
        installation.rollback(self.scope, outcome["backup"])
        installation.verify_installed(self.scope)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")

    def test_uninstall_without_installation_fails(self):
        with self.assertRaisesRegex(installation.InstallationError, "not-installed"):
            installation.uninstall(self.scope)

    def test_uninstall_rollback_refused_after_reinstall(self):
        self.install()
        outcome = installation.uninstall(self.scope)
        self.install()
        with self.assertRaisesRegex(installation.InstallationError, "stale-backup"):
            installation.rollback(self.scope, outcome["backup"])


@linux_only
class LockingTests(InstallationTestBase):
    def test_concurrent_mutation_blocked_by_scope_lock(self):
        self.install()
        newer = write_source(self.base / "source-1.1.0", version="1.1.0")
        with locks.operation_lock(self.scope):
            with self.assertRaises(MihomoctlError):
                self.install(source=newer)

    def test_lock_false_runs_inside_an_already_held_lock(self):
        with locks.operation_lock(self.scope):
            result = self.install(lock=False)
        self.assertEqual(result["version"], "1.0.0")


@linux_only
class PruneTests(InstallationTestBase):
    def test_prune_keeps_active_and_most_recent(self):
        generations = [self.install()["generation"]]
        for version in ("1.0.1", "1.0.2", "1.0.3"):
            source = write_source(self.base / ("s-" + version), version=version)
            generations.append(self.install(source=source)["generation"])
        removed = installation.prune_generations(self.scope, keep=1)
        self.assertIn(generations[0], removed)
        self.assertNotIn(generations[-1], removed)
        installation.verify_installed(self.scope)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.3")


@linux_only
class BootstrapScriptTests(InstallationTestBase):
    def test_bootstrap_extra_selection_inheritance_clear_and_exclusion(self):
        with (self.source / 'pyproject.toml').open('a') as stream:
            stream.write('\n[project.optional-dependencies]\ntui = ["textual==8.2.8"]\n')
        build_wheel(self.wheelhouse, name='textual', version='8.2.8', requires=(), files={'textual/__init__.py': b''})
        args = ['install', '--source', str(self.source), '--wheelhouse', str(self.wheelhouse), '--python', str(self.python)]
        probe = self.run_script(*args, '--extras', 'tui', '--extras', 'tui')
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout[probe.stdout.index('{'):])['extras'], ['tui'])
        probe = self.run_script(*args, '--allow-same-version')
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout[probe.stdout.index('{'):])['extras'], ['tui'])
        probe = self.run_script(*args, '--allow-same-version', '--no-extras')
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(json.loads(probe.stdout[probe.stdout.index('{'):])['extras'], [])
        probe = self.run_script(*args, '--extras', 'tui', '--no-extras')
        self.assertEqual(probe.returncode, 2)

    def run_script(self, *argv):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / "bootstrap.py"), *argv],
                              capture_output=True, text=True, timeout=120,
                              env=dict(os.environ, PYTHONPATH=""))

    def test_bash_wrappers_are_syntactically_valid_and_old_flags_rejected(self):
        for script in ("install.sh", "uninstall.sh"):
            probe = subprocess.run(["bash", "-n", str(ROOT / script)],
                                   capture_output=True, text=True)
            self.assertEqual(probe.returncode, 0, probe.stderr)
        probe = subprocess.run(["bash", str(ROOT / "install.sh"), "--port", "1234"],
                               capture_output=True, text=True, timeout=60)
        self.assertNotEqual(probe.returncode, 0)
        self.assertFalse(self.paths.install_root.exists())
        self.assertIn("unrecognized", probe.stderr)

    def test_install_sh_end_to_end(self):
        probe = subprocess.run(
            ["bash", str(ROOT / "install.sh"), "--source", str(self.source),
             "--wheelhouse", str(self.wheelhouse)]
            + (["--python", str(self.python)] if self.python else []),
            capture_output=True, text=True, timeout=180)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
        self.assertIn("no shell startup files", probe.stdout)

    def test_bootstrap_status_and_verify(self):
        self.install()
        status = json.loads(self.run_script("status").stdout)
        self.assertTrue(status["installed"])
        self.assertEqual(status["version"], "1.0.0")
        self.assertEqual(status["problems"], [])
        verify = json.loads(self.run_script("verify").stdout)
        self.assertEqual(verify["overall"], "PASS")

    def test_self_contained_backup_rollback_without_source_tree(self):
        result = self.install()
        backup = Path(result["backup"])
        self.assertTrue((backup / "bootstrap.py").is_file())
        shutil.rmtree(self.source)
        probe = subprocess.run([sys.executable, str(backup / "bootstrap.py"),
                                "rollback", str(backup)],
                               capture_output=True, text=True, timeout=120,
                               env=dict(os.environ, PYTHONPATH=""))
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertFalse(self.paths.install_root.exists())

    def test_self_contained_uninstall_backup_rollback(self):
        self.install()
        outcome = installation.uninstall(self.scope)
        backup = Path(outcome["backup"])
        self.assertTrue((backup / "bootstrap.py").is_file())
        probe = subprocess.run([sys.executable, str(backup / "bootstrap.py"),
                                "rollback", str(backup)],
                               capture_output=True, text=True, timeout=120,
                               env=dict(os.environ, PYTHONPATH=""))
        self.assertEqual(probe.returncode, 0, probe.stderr)
        installation.verify_installed(self.scope)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")

    def test_uninstall_sh_end_to_end(self):
        self.install()
        probe = subprocess.run(["bash", str(ROOT / "uninstall.sh")],
                               capture_output=True, text=True, timeout=180)
        self.assertEqual(probe.returncode, 0, probe.stderr)
        self.assertFalse(self.paths.install_root.exists())


@linux_only
class InstallerSecurityRegressionTests(InstallationTestBase):
    def test_untrusted_launcher_parent_refused_before_staging(self):
        self.paths.bin_dir.mkdir(parents=True)
        self.paths.bin_dir.chmod(0o777)
        before = self.snapshot_home()
        with self.assertRaisesRegex(MihomoctlError, "installation-target-untrusted"):
            self.install()
        self.assertFalse(self.paths.install_root.exists())
        self.assertEqual(self.snapshot_home(), before)

    def test_group_writable_umask_does_not_contaminate_new_installation_paths(self):
        original = os.umask(0o002)
        try:
            first = self.install()
            self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
            installation.verify_installed(self.scope)
            for path in [self.paths.bin_dir, *self.paths.install_root.rglob("*"),
                         *Path(first["backup"]).rglob("*")]:
                if not path.is_symlink():
                    self.assertFalse(path.stat().st_mode & 0o022, str(path))
            removed = installation.uninstall(self.scope)
            installation.rollback(self.scope, removed["backup"])
            installation.verify_installed(self.scope)
        finally:
            os.umask(original)

    def test_archived_code_is_not_a_runtime_payload(self):
        manifest = installation.load_manifest(ROOT)
        self.assertTrue(all(not name.startswith(('legacy/', 'src/', 'scripts/'))
                            for name in manifest['inventory']['runtime_files']))

    def test_untrusted_interpreter_is_rejected_before_execution(self):
        marker = self.base / "executed"
        interpreter = self.base / "unsafe-python"
        interpreter.write_text("#!/bin/sh\ntouch '" + str(marker) + "'\nexit 0\n", encoding="utf8")
        interpreter.chmod(0o777)
        with self.assertRaises(installation.InstallationError):
            installation.resolve_python(interpreter)
        self.assertFalse(marker.exists())

    def test_failed_uninstall_restores_working_code(self):
        self.install()
        real = installation._rmtree_rw
        counter = [0]
        def fail_once(path):
            counter[0] += 1
            if counter[0] == 1:
                raise OSError("injected removal failure")
            return real(path)
        with patch.object(installation, "_rmtree_rw", side_effect=fail_once):
            with self.assertRaisesRegex(installation.InstallationError, "uninstall-failed-rolled-back"):
                installation.uninstall(self.scope)
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")
        self.assertFalse(self.paths.pending.exists())

    def test_foreign_launcher_symlink_is_preserved(self):
        self.paths.bin_dir.mkdir(parents=True)
        target = self.base / "foreign"
        target.write_text("external", encoding="utf8")
        self.paths.bin_link.symlink_to(target)
        with self.assertRaisesRegex(installation.InstallationError, "launcher-path-occupied"):
            self.install()
        self.assertEqual(self.paths.bin_link.readlink(), target)
        self.assertEqual(target.read_text(), "external")

    def test_source_runtime_extra_and_symlink_are_refused(self):
        extra = self.source / "mihomoctl" / "extra.py"
        extra.write_text("raise RuntimeError('must never execute')", encoding="utf8")
        with self.assertRaises(installation.InventoryError):
            self.install()
        extra.unlink()
        extra.symlink_to(self.source / "mihomoctl" / "cli.py")
        with self.assertRaises(installation.InstallationError):
            self.install()
        self.assertFalse(self.paths.install_root.exists())

    def test_restore_previous_generation_after_gc(self):
        first = self.install()
        second = self.install(source=write_source(self.base / "new-source", version="1.0.1"))
        installation.prune_generations(self.scope, keep=0)
        self.assertFalse((self.paths.generations / first["generation"]).exists())
        installation.rollback(self.scope, second["backup"])
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")

    def test_failed_finalization_restores_previous_generation(self):
        first = self.install()
        real = installation._ensure_launcher
        counter = [0]
        def fail_once(paths):
            counter[0] += 1
            if counter[0] == 1:
                raise OSError("injected finalization failure")
            return real(paths)
        with patch.object(installation, "_ensure_launcher", side_effect=fail_once):
            with self.assertRaisesRegex(installation.InstallationError, "failed-rolled-back") as raised:
                self.install(source=write_source(self.base / "new-source", version="1.0.1"))
        self.assertEqual(installation.failure_codes(raised.exception), [
            "installation-failed-rolled-back", "installation-launcher-activation-failed", "io-error"])
        self.assertNotIn("injected finalization failure", repr(installation.failure_codes(raised.exception)))
        self.assertEqual(installation.current_record(self.scope)["generation"], first["generation"])
        self.assertFalse(self.paths.pending.exists())
        self.assertEqual(self.run_cli("--version").stdout.strip(), "mihomoctl 1.0.0")


@linux_only
class RealProjectPackagingTests(InstallationTestBase):
    """Exercise installed real code rather than the fixture entry point."""

    def test_real_source_and_built_wheel_install_update_uninstall(self):
        import yaml
        project = self.base / "real-source"
        project.mkdir(mode=0o700)
        manifest = installation.load_manifest(ROOT)
        selected = set(manifest["inventory"]["runtime_files"]) | {
            "pyproject.toml", "README.md", "LICENSE", "release-manifest.json", "install.sh", "scripts/__init__.py", "scripts/release/__init__.py", "scripts/release/build_backend.py"}
        for relative in sorted(selected - {"release-manifest.json"}):
            target = project / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
            target.chmod(0o644)
        # This is a private runtime-only development fixture, not a release.
        # It deliberately excludes pending review documents and publish gates.
        manifest["inventory"]["files"] = sorted(selected)
        (project / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf8")
        real_wh = self.base / "real-wheelhouse"
        real_wh.mkdir()
        downloaded = Path("/tmp/mihomoctl-v1-install-wheelhouse")
        wheels = sorted(downloaded.glob("pyyaml-6.0.3-*.whl"))
        if wheels:
            shutil.copyfile(wheels[0], real_wh / wheels[0].name)
        else:
            # Repackage the actual installed YAML implementation for offline CI;
            # the fixture fake YAML cannot pass safe_load/import checks below.
            package = Path(yaml.__file__).parent
            files = {"yaml/" + p.relative_to(package).as_posix(): p.read_bytes()
                     for p in package.rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts}
            build_wheel(real_wh, name="pyyaml", version="6.0.3", files=files,
                        requires=(), requires_python=None)
        built = self.base / "built"
        probe = subprocess.run([sys.executable, "-I", "-m", "build", "--wheel",
                                "--no-isolation", "--outdir", str(built), str(project)],
                               capture_output=True, text=True, timeout=120)
        self.assertEqual(probe.returncode, 0, probe.stderr[-2000:])
        wheel = next(built.glob("mihomoctl-*.whl"))
        with zipfile.ZipFile(wheel) as zf:
            payload = {n for n in zf.namelist() if not n.endswith("/") and ".dist-info/" not in n}
            self.assertEqual(payload, set(manifest["inventory"]["runtime_files"]))
            self.assertNotIn("scripts/paseo.py", payload)
        before = self.snapshot_home()
        first = installation.install(self.scope, project, wheelhouse=real_wh,
                                     python=sys.executable)
        for verb in ("version", "--help"):
            result = self.run_cli(verb)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("mihomoctl", result.stdout)
        wheel_source = self.base / "real-wheel-source"
        wheel_source.mkdir()
        shutil.copyfile(wheel, wheel_source / wheel.name)
        (wheel_source / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf8")
        second = installation.update(self.scope, wheel_source, wheelhouse=real_wh,
                                     python=sys.executable, allow_same_version=True)
        self.assertNotEqual(first["generation"], second["generation"])
        self.assertEqual(self.run_cli("version").returncode, 0)
        installation.rollback(self.scope, second["backup"])
        self.assertEqual(installation.current_record(self.scope)["generation"], first["generation"])
        outcome = installation.uninstall(self.scope)
        self.assertFalse(self.paths.bin_link.exists())
        installation.rollback(self.scope, outcome["backup"])
        self.assertEqual(self.run_cli("version").returncode, 0)
        self.assert_shell_untouched(before)
        self.assert_no_outside_changes(before)


@unittest.skipUnless(LINUX and os.geteuid() == 0
                     and os.environ.get("MIHOMO_V1_PRIVILEGED") == "1",
                     "disposable privileged CI only")
class SystemScopeTests(InstallationTestBase):
    """End-to-end system-scope install on a disposable root VM."""

    def setUp(self):
        super().setUp()
        self.scope = Scope(system=True)
        self.paths = installation.InstallPaths(self.scope)
        self.addCleanup(self._cleanup_system_install)

    def _cleanup_system_install(self):
        with contextlib.suppress(Exception):
            installation.uninstall(self.scope)

    def test_system_install_is_root_owned_and_runs(self):
        if Path("/var/lib/mihomoctl").exists() or Path("/usr/local/bin/mihomoctl").exists():
            self.skipTest("disposable VM must not carry a prior system installation")
        installation.install(self.scope, self.source, wheelhouse=self.wheelhouse)
        record = installation.verify_installed(self.scope)
        self.assertEqual(record["scope"], "system")
        self.assertEqual(record["install_root"], "/usr/local/lib/mihomoctl")
        self.assertEqual(self.paths.bin_link.parent, Path("/usr/local/bin"))
        generation = self.paths.generations / record["generation"]
        for path in generation.rglob("*"):
            self.assertEqual(path.lstat().st_uid, 0)
        probe = subprocess.run([str(self.paths.bin_link), "--version"],
                               capture_output=True, text=True, timeout=60)
        self.assertIn("mihomoctl 1.0.0", probe.stdout)


if __name__ == "__main__":
    unittest.main()
