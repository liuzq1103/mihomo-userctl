"""SSH onboarding, isolated users, and durable recovery without retained history."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

if sys.platform != 'linux':
    raise unittest.SkipTest('Linux user scopes and flock required')

from mihomoctl.app import Application
from mihomoctl.scope import Scope
from mihomoctl.errors import TransactionError, MihomoctlError, ObservedStateError
from mihomoctl.locks import operation_lock
from mihomoctl.transaction import run_transaction
from mihomoctl.trust import require_private_dir
from mihomoctl.yamlutil import strict_load
from mihomoctl.controller.controller_service import ConsoleService


class SSHTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mihomoctl-ssh-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.home = self.root / 'home'
        self.home.mkdir(mode=0o700)
        self.environment = {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / 'config'),
                            'XDG_DATA_HOME': str(self.home / 'data'), 'XDG_CACHE_HOME': str(self.home / 'cache'),
                            'XDG_STATE_HOME': str(self.home / 'state'), 'XDG_RUNTIME_DIR': str(self.home / 'run')}
        require_private_dir(Path(self.environment['XDG_RUNTIME_DIR']), create=True)
        self.patch = patch.dict(os.environ, self.environment)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.app = Application()
        self.scope = self.app.scope

    def initialize(self):
        core = self.home / 'mihomo'
        core.write_text('#!/bin/sh\nexit 0\n')
        core.chmod(0o700)
        self.app.initialize(str(core))
        self.config = Path(self.app.load_manager().core.config)
        return ConsoleService(self.config, str(self.scope.core_home), app=self.app)

    def input_file(self, body):
        source = self.home / 'subscription.yaml'
        source.write_text(body, encoding='utf-8')
        source.chmod(0o600)
        return source

    def test_guided_import_builds_a_selector_and_preserves_authentication(self):
        service = self.initialize()
        original = strict_load(self.config.read_text())
        original_bytes = self.config.read_bytes()
        source = self.input_file('''proxies:
- {name: Node A, type: socks5, server: example.com, port: 1080}
mixed-port: 7890
secret: remote-secret-must-not-be-imported
rules: [MATCH,DIRECT]
''')
        plan = service.subscription_input(str(source), kind='file')
        self.assertTrue(plan['guided'])
        self.assertEqual(self.config.read_bytes(), original_bytes)
        result = service.subscription_apply(plan['id'], plan['sha256'])
        data = strict_load(self.config.read_text())
        self.assertEqual(data['rules'], ['MATCH,Proxy'])
        self.assertEqual(data['proxy-groups'], [{'name': 'Proxy', 'type': 'select', 'proxies': ['Node A']}])
        self.assertEqual(data['listeners'], original['listeners'])
        self.assertEqual(data['secret'], original['secret'])
        self.assertIs(data['profile']['store-selected'], True)
        self.assertNotIn('backup', result)
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])
        self.assertEqual(list((self.scope.state_root / 'subscriptions').iterdir()), [])
        self.assertEqual(list(self.scope.config_root.rglob('*.before-*')), [])

    def test_url_is_hidden_from_results_and_persisted_privately_on_apply_only(self):
        service = self.initialize()
        url = 'https://example.com/subscription?token=private-test-value'
        payload = b'proxies: [{name: A, type: socks5, server: example.com, port: 1080}]\n'
        with patch('mihomoctl.controller.controller_subscriptions.download', return_value=payload) as download:
            plan = service.subscription_input(url)
        self.assertEqual(download.call_args.args, (url,))
        self.assertNotIn(url, json.dumps(plan))
        target = self.scope.config_root / 'subscription-url'
        self.assertFalse(target.exists())
        service.subscription_apply(plan['id'], plan['sha256'])
        self.assertEqual(target.read_text().strip(), url)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_invalid_subscription_preserves_current_config_and_no_history(self):
        service = self.initialize()
        original = self.config.read_bytes()
        source = self.input_file('proxies: [broken]\n')
        with self.assertRaises(Exception):
            service.subscription_input(str(source), kind='file')
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])

    def test_existing_custom_rules_are_not_changed_by_simple_import(self):
        service = self.initialize()
        self.config.write_text(self.config.read_text().replace('MATCH,DIRECT', 'DOMAIN,example.com,DIRECT'))
        source = self.input_file('proxies: [{name: A, type: socks5, server: example.com, port: 1080}]\n')
        plan = service.subscription_input(str(source), kind='file')
        self.assertFalse(plan['guided'])
        service.subscription_apply(plan['id'], plan['sha256'])
        self.assertEqual(strict_load(self.config.read_text())['rules'], ['DOMAIN,example.com,DIRECT'])

    def test_missing_or_invalid_existing_configuration_does_not_crash_setup_detection(self):
        service = self.initialize()
        from mihomoctl.onboarding import needs_setup
        from mihomoctl.controller.controller_types import ControlError
        for content in (None, '[malformed:'):
            if content is None:
                self.config.unlink()
            else:
                self.config.write_text(content)
                self.config.chmod(0o600)
            self.assertTrue(needs_setup(self.app))
            with self.assertRaises(ControlError):
                service.prepare()
            self.assertEqual(self.config.read_text() if self.config.exists() else None, content)

    def test_shortcut_simple_preview_and_discard_never_retain_raw_input(self):
        service = self.initialize()
        source = self.input_file('proxies: [{name: A, type: direct}]\n')
        plan = service.subscription_preview(str(source), policy='simple')
        self.assertTrue(plan['guided'])
        self.assertEqual(list((self.scope.state_root / 'subscriptions').glob('*.raw.yaml')), [])
        service.subscription_discard(plan['id'])
        self.assertEqual(list((self.scope.state_root / 'subscriptions').iterdir()), [])

    def test_new_session_cleans_expired_previews_and_preserves_foreign_files(self):
        import time
        service = self.initialize()
        source = self.input_file('proxies: [{name: A, type: direct}]\n')
        plan = service.subscription_input(str(source), kind='file')
        directory = self.scope.state_root / 'subscriptions'
        for path in directory.iterdir():
            old = time.time() - 2 * 86400
            os.utime(path, (old, old))
        foreign = directory / ('f' * 32 + '.raw.yaml')
        foreign.write_bytes(b'foreign')
        foreign.chmod(0o644)
        fresh = ConsoleService(self.config, str(self.scope.core_home), app=self.app)
        self.assertEqual(list(directory.iterdir()), [foreign])
        self.assertNotEqual(fresh.subscription_input(str(source), kind='file')['id'], plan['id'])
        self.assertEqual(foreign.read_bytes(), b'foreign')

    def test_committed_data_cleanup_failure_is_explicit_and_retried(self):
        require_private_dir(self.scope.config_root, create=True)
        target = self.scope.config_root / 'current'
        with patch('mihomoctl.retention.discard_config_history', side_effect=OSError('cleanup interrupted')):
            with self.assertRaisesRegex(TransactionError, 'operation-committed-cleanup-pending'):
                run_transaction(self.scope, 'commit-test', lambda tx: tx.write_text(target, 'committed'))
        self.assertEqual(target.read_text(), 'committed')
        marker = self.scope.state_root / 'cleanup/pending.json'
        self.assertTrue(marker.exists())
        with operation_lock(self.scope):
            pass
        self.assertFalse(marker.exists())
        self.assertEqual(target.read_text(), 'committed')

    def test_process_crash_recovers_original_bytes_and_removes_temporary_journal(self):
        require_private_dir(self.scope.config_root, create=True)
        target = self.scope.config_root / 'secret'
        target.write_bytes(b'original-private-data')
        target.chmod(0o600)
        code = '''import os, sys
from pathlib import Path
from mihomoctl.scope import Scope
from mihomoctl.locks import operation_lock
from mihomoctl.transaction import Transaction
with operation_lock(Scope()):
    tx = Transaction(Scope(), 'crash-test')
    tx.write_bytes(Path(sys.argv[1]), b'first-publication')
    tx.write_bytes(Path(sys.argv[1]), b'second-publication')
    os._exit(77)
'''
        result = subprocess.run([sys.executable, '-c', code, str(target)])
        self.assertEqual(result.returncode, 77)
        self.assertEqual(target.read_bytes(), b'second-publication')
        with operation_lock(self.scope):
            self.assertEqual(target.read_bytes(), b'original-private-data')
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])
        self.assertEqual(list(self.scope.staging_root.iterdir()), [])

    def test_crash_recovery_preserves_unrelated_manual_edits(self):
        require_private_dir(self.scope.config_root, create=True)
        target = self.scope.config_root / 'config'
        target.write_text('original')
        target.chmod(0o600)
        from mihomoctl.transaction import Transaction
        tx = Transaction(self.scope, 'interrupted')
        tx.write_text(target, 'candidate')
        target.write_text('manual-edit')
        with self.assertRaisesRegex(TransactionError, 'transaction-current-drifted'):
            with operation_lock(self.scope):
                pass
        self.assertEqual(target.read_text(), 'manual-edit')
        self.assertTrue(tx.backup_root.exists())

    def test_automatic_port_retry_preserves_other_listeners(self):
        self.initialize()
        previous = strict_load(self.config.read_text())
        sock = socket.socket()
        self.addCleanup(sock.close)
        sock.bind(('127.0.0.1', previous['listeners'][0]['port']))
        sock.listen()
        with patch('mihomoctl.lifecycle.process.ProcessBackend.start',
                   side_effect=[ObservedStateError('port-conflict'), None]):
            self.app.lifecycle('start')
        updated = strict_load(self.config.read_text())
        self.assertNotEqual(previous['listeners'][0]['port'], updated['listeners'][0]['port'])
        self.assertEqual(sock.getsockname()[1], previous['listeners'][0]['port'])
        self.assertEqual(previous['listeners'][0]['users'], updated['listeners'][0]['users'])

    def test_failed_port_retries_restore_config_and_leave_no_history(self):
        self.initialize()
        original = self.config.read_bytes()
        with patch('mihomoctl.lifecycle.process.ProcessBackend.start', side_effect=ObservedStateError('port-conflict')):
            with self.assertRaises(ObservedStateError):
                self.app.lifecycle('start')
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])

    def test_save_and_start_failure_restores_configuration_and_private_url(self):
        service = self.initialize()
        original = self.config.read_bytes()
        from mihomoctl.errors import StateError
        source = self.input_file('proxies: [{name: A, type: socks5, server: example.com, port: 1080}]\n')
        plan = service.subscription_input(str(source), kind='file')
        with patch('mihomoctl.lifecycle.process.ProcessBackend.start', side_effect=StateError('start-failed')):
            from mihomoctl.controller.controller_types import ControlError
            with self.assertRaises(ControlError):
                service.subscription_save_and_start(plan['id'], plan['sha256'])
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])

    def test_core_failed_runtime_recovery_keeps_material_until_next_attempt(self):
        self.initialize()
        from mihomoctl import coreinstall
        from mihomoctl.errors import RollbackFailedError, StateError
        from mihomoctl.transaction import Transaction
        original = self.scope.manager_path.read_bytes()
        manager = self.app.load_manager()
        old, candidate, restored = Mock(), Mock(), Mock()
        old.status.return_value = {'running': True}
        restored.status.return_value = {'running': False}
        candidate.start.side_effect = StateError('candidate-failed')
        restored.start.side_effect = StateError('original-restart-failed')
        app = Mock()
        app.resolve.return_value = (manager, [], None, None, {})
        app._backend.side_effect = [old, candidate, restored]
        recovery_app=Mock()
        recovery_app.lifecycle.side_effect=StateError('original-restart-failed')
        tx = Transaction(self.scope, 'core-activate')
        with patch.object(coreinstall, '_application', return_value=app), \
                patch('mihomoctl.transaction._runtime_backend',return_value=(recovery_app,restored)):
            with self.assertRaisesRegex(RollbackFailedError, 'core-runtime-rollback-failed'):
                coreinstall._publish_and_activate(self.scope, tx, manager, self.home / 'candidate')
        recovery_app.lifecycle.assert_called_once_with('start',_locked=True,_transaction=tx)
        self.assertEqual(self.scope.manager_path.read_bytes(), original)
        self.assertTrue(tx.backup_root.exists())
        self.assertEqual(json.loads((tx.backup_root / 'journal.json').read_text())['state'], 'restored')
        with patch('mihomoctl.transaction._restore_runtime') as recover:
            with operation_lock(self.scope):
                pass
        recover.assert_called_once()
        self.assertFalse(tx.backup_root.exists())

    def test_json_no_arguments_never_opens_ui(self):
        from mihomoctl.cli import main
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--json']), 2)
        self.assertEqual(json.loads(output.getvalue())['errors'][0]['code'], 'usage-error')

    def test_interactive_no_arguments_dispatches_tui(self):
        from mihomoctl.cli import main
        with patch('sys.stdin.isatty', return_value=True), patch('sys.stdout.isatty', return_value=True), \
                patch('mihomoctl.cli.dispatch', return_value=0) as dispatch:
            self.assertEqual(main([]), 0)
        self.assertEqual(dispatch.call_args.args[1], 'tui')

    def test_portable_archive_cannot_escape_or_create_symlinks(self):
        from mihomoctl.portable import source_tree
        for name, link in (('../outside', False), ('bundle/link', True)):
            archive = self.home / 'evil.tar.gz'
            with tarfile.open(archive, 'w:gz') as output:
                info = tarfile.TarInfo(name)
                if link:
                    info.type, info.linkname = tarfile.SYMTYPE, '/etc/passwd'
                output.addfile(info)
            with self.assertRaises((ValueError, MihomoctlError)):
                with source_tree(archive):
                    pass
