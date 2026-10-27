"""Safe permission details and recovery before/after runtime transitions."""
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from mihomoctl.controller import files
from mihomoctl.controller.controller_config import private
from mihomoctl.controller.controller_state import Store, Snapshot
from mihomoctl.errors import MihomoctlError, RollbackFailedError, ValidationError
from mihomoctl.scope import Scope
from mihomoctl import transaction
from mihomoctl.trust import require_private_dir


class SaveRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'HOME':str(self.root), 'XDG_CONFIG_HOME':str(self.root/'config'),
            'XDG_DATA_HOME':str(self.root/'data'), 'XDG_STATE_HOME':str(self.root/'state'),
            'XDG_CACHE_HOME':str(self.root/'cache'), 'XDG_RUNTIME_DIR':str(self.root/'run')})
        env.start(); self.addCleanup(env.stop)
        self.scope = Scope(system=False)
        require_private_dir(self.scope.config_root, create=True)
        self.config = self.scope.config_root/'core.yaml'
        self.config.write_bytes(b'old config\n'); self.config.chmod(0o600)

    def test_664_reason_and_hint_survive_store_without_file_contents(self):
        self.config.write_text('PRIVATE-PASSWORD'); self.config.chmod(0o664)
        with self.assertRaises(files.InstallError) as caught: private(self.config)
        self.assertEqual(caught.exception.code, 'path-is-writable-by-group-or-others')
        store = Store(workers=1); self.addCleanup(store.close)
        def fail(): raise caught.exception
        store.pending['operation'] = 1
        store.state.snapshots['operation'] = Snapshot()
        store._run('operation', 1, fail)
        snap = store.state.snapshots['operation']
        self.assertIn('chmod 600', snap.error_message)
        self.assertNotIn('PRIVATE-PASSWORD', snap.error_message)
        self.config.chmod(0o600); self.assertEqual(private(self.config), self.config)

    def test_unsafe_ancestor_and_symlink_have_specific_reasons(self):
        parent = self.root/'unsafe'; parent.mkdir(mode=0o777); parent.chmod(0o777)
        p = parent/'script.js'; p.write_text('PRIVATE'); p.chmod(0o600)
        with self.assertRaisesRegex(files.InstallError, 'unsafe-writable-path-ancestor'): private(p)
        link = self.root/'link'; link.symlink_to(self.config)
        with self.assertRaisesRegex(files.InstallError, 'symlink-path-not-supported'): private(link)

    def test_validation_failure_after_file_save_never_stops_untouched_old_core(self):
        def action(tx):
            tx.runtime = {'was_running':True, 'phase':'prepared'}; tx._persist()
            tx.write_text(self.config, 'new config\n')
            raise ValidationError('core-timeout')
        with patch.object(transaction, '_runtime_backend') as backend:
            with self.assertRaisesRegex(ValidationError, 'core-timeout'):
                transaction.run_transaction(self.scope, 'policy-activate', action)
        backend.assert_not_called()
        self.assertEqual(self.config.read_bytes(), b'old config\n')
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])

    def test_runtime_restore_observes_restored_config_before_restart(self):
        backend = Mock(); backend.status.return_value = {'running':False}
        app = Mock()
        def verified(*args,**kwargs):
            self.assertEqual(self.config.read_bytes(), b'old config\n')
            return {'overall':'PASS','runtime':{'running':True}}
        app.lifecycle.side_effect = verified
        def action(tx):
            tx.runtime = {'was_running':True, 'phase':'starting'}; tx._persist()
            tx.write_text(self.config, 'new config\n')
            raise ValidationError('start-not-verified')
        with patch.object(transaction, '_runtime_backend', return_value=(app, backend)):
            with self.assertRaisesRegex(ValidationError, 'start-not-verified'):
                transaction.run_transaction(self.scope, 'policy-activate', action)
        backend.stop.assert_not_called()
        app.lifecycle.assert_called_once_with('start', _locked=True, _transaction=unittest.mock.ANY)

    def test_lock_reasons_and_passthrough_bridge_preserve_safe_hints(self):
        from mihomoctl import bridge
        from mihomoctl.controller import controller
        for code in ('invalid-inherited-lock','another-install-update-or-uninstall-is-running'):
            error=files.InstallError(code)
            self.assertEqual(error.code,code)
            self.assertTrue(error.safe_detail)
        with patch.dict(os.environ,{'MIHOMO_INSTALL_LOCK_FD':'-1'}):
            with self.assertRaisesRegex(files.InstallError,'invalid-inherited-lock'):
                with files.locked(self.root): pass
        with patch.object(controller,'main',side_effect=files.InstallError('path-is-writable-by-group-or-others')):
            with self.assertRaises(bridge.BridgeError) as caught: bridge._run_bridge(self.scope,['tui'])
        self.assertEqual(caught.exception.code,'path-is-writable-by-group-or-others')
        self.assertIn('chmod 600',caught.exception.detail)

    def test_inherited_unlocked_descriptor_really_serializes_operations(self):
        import fcntl
        directory=self.root/'mihomo-userctl-lock';directory.mkdir(mode=0o700)
        path=directory/'operation.lock';path.touch(mode=0o600)
        first=os.open(path,os.O_RDWR);second=os.open(path,os.O_RDWR)
        try:
            with patch.dict(os.environ,{'MIHOMO_INSTALL_LOCK_FD':str(first)}), files.locked(self.root):
                with self.assertRaises(BlockingIOError): fcntl.flock(second,fcntl.LOCK_EX|fcntl.LOCK_NB)
        finally: os.close(first);os.close(second)

    def test_directory_publication_and_deletion_refuse_before_journaling(self):
        folder=self.scope.config_root/'keep';folder.mkdir(mode=0o750)
        child=folder/'secret';child.write_bytes(b'preserved');child.chmod(0o600)
        before=folder.stat()
        tx=transaction.Transaction(self.scope,'test')
        with self.assertRaisesRegex(MihomoctlError,'refuse-non-file-destination'):
            tx.write_text(folder,'new')
        with self.assertRaisesRegex(MihomoctlError,'refuse-directory-delete'):tx.delete(folder)
        self.assertEqual(tx.journal,[]);tx.rollback()
        after=folder.stat()
        self.assertEqual((before.st_ino,before.st_uid,before.st_gid,before.st_mode),(after.st_ino,after.st_uid,after.st_gid,after.st_mode))
        self.assertEqual(child.read_bytes(),b'preserved')

    def test_cli_service_install_migrates_exact_legacy_without_bypassing_security_or_lock(self):
        from mihomoctl import cli
        from mihomoctl.config import Manager,CoreSettings
        from mihomoctl.lifecycle import systemd
        from mihomoctl.errors import StateError
        import contextlib,io
        manager=Manager(core=CoreSettings('/fixture/core',str(self.config),'systemd'))
        unit=systemd.unit_path(self.scope);unit.parent.mkdir(parents=True,mode=0o700)
        current=systemd.unit_text(manager,self.scope)
        legacy=current.replace(systemd.CORE_ENVIRONMENT,systemd.LEGACY_CORE_ENVIRONMENT)
        self.scope.manager_path.write_text('manager bytes stay unchanged\n');self.scope.manager_path.chmod(0o600)
        app=Mock(scope=self.scope);app.resolve.return_value=(manager,[],None,None,{})
        for kind in ('legacy','drift','unsafe','current'):
            text=legacy if kind in ('legacy','unsafe') else current+'# manual change\n' if kind=='drift' else current
            unit.write_text(text);unit.chmod(0o664 if kind=='unsafe' else 0o600)
            inode=unit.stat().st_ino
            def require_current():
                self.assertEqual(unit.read_text(),current)
                self.assertTrue(list(self.scope.backups_root.glob('*/journal.json')),'CLI fast path bypassed operation transaction')
            with self.subTest(kind=kind),patch.object(systemd,'systemd_available',return_value=True), \
                    patch.object(systemd,'_systemctl') as control, \
                    patch.object(systemd.SystemdBackend,'_require_owned_unit',side_effect=require_current), \
                    contextlib.redirect_stdout(io.StringIO()):
                if kind in ('drift','unsafe'):
                    with self.assertRaisesRegex(StateError,'unit-drifted' if kind=='drift' else 'unit-not-managed'):
                        cli.cmd_service(app,['install'],True)
                    control.assert_not_called();self.assertEqual(unit.read_text(),text)
                else:
                    cli.cmd_service(app,['install'],True)
                    self.assertEqual(unit.read_text(),current)
                    if kind=='legacy':control.assert_called_once_with(self.scope,'daemon-reload')
                    else:control.assert_not_called();self.assertEqual(unit.stat().st_ino,inode)
            self.assertEqual(self.scope.manager_path.read_text(),'manager bytes stay unchanged\n')
            self.assertFalse(list(self.scope.backups_root.glob('*/journal.json')))
        app.lifecycle.assert_not_called()

    def test_failed_recovery_start_tracks_unknown_identity_and_never_starts_twice(self):
        tx=transaction.Transaction(self.scope,'policy-activate')
        tx.runtime={'was_running':True};tx._persist();tx.write_text(self.config,'new config\n')
        backend=Mock();backend.status.return_value={'running':False}
        app=Mock()
        def failed_start(*args,**kwargs):
            tracked=kwargs['_transaction']
            tracked.runtime['phase']='unverified';tracked._persist('restored')
            raise RollbackFailedError('start-cleanup-failed')
        app.lifecycle.side_effect=failed_start
        with patch.object(transaction,'_runtime_backend',return_value=(app,backend)):
            with self.assertRaises(RollbackFailedError):transaction.recover_transactions(self.scope)
            self.assertTrue(tx.backup_root.exists())
            with self.assertRaises(RollbackFailedError):transaction.recover_transactions(self.scope)
        app.lifecycle.assert_called_once()

    def test_process_unknown_identity_persists_marker_before_spawn_and_refuses_signal(self):
        from mihomoctl.lifecycle import process
        from mihomoctl.config import Manager,CoreSettings
        from mihomoctl.errors import StateError
        self.config.write_text('rules: ["MATCH,DIRECT"]\n')
        backend=process.ProcessBackend(self.scope,Manager(core=CoreSettings('/core',str(self.config),'process')),[],None)
        tx=transaction.Transaction(self.scope,'policy-activate');tx.runtime={'was_running':False,'phase':'prepared'};tx._persist()
        child=Mock(pid=123456);child.poll.return_value=None
        def transition(phase):tx.runtime['phase']=phase;tx._persist()
        def spawn(*args,**kwargs):
            self.assertEqual(tx.runtime['phase'],'unverified');return child
        with patch.object(backend,'running_identity',return_value=None),patch.object(process,'require_executable_file'), \
                patch.object(process.runner,'validate_config'),patch.object(process.subprocess,'Popen',side_effect=spawn), \
                patch.object(process.ident,'read_identity',side_effect=StateError('identity-unavailable')), \
                patch.object(process.ident,'stop') as stop:
            with self.assertRaisesRegex(RollbackFailedError,'start-cleanup-failed'):
                backend.start(runtime_transition=transition)
        self.assertEqual(tx.runtime['phase'],'unverified');stop.assert_not_called();child.kill.assert_not_called()
        self.assertFalse(self.scope.runtime_state.exists());self.assertTrue(tx.backup_root.exists())

    def test_systemd_unknown_active_unit_keeps_unknown_phase_without_stop(self):
        from mihomoctl.lifecycle import systemd
        from mihomoctl.config import Manager,CoreSettings
        self.config.write_text('rules: ["MATCH,DIRECT"]\n')
        unit=systemd.unit_path(self.scope);unit.parent.mkdir(parents=True,mode=0o700);unit.touch(mode=0o600)
        backend=systemd.SystemdBackend(self.scope,Manager(core=CoreSettings('/core',str(self.config),'systemd')),[],None)
        tx=transaction.Transaction(self.scope,'policy-activate');tx.runtime={'was_running':False,'phase':'prepared'};tx._persist()
        def transition(phase):tx.runtime['phase']=phase;tx._persist()
        def start(*args,**kwargs):self.assertEqual(tx.runtime['phase'],'unverified')
        with patch.object(backend,'_require_owned_unit',return_value={'ActiveState':'inactive'}), \
                patch.object(backend,'running',return_value=(False,{})),patch.object(backend,'running_identity',return_value=None), \
                patch.object(backend,'_main_pid',side_effect=[{'ActiveState':'inactive'},{'ActiveState':'active'}]), \
                patch.object(systemd,'require_executable_file'),patch.object(systemd.runner,'validate_config'), \
                patch.object(systemd,'_systemctl',side_effect=start),patch.object(backend,'stop') as stop:
            with self.assertRaisesRegex(MihomoctlError,'service-cleanup-unverified'):backend.start(runtime_transition=transition)
        self.assertEqual(tx.runtime['phase'],'unverified');stop.assert_not_called()

    def test_managed_port_retry_carries_the_same_durable_runtime_transition(self):
        import json
        from mihomoctl.app import Application
        from mihomoctl.config import Manager,CoreSettings
        from mihomoctl.errors import StateError
        self.config.write_text('listeners:\n  - name: proxy\n    port: 1234\nexternal-controller: "127.0.0.1:1235"\n')
        require_private_dir(self.scope.state_root,create=True)
        marker=self.scope.state_root/'managed-ports.json';marker.write_text(json.dumps({'proxy':1234,'controller':1235}));marker.chmod(0o600)
        backend=Mock()
        tx=transaction.Transaction(self.scope,'policy-activate');tx.runtime={'was_running':False,'phase':'prepared'};tx._persist()
        def attempted(**kwargs):
            kwargs['runtime_transition']('unverified')
            raise RollbackFailedError('start-cleanup-failed')
        backend.start.side_effect=attempted
        manager=Manager(core=CoreSettings('/core',str(self.config),'process'))
        endpoints=[SimpleNamespace(name='proxy',address='127.0.0.1',port=1234)]
        controller=SimpleNamespace(address='127.0.0.1',port=1235)
        app=SimpleNamespace(scope=self.scope,system=False,resolve=Mock(return_value=(manager,endpoints,controller,None,{})),_backend=Mock(return_value=backend))
        with self.assertRaisesRegex(RollbackFailedError,'start-cleanup-failed'):
            Application._retry_managed_ports(app,StateError('port-conflict'),lambda:True,tx)
        self.assertEqual(tx.runtime['phase'],'unverified');self.assertTrue(tx.backup_root.exists())

    def test_core_adoption_rejects_config_drift_before_stopping_old_core(self):
        from mihomoctl import coreinstall
        from mihomoctl.config import Manager,CoreSettings
        before='rules: ["MATCH,DIRECT"]\n';self.config.write_text(before)
        manager=Manager(core=CoreSettings('/old-core',str(self.config),'process'))
        backend=Mock();backend.status.return_value={'running':True}
        app=SimpleNamespace(resolve=Mock(return_value=(manager,[],None,None,{})),_backend=Mock(return_value=backend))
        def mutate(*args,**kwargs):self.config.write_text('rules: ["MALFORMED"]\n')
        with patch.object(coreinstall,'load_manager',return_value=manager),patch.object(coreinstall,'require_executable_file'), \
                patch.object(coreinstall.runner,'validate_config',side_effect=mutate),patch.object(coreinstall,'_application',return_value=app):
            with self.assertRaisesRegex(MihomoctlError,'config-changed-after-validation'):
                coreinstall._activate(self.scope,Path('/new-core'))
        backend.stop.assert_not_called();backend.start.assert_not_called()
        self.assertEqual(self.config.read_text(),'rules: ["MALFORMED"]\n')

    def test_core_adoption_rejects_validated_binary_replacement_before_stop(self):
        from mihomoctl import coreinstall
        from mihomoctl.lifecycle import runner
        from mihomoctl.config import Manager,CoreSettings
        import shutil,subprocess
        binary=self.root/'adopted';shutil.copyfile('/usr/bin/true',binary);binary.chmod(0o700)
        self.config.write_text('rules: ["MATCH,DIRECT"]\n')
        manager=Manager(core=CoreSettings('/old-core',str(self.config),'process'))
        backend=Mock();backend.status.return_value={'running':True}
        app=SimpleNamespace(resolve=Mock(return_value=(manager,[],None,None,{})),_backend=Mock(return_value=backend))
        original=runner.validate_config
        def replace(*args,**kwargs):
            proof=original(*args,**kwargs);binary.write_bytes(binary.read_bytes()+b'changed');return proof
        with patch.object(coreinstall,'load_manager',return_value=manager),patch.object(coreinstall,'_application',return_value=app), \
                patch.object(runner,'validate_config',side_effect=replace),patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)):
            with self.assertRaisesRegex(ValidationError,'validation-inputs-changed'):coreinstall._activate(self.scope,binary)
        backend.stop.assert_not_called();backend.start.assert_not_called()
        self.assertEqual(manager.core.binary,'/old-core')

    def test_stopped_core_unit_reload_failure_restores_definition_and_retains_failed_recovery(self):
        from mihomoctl import coreinstall
        from mihomoctl.lifecycle import systemd
        from mihomoctl.config import Manager,CoreSettings,render_manager
        from mihomoctl.errors import StateError
        import subprocess
        before='rules: ["MATCH,DIRECT"]\n';self.config.write_text(before)
        unit=systemd.unit_path(self.scope);unit.parent.mkdir(parents=True,mode=0o700)
        old_unit=systemd.UNIT_MARKER+'\n[Service]\n# old definition\n'
        backend=Mock();backend.running_identity.return_value=None
        backend.status.return_value={'running':False};backend._require_owned_unit.return_value={'ActiveState':'inactive'}
        for restore_fails in (False,True):
            manager=Manager(core=CoreSettings('/old-core',str(self.config),'systemd'))
            old_manager=render_manager(manager);self.scope.manager_path.write_text(old_manager);self.scope.manager_path.chmod(0o600)
            unit.write_text(old_unit);unit.chmod(0o600)
            app=SimpleNamespace(resolve=Mock(return_value=(manager,[],None,None,{})),_backend=Mock(return_value=backend))
            calls=[]
            def reload(*args,**kwargs):
                calls.append(args)
                if len(calls)==1:raise StateError('candidate-reload-failed')
                self.assertEqual(unit.read_text(),old_unit)
                if restore_fails:raise StateError('restored-reload-failed')
                return subprocess.CompletedProcess([],0)
            tx=transaction.Transaction(self.scope,'core-activate')
            with self.subTest(restore_fails=restore_fails),patch.object(coreinstall,'_application',return_value=app), \
                    patch.object(systemd,'unit_text',return_value=systemd.UNIT_MARKER+'\n[Service]\n# candidate\n'), \
                    patch.object(systemd,'_systemctl',side_effect=reload):
                with self.assertRaises(RollbackFailedError if restore_fails else StateError):
                    coreinstall._publish_and_activate(self.scope,tx,manager,'/new-core',validated_config=before)
            self.assertEqual(len(calls),2);self.assertEqual(unit.read_text(),old_unit)
            self.assertEqual(self.scope.manager_path.read_text(),old_manager)
            self.assertEqual(tx.backup_root.exists(),restore_fails)
            if restore_fails:
                with patch.object(systemd,'_systemctl',return_value=subprocess.CompletedProcess([],0)):
                    transaction.recover_transactions(self.scope)
                self.assertFalse(tx.backup_root.exists())
            backend.start.assert_not_called();backend.stop.assert_not_called()

    def test_standalone_port_retry_uses_fresh_transactions_and_restores_terminal_failure(self):
        import json,yaml
        from mihomoctl.app import Application
        from mihomoctl.config import Manager,CoreSettings
        from mihomoctl.errors import StateError
        require_private_dir(self.scope.state_root,create=True)
        marker=self.scope.state_root/'managed-ports.json'
        original='listeners:\n  - name: proxy\n    port: 1234\nexternal-controller: "127.0.0.1:1235"\n'
        original_marker=json.dumps({'proxy':1234,'controller':1235})
        manager=Manager(core=CoreSettings('/core',str(self.config),'process'))
        def resolve():
            data=yaml.safe_load(self.config.read_text())
            endpoint=SimpleNamespace(name='proxy',address='127.0.0.1',port=data['listeners'][0]['port'])
            controller=SimpleNamespace(address='127.0.0.1',port=int(data['external-controller'].split(':')[1]))
            return manager,[endpoint],controller,None,{}
        for outcomes in ([StateError('port-conflict'),ValidationError('terminal-failure')],
                         [StateError('port-conflict'),None],
                         [StateError('port-conflict') for _ in range(3)]):
            self.config.write_text(original);marker.write_text(original_marker);marker.chmod(0o600)
            backend=Mock();backend.status.return_value={'running':False}
            pending=list(outcomes)
            def start(**kwargs):
                kwargs['runtime_transition']('starting')
                error=pending.pop(0)
                if error is not None:raise error
            backend.start.side_effect=start
            app=SimpleNamespace(scope=self.scope,system=False,resolve=resolve,_backend=Mock(return_value=backend))
            ids=[];real_transaction=transaction.Transaction
            def create(*args,**kwargs):
                tx=real_transaction(*args,**kwargs);ids.append(tx.id);return tx
            with patch.object(transaction,'Transaction',side_effect=create),patch.object(transaction,'_runtime_backend',return_value=(app,backend)):
                if outcomes[-1] is None:Application._retry_managed_ports(app,StateError('port-conflict'),lambda:True)
                else:
                    with self.assertRaises(MihomoctlError):Application._retry_managed_ports(app,StateError('port-conflict'),lambda:True)
            self.assertEqual(len(ids),len(set(ids)));self.assertEqual(len(ids),len(outcomes))
            if outcomes[-1] is not None:
                self.assertEqual(self.config.read_text(),original);self.assertEqual(marker.read_text(),original_marker)
            else:self.assertNotEqual(self.config.read_text(),original)
            self.assertEqual(list(self.scope.backups_root.iterdir()),[])

    def test_policy_save_checks_retained_proof_before_write_and_activation(self):
        from mihomoctl.controller import controller_transaction as policy
        from mihomoctl.lifecycle import runner
        from mihomoctl.config import Manager,CoreSettings
        import shutil,subprocess
        binary=self.root/'core';shutil.copyfile('/usr/bin/true',binary);binary.chmod(0o700)
        require_private_dir(self.scope.core_home,create=True)
        geo=self.scope.core_home/'GeoSite.dat';geo.write_bytes(b'geo');geo.chmod(0o600)
        provider=self.scope.core_home/'nodes.yaml';provider.write_bytes(b'proxies: []\n');provider.chmod(0o600)
        before='proxy-providers: {p: {type: file, path: nodes.yaml}}\nrules: ["MATCH,DIRECT"]\n'
        after=before.replace('MATCH,DIRECT','MATCH,REJECT')
        manager=Manager(core=CoreSettings(str(binary),str(self.config),'process'))
        backend=Mock();backend.status.return_value={'running':True}
        app=SimpleNamespace(scope=self.scope,system=False,load_manager=Mock(return_value=manager),
                            resolve=Mock(return_value=(manager,[],None,None,{})),_backend=Mock(return_value=backend),lifecycle=Mock())
        original=policy.validate_candidate
        for managed in (False,True):
            for resource in (binary,geo,provider):
                self.config.write_text(before)
                token=policy.runtime_application.set(app if managed else None)
                def mutate_after_check(*args,**kwargs):
                    proof=original(*args,**kwargs);resource.write_bytes(resource.read_bytes()+b'changed');return proof
                try:
                    with patch.object(policy,'find_core',return_value=str(binary)), \
                            patch.object(policy,'validate_candidate',side_effect=mutate_after_check), \
                            patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)):
                        with self.assertRaisesRegex(policy.ControlError,'validation-inputs-changed'):
                            policy.apply_policy(self.config,before,after,home_dir=self.scope.core_home)
                finally:policy.runtime_application.reset(token)
                self.assertEqual(self.config.read_text(),before)
        self.config.write_text(before);token=policy.runtime_application.set(app)
        def after_write(tx):provider.write_bytes(provider.read_bytes()+b'changed-before-activation')
        try:
            with patch.object(runner,'run_core',return_value=subprocess.CompletedProcess([],0)):
                with self.assertRaisesRegex(policy.ControlError,'validation-inputs-changed'):
                    policy.apply_policy(self.config,before,after,home_dir=self.scope.core_home,after_write=after_write,activate=True)
        finally:policy.runtime_application.reset(token)
        self.assertEqual(self.config.read_text(),before);app.lifecycle.assert_not_called();backend.stop.assert_not_called()

    def test_service_unit_reload_recovery_and_exact_legacy_migration(self):
        from mihomoctl.lifecycle import systemd
        from mihomoctl.config import Manager,CoreSettings
        from mihomoctl.errors import StateError
        import subprocess,json
        manager=Manager(core=CoreSettings('/core',str(self.config),'systemd'))
        unit=systemd.unit_path(self.scope);unit.parent.mkdir(parents=True,mode=0o700)
        current=systemd.unit_text(manager,self.scope)
        legacy=current.replace(systemd.CORE_ENVIRONMENT,systemd.LEGACY_CORE_ENVIRONMENT)
        for operation in ('service-install','service-uninstall'):
            old=legacy if operation=='service-install' else current
            for restore_fails in (False,True):
                unit.write_text(old);unit.chmod(0o600)
                def action(tx):
                    if operation=='service-install':return systemd.install_unit(manager,self.scope,tx=tx)
                    return systemd.uninstall_unit(self.scope,tx=tx)
                attempts=[]
                def reload(*args,**kwargs):
                    attempts.append(args)
                    journal=next(self.scope.backups_root.glob('*/journal.json'))
                    self.assertTrue(json.loads(journal.read_text())['runtime']['unit_reload'])
                    if len(attempts)==1:raise StateError('candidate-reload-failed')
                    self.assertEqual(unit.read_text(),old)
                    if restore_fails:raise StateError('restored-reload-failed')
                    return subprocess.CompletedProcess([],0)
                with patch.object(systemd,'systemd_available',return_value=True),patch.object(systemd,'_systemctl',side_effect=reload):
                    with self.assertRaises(RollbackFailedError if restore_fails else StateError):
                        systemd.unit_transaction(self.scope,operation,action)
                self.assertEqual(len(attempts),2);self.assertEqual(unit.read_text(),old)
                journals=list(self.scope.backups_root.glob('*/journal.json'))
                self.assertEqual(bool(journals),restore_fails)
                if restore_fails:
                    with patch.object(systemd,'_systemctl',return_value=subprocess.CompletedProcess([],0)),patch.object(transaction,'_runtime_backend') as runtime:
                        transaction.recover_transactions(self.scope)
                    runtime.assert_not_called();self.assertEqual(list(self.scope.backups_root.iterdir()),[])
        # Simulate interruption after reload but before commit, then recover.
        unit.write_text(legacy)
        tx=transaction.Transaction(self.scope,'service-install')
        with patch.object(systemd,'systemd_available',return_value=True),patch.object(systemd,'_systemctl',return_value=subprocess.CompletedProcess([],0)):
            write=tx.write_text
            def publish(path,*args,**kwargs):
                doc=json.loads((tx.backup_root/'journal.json').read_text())
                self.assertTrue(doc['runtime']['unit_reload']);return write(path,*args,**kwargs)
            with patch.object(tx,'write_text',side_effect=publish):systemd.install_unit(manager,self.scope,tx=tx)
            self.assertEqual(unit.read_text(),current)
            transaction.recover_transactions(self.scope)
        self.assertEqual(unit.read_text(),legacy);self.assertFalse(tx.backup_root.exists())
        unit.write_text(current+'# unrelated edit\n')
        with patch.object(systemd,'systemd_available',return_value=True),patch.object(systemd,'_systemctl') as reload:
            with self.assertRaisesRegex(StateError,'unit-drifted'):systemd.install_unit(manager,self.scope)
        reload.assert_not_called();self.assertTrue(unit.read_text().endswith('# unrelated edit\n'))

    def test_other_accounts_private_parent_is_not_trusted(self):
        parent=self.root/'other-parent';parent.mkdir(mode=0o700)
        child=parent/'script';child.write_text('private');child.chmod(0o600)
        original=Path.stat
        def foreign(path,*args,**kwargs):
            result=original(path,*args,**kwargs)
            if path==parent:
                values=list(result);values[4]=os.getuid()+10000
                return os.stat_result(values)
            return result
        with patch.object(Path,'stat',foreign):
            with self.assertRaisesRegex(files.InstallError,'path-ancestor-not-owned-by-current-user-or-root'):
                private(child)

    def test_unmanaged_save_and_activation_is_refused_without_writes(self):
        from mihomoctl.controller.controller_transaction import apply_policy
        with self.assertRaisesRegex(Exception,'runtime-application-unavailable'):
            apply_policy(self.config,'old config\n','new config\n',activate=True)
        self.assertEqual(self.config.read_bytes(),b'old config\n')

    def test_app_validation_failure_does_not_touch_running_core(self):
        from mihomoctl.controller import controller_transaction as policy
        before='rules: ["MATCH,DIRECT"]\n';after='rules: ["MATCH,REJECT"]\n'
        self.config.write_text(before)
        backend=Mock();backend.status.return_value={'running':True}
        app=SimpleNamespace(scope=self.scope,system=False,resolve=Mock(return_value=(None,None,None,None,{})),
                            _backend=Mock(return_value=backend),lifecycle=Mock(),status=Mock(return_value={'overall':'PASS','runtime':{'running':True}}))
        token=policy.runtime_application.set(app)
        try:
            with patch.object(policy,'validate_candidate',side_effect=ValidationError('core-timeout')):
                with self.assertRaisesRegex(ValidationError,'core-timeout') as caught:
                    policy.apply_policy(self.config,before,after,activate=True)
        finally: policy.runtime_application.reset(token)
        app.lifecycle.assert_not_called();backend.stop.assert_not_called()
        self.assertEqual(self.config.read_text(),before)
        self.assertEqual(caught.exception.operation_state,{'phase':'validate','config':'restored','runtime':'running','activation':'failed'})

    def test_nonpassing_lifecycle_result_cannot_be_reported_as_activated(self):
        from mihomoctl.controller import controller_transaction as policy
        before='rules: ["MATCH,DIRECT"]\n';after='rules: ["MATCH,REJECT"]\n';self.config.write_text(before)
        backend=Mock();backend.status.return_value={'running':False}
        app=SimpleNamespace(scope=self.scope,system=False,resolve=Mock(return_value=(None,None,None,None,{})),
                            _backend=Mock(return_value=backend),lifecycle=Mock(return_value={'overall':'UNVERIFIED','runtime':{'running':False}}))
        token=policy.runtime_application.set(app)
        try:
            with patch.object(policy,'validate_candidate',return_value=Mock()):
                with self.assertRaisesRegex(MihomoctlError,'activation-not-verified'):
                    policy.apply_policy(self.config,before,after,activate=True)
        finally: policy.runtime_application.reset(token)
        self.assertEqual(self.config.read_text(),before)

    def test_unverified_runtime_recovery_retains_journal(self):
        backend=Mock();backend.status.return_value={'running':False}
        app=Mock();app.lifecycle.return_value={'overall':'UNVERIFIED','runtime':{'running':False}}
        def action(tx):
            tx.runtime={'was_running':True,'phase':'starting'};tx._persist()
            tx.write_text(self.config,'new config\n')
            raise ValidationError('start-not-verified')
        with patch.object(transaction,'_runtime_backend',return_value=(app,backend)):
            with self.assertRaisesRegex(RollbackFailedError,'rollback-failed'):
                transaction.run_transaction(self.scope,'policy-activate',action)
        self.assertEqual(self.config.read_bytes(),b'old config\n')
        self.assertTrue(list(self.scope.backups_root.glob('*/journal.json')))

    def test_running_recovery_requires_fresh_auth_and_never_signals_old_core(self):
        for health in ('FAIL','UNVERIFIED','PASS',RuntimeError('PRIVATE-CREDENTIAL')):
            tx=transaction.Transaction(self.scope,'policy-activate')
            tx.runtime={'was_running':True,'phase':'starting'};tx._persist()
            tx.write_text(self.config,'new config\n');tx.rollback(finish=False)
            backend=Mock();backend.status.return_value={'running':True}
            app=Mock();app.status.return_value={'overall':'PASS','runtime':{'running':True}}
            if isinstance(health,Exception):app._health_result.side_effect=health
            else:app._health_result.return_value=({},[],health)
            with self.subTest(health=type(health).__name__ if isinstance(health,Exception) else health), \
                    patch.object(transaction,'_runtime_backend',return_value=(app,backend)):
                if health=='PASS':
                    transaction.recover_transactions(self.scope)
                    self.assertFalse(tx.backup_root.exists())
                else:
                    with self.assertRaisesRegex(RollbackFailedError,'rollback-failed') as caught:
                        transaction.recover_transactions(self.scope)
                    self.assertNotIn('PRIVATE-CREDENTIAL',str(caught.exception))
                    self.assertTrue(tx.backup_root.exists())
                    app._health_result.side_effect=None;app._health_result.return_value=({},[],'PASS')
                    transaction.recover_transactions(self.scope)
                    self.assertFalse(tx.backup_root.exists())
            self.assertEqual(self.config.read_bytes(),b'old config\n')
            backend.stop.assert_not_called();app.lifecycle.assert_not_called()

    def test_unknown_child_without_state_never_means_stopped_or_discards_journal(self):
        import json
        backend = Mock(); backend.status.return_value = {'running': False, 'detail': 'no-state'}
        for was_running in (False, True):
            self.config.write_bytes(b'old config\n')
            def action(tx):
                tx.runtime = {'was_running': was_running, 'phase': 'unverified'}; tx._persist()
                tx.write_text(self.config, 'new config\n')
                raise RollbackFailedError('start-cleanup-failed')
            with self.subTest(was_running=was_running), \
                    patch.object(transaction, '_runtime_backend', return_value=(Mock(), backend)):
                with self.assertRaisesRegex(RollbackFailedError, 'rollback-failed'):
                    transaction.run_transaction(self.scope, 'policy-activate', action)
                journals = list(self.scope.backups_root.glob('*/journal.json'))
                self.assertTrue(journals)
                for journal in journals:
                    self.assertEqual(json.loads(journal.read_text())['runtime']['phase'], 'unverified')
                with self.assertRaisesRegex(RollbackFailedError, 'rollback-failed'):
                    transaction.recover_transactions(self.scope)
            backend.stop.assert_not_called()
            self.assertEqual(self.config.read_bytes(), b'new config\n')
            import shutil
            for journal in journals: shutil.rmtree(journal.parent)

    def test_interrupted_journal_without_state_is_retained(self):
        import json
        tx=transaction.Transaction(self.scope,'policy-activate')
        tx.write_text(self.config,'new config\n')
        journal=tx.backup_root/'journal.json';doc=json.loads(journal.read_text());doc.pop('state')
        journal.write_text(json.dumps(doc));journal.chmod(0o600)
        with self.assertRaisesRegex(MihomoctlError,'transaction-recovery-required'):
            transaction.recover_transactions(self.scope)
        self.assertTrue(journal.exists())

    def test_crash_recovery_phase_journals_restore_observed_state(self):
        for phase in ('prepared','stopping','starting'):
            self.config.write_bytes(b'old config\n')
            tx=transaction.Transaction(self.scope,'policy-activate')
            tx.runtime={'was_running':True,'phase':phase};tx._persist()
            tx.write_text(self.config,'new config\n')
            backend=Mock();backend.status.return_value={'running':False}
            app=Mock();app.lifecycle.return_value={'overall':'PASS','runtime':{'running':True}}
            with self.subTest(phase=phase),patch.object(transaction,'_runtime_backend',return_value=(app,backend)):
                transaction.recover_transactions(self.scope)
            self.assertEqual(self.config.read_bytes(),b'old config\n')
            self.assertFalse(tx.backup_root.exists())
            if phase=='prepared': app.lifecycle.assert_not_called()
            else: app.lifecycle.assert_called_once_with('start',_locked=True,_transaction=unittest.mock.ANY)

    def test_crash_recovery_preserves_manual_edit_and_journal(self):
        tx=transaction.Transaction(self.scope,'policy-activate')
        tx.runtime={'was_running':True,'phase':'stopping'};tx._persist();tx.write_text(self.config,'new config\n')
        self.config.write_text('manual edit\n')
        with self.assertRaisesRegex(MihomoctlError,'transaction-current-drifted'):
            transaction.recover_transactions(self.scope)
        self.assertEqual(self.config.read_text(),'manual edit\n')
        self.assertTrue(tx.backup_root.exists())

    def test_required_ownership_restore_failure_is_not_ignored(self):
        backup=self.root/'backup';backup.write_bytes(b'old')
        record={'mode':'0o600','uid':os.getuid()+10000,'gid':os.getgid()}
        with patch.object(os,'geteuid',return_value=0),patch.object(os,'chown',side_effect=PermissionError('denied')):
            with self.assertRaises(OSError): transaction.Transaction._restore(self.config,backup,record)

    def test_post_commit_cleanup_failure_reports_committed_configuration(self):
        from mihomoctl.controller import controller_transaction as policy
        before='rules: ["MATCH,DIRECT"]\n';after='rules: ["MATCH,REJECT"]\n';self.config.write_text(before)
        backend=Mock();backend.status.return_value={'running':True}
        app=SimpleNamespace(scope=self.scope,system=False,resolve=Mock(return_value=(None,None,None,None,{})),
                            _backend=Mock(return_value=backend),lifecycle=Mock(return_value={'overall':'PASS','runtime':{'running':True}}),
                            status=Mock(return_value={'overall':'PASS','runtime':{'running':True}}))
        token=policy.runtime_application.set(app)
        try:
            with patch.object(policy,'validate_candidate',return_value=Mock()), \
                    patch('mihomoctl.retention.cleanup_after_commit',side_effect=ValidationError('cleanup-failed')):
                with self.assertRaisesRegex(MihomoctlError,'cleanup-failed') as caught:
                    policy.apply_policy(self.config,before,after,activate=True)
        finally: policy.runtime_application.reset(token)
        self.assertEqual(self.config.read_text(),after)
        self.assertEqual(caught.exception.operation_state['config'],'committed')
        self.assertEqual(caught.exception.operation_state['activation'],'verified')

    def test_failed_save_never_labels_stale_identity_or_unverified_auth_as_running_or_stopped(self):
        from mihomoctl.controller import controller_transaction as policy
        before='rules: ["MATCH,DIRECT"]\n';after='rules: ["MATCH,REJECT"]\n';self.config.write_text(before)
        for runtime in ({'running':True,'listening':False}, {'running':False,'detail':'stale-state'},
                        {'running':False,'state':'active'}):
            backend=Mock();backend.status.return_value=runtime
            app=SimpleNamespace(scope=self.scope,system=False,resolve=Mock(return_value=(None,None,None,None,{})),
                                _backend=Mock(return_value=backend),lifecycle=Mock(),
                                status=Mock(return_value={'overall':'UNVERIFIED','runtime':runtime}))
            token=policy.runtime_application.set(app)
            try:
                with patch.object(policy,'validate_candidate',side_effect=ValidationError('core-timeout')):
                    with self.assertRaises(ValidationError) as caught:policy.apply_policy(self.config,before,after,activate=True)
            finally:policy.runtime_application.reset(token)
            self.assertEqual(caught.exception.operation_state['runtime'],'unverified')
            self.assertEqual(self.config.read_text(),before);backend.stop.assert_not_called()

    def test_preview_cleanup_failure_reports_already_committed_and_verified_runtime(self):
        from mihomoctl.controller import controller_subscriptions as subscriptions
        from mihomoctl.controller.controller_state import Snapshot
        import hashlib
        self.config.write_text('rules: ["MATCH,DIRECT"]\n')
        source=self.root/'nodes.yaml';source.write_text('proxies: [{name: test, type: direct}]\n');source.chmod(0o600)
        sub=subscriptions.Subscriptions(self.config)
        plan=sub.preview(source,policy='nodes')
        sub.app=SimpleNamespace(status=Mock(return_value={'overall':'PASS','runtime':{'running':True}}))
        def committed(config,original,updated,*args,**kwargs):
            config.write_text(updated)
            return {'state':'ready','action':'start','overall':'PASS','applied_sha256':hashlib.sha256(updated.encode()).hexdigest()}
        original_unlink=Path.unlink
        def failed_cleanup(path,*args,**kwargs):
            if path==sub.root/(plan['id']+'.json'):raise OSError('PRIVATE-CLEANUP-DETAIL')
            return original_unlink(path,*args,**kwargs)
        with patch.object(subscriptions,'apply_policy',side_effect=committed),patch.object(Path,'unlink',failed_cleanup):
            with self.assertRaisesRegex(subscriptions.ControlError,'subscription-cleanup-incomplete') as caught:
                sub.apply(plan['id'],plan['sha256'],activate=True)
        self.assertEqual(caught.exception.operation_state,{'phase':'cleanup','config':'committed','runtime':'running','activation':'verified'})
        self.assertNotIn('PRIVATE-CLEANUP-DETAIL',str(caught.exception))
        snap=Snapshot(error=caught.exception.code,safe_detail=caught.exception.safe_detail,operation_state=caught.exception.operation_state)
        self.assertIn('清理临时材料',snap.error_message);self.assertIn('新配置已提交',snap.error_message)


if __name__ == '__main__': unittest.main()
