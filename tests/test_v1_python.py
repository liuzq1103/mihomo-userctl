"""Python distribution identity, standard source builds and ownership boundaries."""
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from mihomoctl import installation
from mihomoctl.release_artifacts import verify_sdist_inventory, verify_wheel_inventory
from mihomoctl.release_identity import (asset_names, distribution, is_stable,
                                       source_stem, version_order, wheel_name)

ROOT = Path(__file__).resolve().parents[1]


class PythonDistributionTests(unittest.TestCase):
    def test_development_release_ordering_preserves_existing_prereleases(self):
        versions = ['1.4.3', '1.5.0.dev0', '1.5.0.dev1', '1.5.0a0.dev0',
                    '1.5.0a0', '1.5.0b0', '1.5.0rc0', '1.5.0', '1.5.1.dev0']
        self.assertEqual(sorted(versions, key=version_order), versions)
        self.assertEqual(version_order('1.5'), version_order('1.5.0'))
        self.assertFalse(is_stable('1.5.0.dev0'))
        self.assertTrue(is_stable('1.5.0'))

    def test_name_transition_does_not_rename_imports_or_old_assets(self):
        self.assertEqual(distribution({}), 'mihomoctl')
        self.assertEqual(source_stem('1.4.0'), 'mihomoctl-1.4.0')
        self.assertEqual(wheel_name('1.5.0.dev0'), 'mihomo_userctl-1.5.0.dev0-py3-none-any.whl')
        self.assertEqual(len(asset_names('1.5.0.dev0')), 4)
        with self.assertRaises(ValueError):
            distribution({'distribution': 'another-project'})

    def test_external_code_cannot_take_over_a_different_managed_install(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            expected = root / 'current/lib/mihomoctl/installation.py'
            expected.parent.mkdir(parents=True)
            expected.write_text('unrelated installed module')
            with patch.object(installation, 'InstallPaths', return_value=SimpleNamespace(install_root=root)), \
                    patch.object(installation, 'verify_installed', side_effect=AssertionError('receipt must not authorize unrelated code')):
                with self.assertRaisesRegex(installation.InstallationError, 'external-installation-managed-externally'):
                    installation.require_managed_update(SimpleNamespace())

    def test_github_publication_refuses_a_development_candidate(self):
        from scripts.release.publish_release import assemble
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            gate = base / 'release-gate'
            gate.mkdir()
            commit = 'a' * 40
            (gate / 'release-gate.json').write_text(json.dumps({'version': '1.5.0.dev0', 'commit': commit, 'verified': True}))
            with self.assertRaisesRegex(ValueError, 'gate-identity-mismatch'):
                assemble(base, base / 'output', commit, '123', 'example/repository')

    def test_pypi_publication_refuses_a_verified_development_candidate(self):
        from scripts.release import prepare_pypi
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            gate_dir = base / 'release-gate'
            gate_dir.mkdir()
            commit = 'a' * 40
            gate = {'version': '1.5.0.dev0', 'commit': commit, 'verified': True}
            (gate_dir / 'release-gate.json').write_text(json.dumps(gate))
            with patch.object(prepare_pypi, 'verify', return_value=gate):
                with self.assertRaisesRegex(ValueError, 'development-version-publication-forbidden'):
                    prepare_pypi.prepare(base, base / 'output', commit, publishing=True)

    @unittest.skipUnless(sys.platform == 'linux', 'trusted Linux source and build paths')
    def test_standard_sdist_rebuilds_reviewed_wheel_outside_checkout(self):
        manifest = json.loads((ROOT / 'release-manifest.json').read_text())
        with tempfile.TemporaryDirectory(prefix='mihomoctl-sdist-test-') as temporary:
            base = Path(temporary)
            built = subprocess.run([sys.executable, '-m', 'build', '--sdist', '--no-isolation',
                                    '--outdir', str(base), str(ROOT)], capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stderr[-2000:])
            sdist = next(base.glob('*.tar.gz'))
            verify_sdist_inventory(sdist, manifest)
            with tarfile.open(sdist) as archive:
                archive.extractall(base / 'extracted')
            source = next((base / 'extracted').iterdir())
            built = subprocess.run([sys.executable, '-m', 'build', '--wheel', '--no-isolation',
                                    '--outdir', str(base), str(source)], capture_output=True, text=True, timeout=180)
            self.assertEqual(built.returncode, 0, built.stderr[-2000:])
            wheel = next(base.glob('*.whl'))
            verify_wheel_inventory(wheel, manifest)
