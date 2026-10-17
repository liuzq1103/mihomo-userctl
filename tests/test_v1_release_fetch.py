"""Acquisition exercises real release validators with a local official-channel fixture."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

from mihomoctl import release
from mihomoctl.scope import Scope
from scripts.release import build_offline_bundle
import test_v1_offline_bundle as offline_fixture


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() != 0, 'Linux user acquisition')
class FetchTests(unittest.TestCase):
    def setUp(self):
        fixture = offline_fixture.OfflineBundleTests('test_complete_kit_checksums_and_dependency_provenance')
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture = fixture
        self.base = fixture.base
        self.base.chmod(0o700)
        self.assets = fixture.artifacts
        self.commit = 'a' * 40
        self.env = patch.dict(os.environ, {key: str(self.base / name) for key, name in (
            ('HOME', 'home'), ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'),
            ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_RUNTIME_DIR', 'runtime'))})
        self.env.start()
        self.addCleanup(self.env.stop)
        for target in ('ubuntu22.04-x86_64-py310', 'ubuntu24.04-x86_64-py312'):
            build_offline_bundle.build(self.assets, fixture.wheelhouse, target, self.base / 'kits')
        for path in (self.base / 'kits').iterdir():
            shutil.copyfile(path, self.assets / path.name)
        self.gate = {'commit': self.commit, 'version': '1.0.0', 'verified': True,
                     'ubuntu': ['22.04', '24.04'], 'assets': sorted(p.name for p in self.assets.iterdir())}
        (self.assets / 'release-gate.json').write_text(json.dumps(self.gate))
        self.refresh_metadata()
        self.metadata_patch = patch.object(release, 'metadata', side_effect=lambda *_a, **_k: self.selected)
        self.transport_patch = patch.object(release, 'transfer', side_effect=self.transport)
        self.metadata_patch.start()
        self.transport_patch.start()
        self.addCleanup(self.metadata_patch.stop)
        self.addCleanup(self.transport_patch.stop)

    def refresh_metadata(self):
        self.selected = {'tag_name': 'v1.0.0', 'draft': False, 'prerelease': False,
                         'assets': [{'name': p.name, 'size': p.stat().st_size, 'state': 'uploaded',
                                     'digest': 'sha256:' + hashlib.sha256(p.read_bytes()).hexdigest(),
                                     'browser_download_url': release.WEB + '/releases/download/v1.0.0/' + p.name}
                                    for p in self.assets.iterdir()]}

    def transport(self, url, path, limit, timeout):
        if '/git/ref/tags/' in url:
            Path(path).write_text(json.dumps({'object': {'type': 'commit', 'sha': self.commit}}))
        else:
            shutil.copyfile(self.assets / url.rsplit('/', 1)[1], path)
        Path(path).chmod(0o600)

    def fetch(self, target=None):
        return release.fetch(Scope(), self.base / 'output', target=target)

    def test_normal_release_and_portable_record(self):
        result = self.fetch()
        self.assertEqual(result['version'], '1.0.0')
        self.assertTrue(Path(result['source']).is_file())
        record = json.loads((self.base / 'output/acquisition.json').read_text())
        self.assertFalse(Path(record['source']).is_absolute())
        self.assertIsNone(record['wheelhouse'])
        self.assertEqual((self.base / 'output').stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(release.ReleaseError, 'release-output-exists'):
            self.fetch()

    def test_both_offline_targets_include_dependencies(self):
        for index, target in enumerate(('ubuntu22.04-x86_64-py310', 'ubuntu24.04-x86_64-py312')):
            result = release.fetch(Scope(), self.base / ('output' + str(index)), target=target)
            self.assertTrue(Path(result['source']).is_file())
            self.assertEqual(len(list(Path(result['wheelhouse']).glob('*.whl'))), 1)

    def test_bad_gate_identity_and_receipt_fail_before_publication(self):
        for key, value in (('verified', False), ('commit', 'b' * 40), ('version', '9.0.0'), ('assets', [])):
            gate = dict(self.gate, **{key: value})
            (self.assets / 'release-gate.json').write_text(json.dumps(gate))
            self.refresh_metadata()
            with self.assertRaises(release.ReleaseError):
                self.fetch()
            self.assertFalse((self.base / 'output').exists())
        (self.assets / 'release-gate.json').write_text(json.dumps(self.gate))
        receipt = json.loads((self.assets / 'build-receipt.json').read_text())
        receipt['publishable'] = False
        (self.assets / 'build-receipt.json').write_text(json.dumps(receipt))
        self.refresh_metadata()
        with self.assertRaises(release.ReleaseError):
            self.fetch()

    def test_download_interruption_and_digest_mismatch_leave_no_result(self):
        with patch.object(release, 'transfer', side_effect=release.ReleaseError('release-network-unavailable')):
            with self.assertRaises(release.ReleaseError):
                self.fetch()
        row = next(r for r in self.selected['assets'] if r['name'] == 'release-gate.json')
        row['digest'] = 'sha256:' + '0' * 64
        with self.assertRaisesRegex(release.ReleaseError, 'digest-mismatch'):
            self.fetch()
        self.assertFalse((self.base / 'output').exists())
        self.assertEqual(list(self.base.glob('.mihomoctl-fetch-*')), [])

    def test_non_official_asset_and_existing_symlink_refused(self):
        self.selected['assets'][0]['browser_download_url'] = 'https://evil.example/asset'
        # Refuse when that asset is required (gate always required).
        next(row for row in self.selected['assets'] if row['name'] == 'release-gate.json')['browser_download_url'] = 'https://evil.example/gate'
        with self.assertRaises(release.ReleaseError):
            self.fetch()
        (self.base / 'output').symlink_to(self.base / 'missing', target_is_directory=True)
        with self.assertRaisesRegex(release.ReleaseError, 'release-output-exists'):
            self.fetch()

    def test_atomic_publication_never_replaces_racing_empty_directory(self):
        original = release._publish
        def race(stage, destination):
            destination.mkdir(mode=0o700)
            original(stage, destination)
        with patch.object(release, '_publish', side_effect=race):
            with self.assertRaisesRegex(release.ReleaseError, 'release-output-exists'):
                self.fetch()
        self.assertEqual(list((self.base / 'output').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
