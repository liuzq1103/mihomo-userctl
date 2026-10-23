"""Acquisition exercises real release validators with a local official-channel fixture."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
import zipfile
from unittest.mock import patch

from mihomoctl import release
from mihomoctl import installation
from mihomoctl.cli import main
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

    def portable_asset(self, commit=None):
        name = 'mihomoctl-1.0.0-portable-linux-x86_64'
        payload = {key: b'fixture component' for key in (
            'runtime/bin/python3', 'bin/mihomoctl', 'mihomoctl', 'install.sh',
            'lib/mihomoctl/cli.py', 'core/mihomo.gz', 'core/pin.json')}
        manifest = {'format': 1, 'kind': 'portable', 'version': '1.0.0',
                    'target': 'linux-x86_64', 'commit': commit or self.commit, 'publishable': True,
                    'files': {key: {'sha256': hashlib.sha256(body).hexdigest(), 'mode': 0o644}
                              for key, body in payload.items()}}
        payload['bundle-manifest.json'] = json.dumps(manifest).encode()
        path = self.assets / (name + '.tar.gz')
        with tarfile.open(path, 'w:gz') as archive:
            for key, body in payload.items():
                info = tarfile.TarInfo(name + '/' + key)
                info.size, info.mode = len(body), 0o644
                archive.addfile(info, io.BytesIO(body))
        path.with_name(path.name + '.sha256').write_text(
            hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n')
        self.gate['assets'] = sorted(p.name for p in self.assets.iterdir())
        (self.assets / 'release-gate.json').write_text(json.dumps(self.gate))
        self.refresh_metadata()
        return path

    def test_complete_portable_acquisition_checks_inventory_and_publishes_relative_source(self):
        asset = self.portable_asset()
        result = self.fetch('linux-x86_64')
        self.assertIsNone(result['wheelhouse'])
        self.assertEqual(Path(result['source']).read_bytes(), asset.read_bytes())
        record = json.loads((self.base / 'output/acquisition.json').read_text())
        self.assertEqual(record['source'], asset.name)
        self.assertEqual(record['commit'], self.commit)

    def test_complete_portable_identity_mismatch_never_publishes(self):
        self.portable_asset(commit='b' * 40)
        with self.assertRaisesRegex(release.ReleaseError, 'release-bundle-identity-mismatch'):
            self.fetch('linux-x86_64')
        self.assertFalse((self.base / 'output').exists())

    def test_complete_portable_acquisition_with_implicit_directories_and_shared_umask(self):
        # portable_asset deliberately has files only, with no directory entries.
        asset = self.portable_asset()
        previous = os.umask(0o002)
        try:
            result = self.fetch('linux-x86_64')
            current = os.umask(0o002)
            self.assertEqual(current, 0o002, 'acquisition must preserve the caller umask')
        finally:
            os.umask(previous)
        self.assertEqual(Path(result['source']).read_bytes(), asset.read_bytes())
        self.assertEqual(Path(result['output_dir']).stat().st_mode & 0o777, 0o700)

    def test_portable_latest_keeps_acquisition_contract_without_host_python(self):
        self.portable_asset()
        def update(scope, source, **options):
            self.assertTrue(Path(source).is_file())
            self.assertEqual(options, {})
            return {'version': '1.0.0', 'source_kind': 'portable-bundle',
                    'generation': 'f' * 32, 'python': '/bundled/python', 'replaced': 'generations/previous'}
        with patch.object(installation, 'current_record', return_value={'source_kind': 'portable-bundle'}), \
                patch.object(installation, 'verify_installed', return_value={'version': '0.9.0'}), \
                patch.object(installation, 'resolve_python', side_effect=AssertionError('host Python must not be used')), \
                patch.object(installation, 'update', side_effect=update):
            result = release.update_latest(Scope())
        self.assertTrue(result['changed'])
        self.assertEqual(result['acquisition']['target'], 'linux-x86_64')
        self.assertEqual(result['acquisition']['commit'], self.commit)
        self.assertEqual(result['python'], '/bundled/python')

    def test_readable_nonwritable_parent_is_safe_and_not_changed(self):
        self.base.chmod(0o755)
        result = self.fetch()
        self.assertEqual(self.base.stat().st_mode & 0o777, 0o755)
        self.assertEqual(Path(result['output_dir']).stat().st_mode & 0o777, 0o700)

    def test_group_writable_parent_is_refused_without_download(self):
        self.base.chmod(0o770)
        with patch.object(release, 'metadata', side_effect=AssertionError('untrusted parent')):
            with self.assertRaises(Exception):
                self.fetch()
        self.assertFalse((self.base / 'output').exists())

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

    def test_deep_artifact_json_is_invalid_not_a_crash(self):
        for name in ('build-receipt.json', 'release-gate.json'):
            with self.subTest(name=name):
                (self.assets / name).write_text('[' * 100000)
                self.refresh_metadata()
                with self.assertRaisesRegex(release.ReleaseError,
                                            'release-artifact-invalid|release-metadata-invalid'):
                    self.fetch()
                self.assertFalse((self.base / 'output').exists())
        (self.assets / 'build-receipt.json').unlink()
        self.refresh_metadata()
        with self.assertRaises(release.ReleaseError):
            self.fetch()

    def rehash_release(self):
        receipt = json.loads((self.assets / 'build-receipt.json').read_text())
        receipt['sha256'] = {name: hashlib.sha256((self.assets / name).read_bytes()).hexdigest()
                             for name in receipt['sha256']}
        (self.assets / 'build-receipt.json').write_text(json.dumps(receipt))
        (self.assets / 'SHA256SUMS').write_text(''.join(receipt['sha256'][name] + '  ' + name + '\n'
                                                      for name in sorted(receipt['sha256'])))
        self.refresh_metadata()

    def test_rehashed_zip_cannot_disagree_with_source_tar(self):
        archive = self.assets / 'mihomoctl-1.0.0.zip'
        with zipfile.ZipFile(archive) as package:
            payload = {name: package.read(name) for name in package.namelist()}
        payload['mihomoctl-1.0.0/docs/guide.md'] = b'different release content\n'
        with zipfile.ZipFile(archive, 'w') as package:
            for name, body in payload.items():
                package.writestr(name, body)
        self.rehash_release()
        with self.assertRaisesRegex(release.ReleaseError, 'release-source-formats-disagree'):
            self.fetch()

    def test_rehashed_wheel_cannot_disagree_with_source_runtime(self):
        from test_v1_installation import build_wheel
        runtime = {name: (self.fixture.source / name).read_bytes()
                   for name in self.fixture.manifest['inventory']['runtime_files']}
        runtime['mihomoctl/cli.py'] += b'\n# different wheel code\n'
        build_wheel(self.assets, files=runtime)
        self.rehash_release()
        with self.assertRaisesRegex(release.ReleaseError, 'release-wheel-source-disagree'):
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

    def installed_fixture(self):
        from test_v1_installation import write_source
        old = write_source(self.base / 'old', version='0.9.9')
        installation.install(Scope(), old, wheelhouse=self.fixture.wheelhouse,
                             python=sys.executable)
        protected = {}
        for root, names in ((Scope().config_root, ('manager.yaml', 'profiles/credentials.yaml', 'subscription.yaml')),
                            (Scope().cache_root, ('existing-cache',)),
                            (Scope().data_root, ('cores/mihomo', 'core-home/config.yaml'))):
            for name in names:
                path = root / name
                # mkdir(parents=True) would create intermediate scope roots with
                # the ambient umask; every level must be private from creation.
                missing = []
                cursor = path.parent
                while not cursor.exists():
                    missing.append(cursor)
                    cursor = cursor.parent
                for component in reversed(missing):
                    component.mkdir(mode=0o700)
                path.write_bytes(('private fixture ' + name).encode())
                path.chmod(0o600)
                protected[path] = path.read_bytes()
        return protected

    def test_latest_updates_and_self_contained_rollback_preserve_data_and_process(self):
        protected = self.installed_fixture()
        process = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
        self.addCleanup(lambda: process.poll() is None and process.terminate())
        identity = Path('/proc/%s/stat' % process.pid).read_text().split()[21]
        with patch.object(release, 'matching_target', return_value=self.fixture.target):
            result = release.update_latest(Scope(), python=sys.executable)
        self.assertTrue(result['changed'])
        self.assertEqual(installation.verify_installed(Scope())['version'], '1.0.0')
        self.assertEqual(list((Scope().cache_root / 'release-acquisition').iterdir()), [])
        shutil.rmtree(self.assets)
        self.assertNotIn('backup', result)
        self.assertEqual(list(installation.InstallPaths(Scope()).backups_root.iterdir()), [])
        self.assertEqual(installation.verify_installed(Scope())['version'], '1.0.0')
        self.assertIsNone(process.poll())
        self.assertEqual(Path('/proc/%s/stat' % process.pid).read_text().split()[21], identity)
        for path, content in protected.items():
            self.assertEqual(path.read_bytes(), content)

    def test_latest_dry_run_and_post_switch_failure_leave_old_installation(self):
        protected = self.installed_fixture()
        old = installation.verify_installed(Scope())
        with patch.object(release, 'matching_target', return_value=self.fixture.target):
            result = release.update_latest(Scope(), python=sys.executable, dry_run=True)
            self.assertFalse(result['changed'])
            self.assertEqual(installation.verify_installed(Scope())['generation'], old['generation'])
            original = installation._ensure_launcher
            failed = False
            def fail_once(paths):
                nonlocal failed
                if not failed:
                    failed = True
                    raise OSError('injected activation failure')
                return original(paths)
            with patch.object(installation, '_ensure_launcher', side_effect=fail_once):
                with self.assertRaisesRegex(installation.InstallationError, 'installation-failed-rolled-back'):
                    release.update_latest(Scope(), python=sys.executable)
        self.assertEqual(installation.verify_installed(Scope())['generation'], old['generation'])
        for path, content in protected.items():
            self.assertEqual(path.read_bytes(), content)

    def test_latest_uses_explicit_wheelhouse_and_no_newer_is_noop(self):
        self.installed_fixture()
        with patch.object(release, 'matching_target', side_effect=AssertionError('target selection')):
            result = release.update_latest(Scope(), wheelhouse=str(self.fixture.wheelhouse), python=sys.executable)
        self.assertIsNone(result['acquisition']['target'])
        with patch.object(release, 'fetch', side_effect=AssertionError('unexpected fetch')):
            result = release.update_latest(Scope())
            self.assertFalse(result['changed'])
        self.assertNotIn('latest', json.dumps(result).lower())

    def test_cli_single_command_upgrades_using_existing_transaction(self):
        import contextlib
        import io
        self.installed_fixture()
        with patch.object(release, 'matching_target', return_value=self.fixture.target), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['update', '--latest', '--python', sys.executable, '--json']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['command'], 'update')
        self.assertEqual(result['overall'], 'PASS')
        self.assertTrue(result['data']['changed'])
        self.assertEqual(installation.verify_installed(Scope())['version'], '1.0.0')

    def test_transferred_acquisition_installs_offline_at_new_location(self):
        result = self.fetch(self.fixture.target)
        transferred = self.base / 'another-machine'
        shutil.move(result['output_dir'], transferred)
        record = json.loads((transferred / 'acquisition.json').read_text())
        with patch.object(release, 'transfer', side_effect=AssertionError('offline install used network')):
            installation.install(Scope(), transferred / record['source'],
                                 wheelhouse=transferred / record['wheelhouse'], python=sys.executable)
        self.assertEqual(installation.verify_installed(Scope())['version'], '1.0.0')

    def test_cli_latest_and_explicit_source_exclusive_and_missing_source_unchanged(self):
        import contextlib
        import io
        for args, code in ((['update', '--latest', '/source'], 'usage-error'),
                           (['update'], 'update-source-required')):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main([*args, '--json']), 2)
            self.assertEqual(json.loads(output.getvalue())['errors'][0]['code'], code)


if __name__ == '__main__':
    unittest.main()
