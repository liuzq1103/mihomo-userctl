"""Isolation, resource trust and process-local validation proof regressions."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mihomoctl.errors import ConfigError, StateError, ValidationError
from mihomoctl.lifecycle import runner


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        self.binary = self.root / 'core'
        shutil.copyfile('/usr/bin/true', self.binary)
        self.binary.chmod(0o700)
        self.config = 'rules: [MATCH,DIRECT]\n'

    def resource(self, name, value=b'trusted-cache'):
        p = self.home / name
        p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        p.write_bytes(value)
        p.chmod(0o600)
        return p

    def validate(self, text=None):
        return runner.validate_config(self.binary, text or self.config, self.home)

    def test_only_needed_trusted_resources_are_copied_and_live_files_untouched(self):
        geo = self.resource('geoip.metadb')
        provider = self.resource('providers/sub.yaml', b'proxies: []\n')
        live_cache=self.resource('cache.db', b'PRIVATE-SELECTION')
        live_bytes=live_cache.read_bytes()
        before_cache=live_cache.stat()
        self.resource('secret-file', b'PRIVATE-CREDENTIAL')
        candidate = 'proxy-providers:\n  subscription:\n    type: file\n    path: providers/sub.yaml\n'
        staging_paths = []
        def core(_binary, args, **kwargs):
            stage = Path(args[2]); staging_paths.append(stage)
            self.assertNotEqual(stage, self.home)
            self.assertEqual((stage / 'geoip.metadb').read_bytes(), geo.read_bytes())
            self.assertEqual((stage / 'providers/sub.yaml').read_bytes(), provider.read_bytes())
            self.assertFalse((stage / 'cache.db').exists())
            self.assertFalse((stage / 'secret-file').exists())
            (stage / 'geoip.metadb').write_bytes(b'core-writes-isolated-copy')
            self.assertNotIn(str(self.home), kwargs['input_text'])
            return subprocess.CompletedProcess([], 0)
        with patch.object(runner, 'run_core', side_effect=core):
            self.assertTrue(self.validate(candidate))
        self.assertEqual(geo.read_bytes(), b'trusted-cache')
        self.assertEqual(live_cache.read_bytes(),live_bytes)
        after_cache=live_cache.stat()
        for field in ('st_ino','st_size','st_uid','st_gid','st_mode','st_mtime_ns','st_ctime_ns','st_nlink'):
            self.assertEqual(getattr(before_cache,field),getattr(after_cache,field))
        self.assertFalse(staging_paths[0].exists())

    def test_missing_cache_and_timeout_report_safe_stage_and_timing(self):
        for failure in (StateError('core-timeout', 'raw-secret-URL'), subprocess.CompletedProcess([], 1)):
            with self.subTest(failure=type(failure).__name__):
                with patch.object(runner, 'run_core', side_effect=failure if isinstance(failure, Exception) else None,
                                  return_value=failure):
                    with self.assertRaises((StateError, ValidationError)) as caught:
                        self.validate()
                detail = caught.exception.detail
                self.assertIn('stage=core-validation', detail)
                self.assertIn('elapsed_ms=', detail)
                self.assertIn('cache_files=0', detail)
                self.assertNotIn('raw-secret', str(caught.exception))
                self.assertIn('geo_cache_files=0',detail)
                self.assertIn('provider_cache_files=0',detail)
        config='proxy-providers: {p: {type: file, path: providers/missing.yaml}}\n'
        with patch.object(runner,'run_core',side_effect=StateError('core-timeout')),self.assertRaises(StateError) as caught:
            self.validate(config)
        self.assertIn('provider_cache_missing=1',caught.exception.detail)
        self.assertNotIn('providers/missing',caught.exception.detail)

    def test_untrusted_links_permissions_and_cross_identity_refused_before_core(self):
        file = self.resource('GeoSite.dat')
        for attack in ('writable', 'symlink', 'hardlink', 'foreign-owner'):
            with self.subTest(attack=attack):
                file.unlink(missing_ok=True)
                file = self.resource('GeoSite.dat')
                if attack == 'writable': file.chmod(0o664)
                elif attack == 'symlink':
                    file.unlink(); file.symlink_to(self.resource('other'))
                elif attack == 'hardlink': os.link(file, self.home / 'hardlink')
                with patch.object(runner, 'run_core') as run:
                    with self.assertRaises((ValidationError, ConfigError)):
                        if attack == 'foreign-owner':
                            runner._trusted_bytes(file, {os.getuid() + 10000})
                        else: self.validate()
                run.assert_not_called()

    def test_resource_outside_home_is_never_used(self):
        for path in ('../secret', '/etc/passwd', 'cache.db', 'GeoSite.dat'):
            with self.subTest(path=path), patch.object(runner, 'run_core') as run:
                with self.assertRaisesRegex(ValidationError, 'validation-resource-path-unsafe'):
                    self.validate('proxy-providers:\n  p: {type: file, path: ' + path + '}\n')
                run.assert_not_called()

    def test_malformed_provider_paths_have_safe_controlled_diagnostics(self):
        import yaml
        for path in ('providers/secret\0.yaml', 'providers/\ud800.yaml'):
            candidate=yaml.safe_dump({'proxy-providers':{'p':{'type':'file','path':path}}})
            with self.subTest(path=repr(path)), patch.object(runner,'run_core') as run:
                with self.assertRaises(ValidationError) as caught: self.validate(candidate)
                self.assertEqual(caught.exception.code,'validation-resource-path-unsafe')
                self.assertIn('stage=cache-check',caught.exception.detail)
                self.assertIn('elapsed_ms=',caught.exception.detail)
                self.assertNotIn('secret',str(caught.exception))
                run.assert_not_called()

    def test_invalid_home_binary_and_wrong_uid_are_rejected_safely(self):
        for path in ('/tmp/secret\0', '/tmp/\ud800'):
            for binary, home in ((path,self.home),(self.binary,path)):
                with patch.object(runner,'run_core') as run, self.assertRaises(ValidationError) as caught:
                    runner.validate_config(binary,self.config,home)
                self.assertEqual(caught.exception.code,'validation-resource-path-unsafe')
                self.assertIn('stage=cache-check',caught.exception.detail)
                self.assertNotIn('secret',str(caught.exception));run.assert_not_called()
        with patch.object(runner,'run_core') as run, self.assertRaisesRegex(ValidationError,'validation-identity-mismatch'):
            runner.validate_config(self.binary,self.config,self.home,as_uid=os.geteuid()+10000)
        run.assert_not_called()

    def test_invalid_utf8_core_output_never_escapes_safe_diagnostics(self):
        self.binary.write_text("#!/bin/sh\nprintf '\\377PRIVATE-SECRET' >&2\nexit 1\n")
        with self.assertRaises(ValidationError) as caught:self.validate()
        self.assertEqual(caught.exception.code,'core-config-invalid')
        self.assertIn('stage=core-validation',caught.exception.detail)
        self.assertNotIn('PRIVATE-SECRET',str(caught.exception))

    def test_home_bound_capacity_and_incomplete_dependencies(self):
        cache = {}
        with runner.validation_session(cache), patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)) as run:
            self.validate()
            other=self.root/'other-home';other.mkdir(mode=0o700)
            runner.validate_config(self.binary,self.config,other)
            self.assertEqual(run.call_count,2)
            for i in range(12):
                self.validate(self.config+'# '+str(i)+'\n')
                self.assertLessEqual(len(cache),4)
        for config in ('proxy-providers: {p: {type: http, url: "https://example.test/private"}}\n',
                       'proxy-providers: {p: {type: file, path: providers/missing.yaml}}\n'):
            with runner.validation_session() as _unused, patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)) as run:
                self.validate(config);self.validate(config);self.assertEqual(run.call_count,2)
        def download(_binary,args,**kwargs):
            (Path(args[2])/'GeoSite.dat').write_bytes(b'downloaded')
            return subprocess.CompletedProcess([],0)
        with runner.validation_session(), patch.object(runner,'run_core',side_effect=download) as run:
            self.validate();self.validate();self.assertEqual(run.call_count,2)

    def test_reuse_bound_to_candidate_binary_resources_and_timeout(self):
        geo = self.resource('geoip.metadb')
        with patch.object(runner, 'run_core', return_value=subprocess.CompletedProcess([], 0)) as run:
            with runner.validation_session():
                self.validate(); self.validate()
                self.assertEqual(run.call_count, 1)
                self.validate(self.config + '# changed bytes\n')
                self.assertEqual(run.call_count, 2)
                geo.write_bytes(b'new-database')
                self.validate(); self.assertEqual(run.call_count, 3)
                self.binary.write_bytes(self.binary.read_bytes() + b'new-core')
                self.validate(); self.assertEqual(run.call_count, 4)
                runner.validate_config(self.binary, self.config, self.home, timeout=61)
                self.assertEqual(run.call_count, 5)
            self.validate(); self.assertEqual(run.call_count, 6)

    def test_changing_dependency_during_validation_cannot_create_proof(self):
        geo = self.resource('GeoSite.dat')
        def core(*args, **kwargs):
            geo.write_bytes(b'changed')
            return subprocess.CompletedProcess([], 0)
        with runner.validation_session(), patch.object(runner, 'run_core', side_effect=core):
            with self.assertRaisesRegex(ValidationError, 'validation-inputs-changed'):
                self.validate()

    def test_replaced_parent_cannot_redirect_a_trusted_read(self):
        cache = self.resource('providers/sub.yaml', b'original')
        elsewhere = self.root / 'elsewhere'; elsewhere.mkdir(mode=0o700)
        (elsewhere / 'sub.yaml').write_bytes(b'not-the-checked-directory')
        original_open = os.open
        swapped = []
        def replace_parent(name, *args, **kwargs):
            descriptor = original_open(name, *args, **kwargs)
            if name == 'providers' and kwargs.get('dir_fd') is not None and not swapped:
                cache.parent.rename(self.home / 'pinned-original')
                cache.parent.symlink_to(elsewhere, target_is_directory=True)
                swapped.append(True)
            return descriptor
        with patch.object(os, 'open', side_effect=replace_parent):
            self.assertEqual(runner._trusted_bytes(cache, {0, os.getuid()}), b'original')
        self.assertTrue(swapped)
        with self.assertRaises(OSError):
            runner._trusted_bytes(cache, {0, os.getuid()})

    def test_core_modified_seeded_resources_never_create_reusable_proof(self):
        self.resource('GeoSite.dat')
        for mutation in ('modify', 'delete', 'symlink'):
            def core(_binary, args, **kwargs):
                target = Path(args[2]) / 'GeoSite.dat'
                if mutation == 'modify': target.write_bytes(b'downloaded replacement')
                elif mutation == 'delete': target.unlink()
                else:
                    target.unlink(); target.symlink_to(self.home / 'GeoSite.dat')
                return subprocess.CompletedProcess([], 0)
            with self.subTest(mutation=mutation), runner.validation_session(), \
                    patch.object(runner, 'run_core', side_effect=core) as run:
                self.validate(); self.validate()
                self.assertEqual(run.call_count, 2)

    def test_both_restart_backends_reuse_once_and_reject_disk_changes_before_stop(self):
        from mihomoctl.lifecycle import process, systemd
        config = self.root/'config.yaml'; config.write_text(self.config); config.chmod(0o600)
        manager = SimpleNamespace(core=SimpleNamespace(binary=str(self.binary), config=str(config)))
        scope = SimpleNamespace(core_home=self.home, system=False)
        for kind in (process.ProcessBackend, systemd.SystemdBackend):
            backend = kind(scope, manager, [], None)
            def start(**kwargs):
                return runner.validate_config(self.binary, config.read_text(), self.home)
            with self.subTest(backend=kind.__name__), \
                    patch.object(backend, 'running_identity', return_value=None), \
                    patch.object(systemd.SystemdBackend, '_require_owned_unit', return_value={'ActiveState':'inactive'}), \
                    patch.object(backend, 'stop') as stop, patch.object(backend, 'start', side_effect=start), \
                    patch.object(runner, 'run_core', return_value=subprocess.CompletedProcess([],0)) as run:
                backend.restart()
                self.assertEqual(run.call_count, 1)
                stop.assert_called_once()
            config.write_text(self.config)
            def mutate(*args, **kwargs):
                config.write_text(self.config+'# changed during validation\n')
                return subprocess.CompletedProcess([],0)
            with self.subTest(changed_backend=kind.__name__), \
                    patch.object(backend, 'running_identity', return_value=None), \
                    patch.object(systemd.SystemdBackend, '_require_owned_unit', return_value={'ActiveState':'inactive'}), \
                    patch.object(backend, 'stop') as stop, \
                    patch.object(runner, 'run_core', side_effect=mutate):
                with self.assertRaisesRegex(StateError, 'config-changed-after-validation'):
                    backend.restart()
                stop.assert_not_called()
            config.write_text(self.config)

    def test_post_validation_binary_and_dependency_drift_is_rejected_before_stop(self):
        from mihomoctl.lifecycle import process,systemd
        geo=self.resource('GeoSite.dat');provider=self.resource('providers/sub.yaml',b'proxies: []\n')
        text='proxy-providers: {p: {type: file, path: providers/sub.yaml}}\n'
        config=self.root/'config.yaml';config.write_text(text);config.chmod(0o600)
        manager=SimpleNamespace(core=SimpleNamespace(binary=str(self.binary),config=str(config)))
        scope=SimpleNamespace(core_home=self.home,system=False)
        original=runner.validate_config
        for kind in (process.ProcessBackend,systemd.SystemdBackend):
            for resource in (self.binary,geo,provider):
                backend=kind(scope,manager,[],None)
                def after_validation(*args,**kwargs):
                    proof=original(*args,**kwargs)
                    resource.write_bytes(resource.read_bytes()+b'changed-after-validation')
                    return proof
                with self.subTest(backend=kind.__name__,resource=resource.name), \
                        patch.object(backend,'running_identity',return_value=None), \
                        patch.object(systemd.SystemdBackend,'_require_owned_unit',return_value={'ActiveState':'inactive'}), \
                        patch.object(runner,'validate_config',side_effect=after_validation), \
                        patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)),patch.object(backend,'stop') as stop:
                    with self.assertRaisesRegex(ValidationError,'validation-inputs-changed') as caught:backend.restart()
                stop.assert_not_called();self.assertIn('stage=activation-boundary',caught.exception.detail)


if __name__ == '__main__':
    unittest.main()
