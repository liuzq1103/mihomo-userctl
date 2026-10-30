"""Offline domain regression: credentials, trust and explicit legacy migration."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from mihomoctl import envelope
from mihomoctl.config import Binding, Profile, parse_manager
from mihomoctl.credentials import Credentials
from mihomoctl.endpoints import Endpoint, parse_endpoints
from mihomoctl.environment import build
from mihomoctl.errors import ConfigError, StateError, TransactionError, RollbackFailedError
from mihomoctl.migrate import BEGIN_MARKER, END_MARKER, apply, preview
from mihomoctl.scope import Scope
from mihomoctl.transaction import run_transaction, restore_backup, Transaction
from mihomoctl.trust import require_private_dir


class DomainValues(unittest.TestCase):
    def test_authenticated_urls_preserve_host_and_percent_encode_credentials(self):
        profile = Profile('main', 'proxy', 'proxy', '/credentials')
        endpoint = Endpoint('proxy', 'listeners', 'mixed', '::1', 7890, False, True)
        variables = build(profile, [endpoint], Credentials('user', 'p@ss:$"word')).variables()
        from urllib.parse import urlsplit, unquote
        proxy = urlsplit(variables['HTTP_PROXY'])
        self.assertEqual((proxy.hostname, proxy.port), ('::1', 7890))
        self.assertEqual(unquote(proxy.password), 'p@ss:$"word')
        self.assertEqual(variables['http_proxy'], variables['HTTP_PROXY'])
        self.assertNotIn('p@ss', variables['HTTP_PROXY'])

    def test_unknown_observation_cannot_become_healthy_or_break_combination(self):
        self.assertEqual(envelope.combine(['missing-state', 'PASS']), 'UNVERIFIED')
        self.assertEqual(envelope.combine(['missing-state', 'FAIL']), 'FAIL')

    def test_binding_and_scope_secret_paths_are_strict(self):
        shape = {'version': 1, 'profiles': {'default': {'http_listener': 'x'}},
                 'bindings': {'worker': {'profile': 'default', 'adapter': 'systemd', 'target': 'worker.service'}}}
        self.assertEqual(parse_manager(shape).bindings['worker'].target, 'worker.service')
        shape['bindings']['worker']['connect_host'] = 'host\nInjected=yes'
        with self.assertRaises(ConfigError):
            parse_manager(shape)

    def test_user_transparent_and_auth_bypass_inputs_are_refused(self):
        for cfg in ({'tun': {'enable': True}}, {'allow-lan': True}, {'redir-port': 7891},
                    {'dns': {'listen': '127.0.0.1:5353'}}, {'skip-auth-prefixes': ['127.0.0.0/8']}):
            with self.subTest(cfg=cfg), self.assertRaises(ConfigError):
                parse_endpoints(cfg)

    def test_managed_config_persists_selector_choices(self):
        """A managed config must carry store-selected explicitly.

        Without it the core drops every Selector choice on the next start and
        falls back to each group's first member — for an airport subscription
        that is the "Expire:" information node.
        """
        from mihomoctl.config import compose_core_config
        from mihomoctl.yamlutil import strict_load
        cfg = strict_load(compose_core_config(17890, 'user', 'pw', 17891,
                                              'private-controller-token-for-preview-fixture'))
        self.assertIs(cfg['profile']['store-selected'], True)
        # Still a valid managed layout: exactly one loopback controller.
        _, controller = parse_endpoints(cfg)
        self.assertEqual(controller.address, '127.0.0.1')

    def test_custom_templates_use_format_literals_and_reject_unknown_placeholders(self):
        from mihomoctl.integration import render_template
        value = 'secret"; injected=true; %2F\\tail'
        for kind in ('ci', 'kubernetes', 'pm2'):
            rendered = render_template('{http_url}', {'http_url': value}, kind=kind)
            self.assertEqual(json.loads(rendered), value)
            with self.assertRaises(ConfigError):
                render_template('"{http_url}"', {'http_url': value}, kind=kind)
        self.assertEqual(render_template('{http_url}', {'http_url': 'x%20y'}, kind='supervisor'), '"x%%20y"')
        for token in ('{UNKNOWN}', '{bad-token}', '{http_url'):
            with self.assertRaises(ConfigError):
                render_template(token, {'http_url': value}, kind='docker')
        with self.assertRaises(ConfigError):
            render_template('{http_url}', {'http_url': 'x\nINJECT=1'}, kind='docker')

    @unittest.skipUnless(sys.platform == 'linux', 'native Linux subprocess credentials')
    def test_root_validator_uses_native_credentials_without_fork_callbacks(self):
        from types import SimpleNamespace
        from mihomoctl.lifecycle import runner
        account = SimpleNamespace(pw_uid=12345, pw_gid=23456)
        with patch.object(runner.os, 'geteuid', return_value=0), \
                patch('mihomoctl.trust.require_executable_file'), patch('pwd.getpwuid', return_value=account), \
                patch.object(runner.subprocess, 'run') as run:
            runner.run_core('/trusted/core', ['-t'], as_uid=account.pw_uid,
                env={'CLASH_POST_UP': 'bad', 'LD_PRELOAD': '/bad', 'SAFE': 'yes'})
            arguments = run.call_args.kwargs
            self.assertNotIn('preexec_fn', arguments)
            self.assertEqual((arguments['user'], arguments['group'], arguments['extra_groups']), (12345, 23456, [23456]))
            self.assertEqual(arguments['env'], {'SAFE': 'yes'})

    def test_egress_basic_auth_decodes_url_encoded_credentials(self):
        import base64
        from unittest.mock import Mock
        from mihomoctl.environment import ProxyEnvironment
        from mihomoctl import health
        proxy = ProxyEnvironment('default', 'http://user:p%40ss%3Aword@127.0.0.1:7890',
                                 'socks5h://user:p%40ss%3Aword@127.0.0.1:7890', 'localhost')
        connection, tunnel = Mock(), Mock()
        tunnel.recv.return_value = b'HTTP/1.1 200 OK\r\n\r\n'
        with patch.object(health, '_tcp', return_value=connection), \
                patch.object(health, '_recv', return_value=b'HTTP/1.1 200 OK\r\n\r\n'), \
                patch('ssl.create_default_context') as context:
            context.return_value.wrap_socket.return_value = tunnel
            self.assertEqual(health.egress_probe(proxy, 'https://example.com/').status, 'PASS')
        request = connection.sendall.call_args.args[0].decode()
        token = next(line.split('Basic ', 1)[1] for line in request.splitlines() if line.startswith('Proxy-Authorization:'))
        self.assertEqual(base64.b64decode(token).decode(), 'user:p@ss:word')

    @unittest.skipUnless(sys.platform == 'linux', 'Linux procfs TUN evidence')
    def test_tun_fd_evidence_requires_exact_iff_and_stable_process_identity(self):
        from mihomoctl.identity import ProcessIdentity
        from mihomoctl.lifecycle import tun
        with tempfile.TemporaryDirectory() as directory:
            proc = Path(directory)
            info = proc / '123/fdinfo'
            descriptors = proc / '123/fd'
            info.mkdir(parents=True)
            descriptors.mkdir()
            (info / '7').write_text('pos:\t0\niff:\tmihomo0\n')
            (descriptors / '7').symlink_to('/dev/net/tun')
            identity = ProcessIdentity(123, 234, 345, '/core', '/config')
            with patch('mihomoctl.identity.alive', side_effect=[True, True]):
                self.assertTrue(tun._owns_tun_fd(identity, 'mihomo0', proc=proc))
            with patch('mihomoctl.identity.alive', return_value=True):
                self.assertFalse(tun._owns_tun_fd(identity, 'foreign0', proc=proc))
            with patch('mihomoctl.identity.alive', side_effect=[True, False]):
                self.assertFalse(tun._owns_tun_fd(identity, 'mihomo0', proc=proc))

    @unittest.skipUnless(sys.platform == 'linux', 'Linux namespace inode evidence')
    def test_namespace_renderer_and_inode_guard_reject_unsafe_deployment(self):
        from mihomoctl.lifecycle import systemd
        path = '/run/netns/isolated-worker'
        self.assertEqual(systemd.namespace_dropin_text(path), systemd.UNIT_MARKER + '\n[Service]\nNetworkNamespacePath=' + path + '\n')
        for unsafe in ('/tmp/worker', '/run/netns/../other', path + '\nExecStart=/bad', '/run/netns/link/child'):
            with self.assertRaises(ConfigError):
                systemd.namespace_dropin_text(unsafe)
        actual = Path('/proc/self/ns/net').stat()
        with patch.object(systemd, '_namespace_entry', return_value=(actual.st_dev, actual.st_ino)):
            self.assertTrue(systemd._namespace_matches(path, process=os.getpid()))
        with patch.object(systemd, '_namespace_entry', return_value=(actual.st_dev, actual.st_ino + 1)):
            self.assertFalse(systemd._namespace_matches(path, process=os.getpid()))


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() != 0, 'ordinary Linux user fixture')
class DomainFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='muc-domain-')
        self.home = Path(self.tmp.name)
        self.home.chmod(0o700)
        self.env = patch.dict(os.environ, {'HOME': str(self.home), 'XDG_CONFIG_HOME': str(self.home / 'config'),
            'XDG_DATA_HOME': str(self.home / 'data'), 'XDG_STATE_HOME': str(self.home / 'state'),
            'XDG_CACHE_HOME': str(self.home / 'cache')}, clear=False)
        self.env.start()
        self.scope = Scope()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_missing_intermediate_private_directories_created_as_0700(self):
        target = self.home / 'a/b/c'
        require_private_dir(target, create=True)
        for path in (self.home / 'a', self.home / 'a/b', target):
            self.assertEqual(path.stat().st_mode & 0o777, 0o700)

    def test_nested_help_needs_no_initialization(self):
        from mihomoctl.cli import main
        for command in ('profile validate', 'integration export', 'service uninstall'):
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(command.split() + ['--help', '--json']), 0)
                self.assertEqual(json.loads(out.getvalue())['overall'], 'PASS')
        self.assertFalse(self.scope.manager_path.exists())

    def _write_manager(self, config_path=None):
        from mihomoctl.config import CoreSettings, Manager, Profile, compose_core_config, render_manager
        from mihomoctl.credentials import Credentials
        self.scope.credentials_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.scope.credentials_dir.chmod(0o700)
        credentials = self.scope.credentials_dir / 'work.yaml'
        Credentials.create(credentials, 'test-user', 'private-password')
        if config_path is None:
            config_path = self.home / 'core' / 'config.yaml'
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(compose_core_config(
            17890, 'test-user', 'private-password', 17891,
            'private-controller-token-for-preview-fixture'), encoding='utf-8')
        config_path.chmod(0o600)
        self.scope.manager_path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.scope.manager_path.write_text(render_manager(Manager(
            core=CoreSettings('/bin/true', str(config_path), 'process'),
            default_profile='work', profiles={'work': Profile(
                name='work', http_listener='proxy', socks_listener='proxy',
                credentials_file=str(credentials))})), encoding='utf-8')
        self.scope.manager_path.chmod(0o600)
        return config_path

    # -- reset ---------------------------------------------------------
    def _fake_core(self):
        """A stand-in core binary: validates every candidate like mihomo -t.

        A real path under the private fixture home, because the trust gate
        refuses a core reached through a symlinked ancestor (/bin -> usr/bin).
        """
        core = self.home / 'mihomo'
        core.write_text('#!/bin/sh\ncat > /dev/null\nexit 0\n', encoding='utf-8')
        core.chmod(0o700)
        return str(core)

    def _imported_subscription_state(self):
        """Post-subscription state: imported nodes, a second profile and the
        policy backup and restart receipt left behind by an apply."""
        scope = self.scope
        config = scope.config_root / 'mihomo' / 'config.yaml'
        original = config.read_text(encoding='utf-8')
        config.write_text(original.replace('  - MATCH,DIRECT\n',
            '  - MATCH,Proxy\nproxies:\n'
            '  - {name: bought-node, type: http, server: 198.51.100.7, port: 443}\n'),
            encoding='utf-8')
        config.chmod(0o600)
        extra = scope.credentials_dir / 'work.yaml'
        extra.write_text('username: work\npassword: work-password\n', encoding='utf-8')
        extra.chmod(0o600)
        backup = config.with_name(config.name + '.before-policy-deadbeef')
        backup.write_text(original, encoding='utf-8')
        backup.chmod(0o600)
        receipt = config.with_name(config.name + '.userctl-state.json')
        receipt.write_text('{"state": "restart-required"}\n', encoding='utf-8')
        receipt.chmod(0o600)
        return config, original, extra, backup, receipt

    def test_reset_preview_lists_managed_files_and_changes_nothing(self):
        from mihomoctl.app import Application
        app = Application()
        core = self._fake_core()
        app.initialize(core)
        config, _original, extra, backup, receipt = self._imported_subscription_state()
        before = {str(path): path.read_bytes()
                  for path in sorted(self.home.rglob('*')) if path.is_file()}
        preview = app.reset_preview()
        self.assertEqual(preview['state'], 'preview')
        self.assertEqual(preview['core'], core)
        self.assertEqual(preview['removed'], sorted(map(str, (extra, backup, receipt))))
        self.assertEqual(preview['replaced'], [str(self.scope.manager_path), str(config),
                                                str(self.scope.credentials_dir / 'default.yaml')])
        self.assertEqual(before, {str(path): path.read_bytes()
                                  for path in sorted(self.home.rglob('*')) if path.is_file()})

    def test_reset_requires_proof_and_rejects_content_drift_before_stop(self):
        from mihomoctl.app import Application
        from mihomoctl.errors import UsageError
        app = Application()
        app.initialize(self._fake_core())
        preview = app.reset_preview()
        with patch.object(app, 'lifecycle', side_effect=AssertionError('stale reset stopped runtime')):
            with self.assertRaisesRegex(UsageError, 'reset-preview-required'):
                app.reset()
            config = Path(app.load_manager().core.config)
            config.write_text(config.read_text() + '\n# changed after preview\n')
            with self.assertRaisesRegex(StateError, 'reset-preview-stale'):
                app.reset(plan_sha256=preview['plan_sha256'])

    def test_reset_proof_binds_credentials_and_effective_core(self):
        from mihomoctl.app import Application
        app = Application()
        core = self._fake_core()
        app.initialize(core)
        first = app.reset_preview()['plan_sha256']
        credential = self.scope.credentials_dir / 'default.yaml'
        credential.write_text(credential.read_text() + '\n# private change\n')
        self.assertNotEqual(first, app.reset_preview()['plan_sha256'])
        second = app.reset_preview()['plan_sha256']
        Path(core).write_text(Path(core).read_text() + '\n# replaced core\n')
        self.assertNotEqual(second, app.reset_preview()['plan_sha256'])

    def test_reset_repairs_malformed_config_when_owned_runtime_is_inactive(self):
        from mihomoctl.app import Application
        app = Application()
        app.initialize(self._fake_core())
        path = Path(app.load_manager().core.config)
        path.write_text('not: [valid YAML\n')
        proof = app.reset_preview()['plan_sha256']
        result = app.reset(plan_sha256=proof)
        self.assertEqual(result['state'], 'restart-required')
        self.assertIn('MATCH,DIRECT', path.read_text())

    def test_reset_preview_handles_manager_without_config_path(self):
        from mihomoctl.app import Application
        app = Application()
        app.initialize(self._fake_core())
        body = self.scope.manager_path.read_text()
        body = '\n'.join(line for line in body.splitlines() if not line.strip().startswith('config:')) + '\n'
        self.scope.manager_path.write_text(body)
        preview = app.reset_preview()
        self.assertEqual(len(preview['plan_sha256']), 64)
        result = app.reset(plan_sha256=preview['plan_sha256'])
        self.assertEqual(result['state'], 'restart-required')

    def test_reset_restores_the_initial_default_configuration(self):
        from mihomoctl.app import Application
        from mihomoctl.yamlutil import strict_load
        app = Application()
        app.initialize(self._fake_core())
        scope = self.scope
        config = scope.config_root / 'mihomo' / 'config.yaml'
        issued = (scope.credentials_dir / 'default.yaml').read_text(encoding='utf-8')
        config, _original, extra, backup, receipt = self._imported_subscription_state()

        result = app.reset(plan_sha256=app.reset_preview()['plan_sha256'])

        self.assertEqual(result['state'], 'restart-required')
        self.assertEqual(result['service'], 'unchanged')
        self.assertEqual(result['manager'], str(scope.manager_path))
        restored = config.read_text(encoding='utf-8')
        self.assertNotIn('bought-node', restored)
        self.assertIn('  - MATCH,DIRECT\n', restored)
        self.assertEqual(sorted(strict_load(restored)),
                         ['external-controller', 'listeners', 'mode', 'profile', 'rules', 'secret'])
        # Credentials are regenerated: the old secret no longer authenticates.
        self.assertNotEqual((scope.credentials_dir / 'default.yaml').read_text(encoding='utf-8'), issued)
        self.assertEqual(sorted(app.load_manager().profiles), ['default'])
        for path in (extra, backup, receipt):
            self.assertFalse(path.exists(), path)

    def test_reset_keeps_the_core_subscription_previews_and_logs(self):
        from mihomoctl.app import Application
        app = Application()
        app.initialize(self._fake_core())
        kept = {}
        for path in (self.scope.cores_root / 'v1.19.32' / 'mihomo',
                     self.scope.state_root / 'subscriptions' / 'abc.raw.yaml',
                     self.scope.logs_dir / 'mihomo.log'):
            path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            path.write_text('preserved\n', encoding='utf-8')
            path.chmod(0o600)
            kept[path] = 'preserved\n'
        app.reset(plan_sha256=app.reset_preview()['plan_sha256'])
        for path, body in kept.items():
            self.assertEqual(path.read_text(encoding='utf-8'), body, path)

    def test_reset_journals_the_previous_configuration_and_credentials(self):
        from mihomoctl.app import Application
        app = Application()
        app.initialize(self._fake_core())
        config, _original, extra, _backup, _receipt = self._imported_subscription_state()
        # The journal must hold the state reset actually replaced.
        config_body = config.read_bytes()
        extra_body = extra.read_bytes()
        manager_body = self.scope.manager_path.read_bytes()

        result = app.reset(plan_sha256=app.reset_preview()['plan_sha256'])

        self.assertEqual(list(self.scope.backups_root.iterdir()), [])
        self.assertNotIn('backup', result)
        self.assertFalse(extra.exists())
        self.assertNotEqual(config.read_bytes(), config_body)

    def test_reset_is_idempotent_and_needs_an_initialized_manager(self):
        from mihomoctl.app import Application
        from mihomoctl.errors import StateError
        with self.assertRaisesRegex(StateError, 'nothing to reset'):
            Application().reset()
        app = Application()
        app.initialize(self._fake_core())
        self._imported_subscription_state()
        self.assertNotEqual(app.reset(plan_sha256=app.reset_preview()['plan_sha256'])['removed'], [])
        self.assertEqual(app.reset(plan_sha256=app.reset_preview()['plan_sha256'])['removed'], [])
        self.assertEqual(sorted(app.load_manager().profiles), ['default'])

    def test_reset_reports_a_missing_core_instead_of_writing_anything(self):
        from mihomoctl.app import Application
        from mihomoctl.errors import ConfigError
        app = Application()
        app.initialize(self._fake_core())
        before = {str(path): path.read_bytes()
                  for path in sorted(self.home.rglob('*')) if path.is_file()}
        with self.assertRaisesRegex(ConfigError, 'missing binary'):
            app.reset(core=str(self.home / 'absent' / 'mihomo'))
        self.assertEqual(before, {str(path): path.read_bytes()
                                  for path in sorted(self.home.rglob('*')) if path.is_file()})

    def test_reset_is_dispatched_from_the_cli_for_both_actions(self):
        from mihomoctl.app import Application
        from mihomoctl.cli import main
        Application().initialize(self._fake_core())
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['reset', '--dry-run', '--json']), 0)
        preview = json.loads(out.getvalue())['data']
        self.assertEqual(preview['state'], 'preview')
        self.assertEqual(preview['removed'], [])
        self.assertTrue(self.scope.manager_path.exists(), 'preview must not publish')

        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['reset', '--apply', '--plan-sha256', preview['plan_sha256'], '--json']), 0)
        applied = json.loads(out.getvalue())['data']
        self.assertEqual(applied['state'], 'restart-required')
        self.assertIn('  - MATCH,DIRECT\n',
                      (self.scope.config_root / 'mihomo' / 'config.yaml').read_text(encoding='utf-8'))

    def test_rules_is_dispatched_with_managed_paths_and_never_guessed(self):
        from mihomoctl.cli import main
        from mihomoctl.controller import rules as checker
        config_path = self._write_manager()
        seen = {}

        def record(argv, core_binary=None, core_uid=None):
            seen['argv'] = list(argv)
            seen['core_binary'] = core_binary
            return 0

        with patch.object(checker, 'main', record), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['rules', 'status', '--json']), 0)
        document = json.loads(out.getvalue())
        self.assertEqual(document['command'], 'rules-status')
        self.assertEqual(document['overall'], 'PASS')
        self.assertEqual(document['data']['check'], 'status')
        self.assertEqual(seen['core_binary'], '/bin/true')
        self.assertEqual(seen['argv'][0], 'status')
        self.assertEqual(seen['argv'][-1], '--json')
        self.assertIn(str(self.scope.core_home), seen['argv'])
        self.assertIn(str(config_path), seen['argv'])
        # An explicit path is honoured verbatim and never replaced.
        with patch.object(checker, 'main', record), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['rules', 'status', '--home-dir', '/a', '--config', '/b']), 0)
        self.assertEqual(seen['argv'], ['status', '--home-dir', '/a', '--config', '/b'])

    def test_rules_rejects_unknown_subcommands_and_reports_missing_paths(self):
        from mihomoctl.cli import main
        from mihomoctl.config import CoreSettings, Manager, Profile, render_manager
        self._write_manager()
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['rules', 'rewrite', '--json']), 2)
        self.assertEqual(json.loads(out.getvalue())['errors'][0]['code'], 'usage-error')
        credentials = self.scope.credentials_dir / 'work.yaml'
        self.scope.manager_path.write_text(render_manager(Manager(
            core=CoreSettings('/bin/true', '', 'process'), default_profile='work',
            profiles={'work': Profile(name='work', http_listener='proxy',
                                      socks_listener='proxy', credentials_file=str(credentials))})),
            encoding='utf-8')
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['rules', 'status', '--json']), 2)
        self.assertEqual(json.loads(out.getvalue())['errors'][0]['code'], 'rules-unavailable')

    def test_rules_exit_code_is_preserved_through_the_envelope(self):
        from mihomoctl.cli import main
        from mihomoctl.controller import rules as checker
        self._write_manager()
        for code, overall in ((0, 'PASS'), (1, 'FAIL'), (2, 'UNVERIFIED')):
            with self.subTest(code=code), patch.object(checker, 'main', lambda argv, **kwargs: code), \
                    contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(main(['rules', 'check', '--json']), code)
            document = json.loads(out.getvalue())
            self.assertEqual(document['overall'], overall)
            self.assertEqual(document['data']['exit'], code)

    def test_service_uninstall_preview_never_claims_a_removal_it_did_not_perform(self):
        from mihomoctl.app import UNIT_NAME
        from mihomoctl.cli import main
        from mihomoctl.lifecycle import systemd as backend
        self._write_manager()
        installed = []
        writes = []

        class StubTransaction:
            def write_text(self, path, text, mode=None):
                writes.append(path)

        def run_transaction(scope, name, body):
            return body(StubTransaction())

        with patch.object(backend.SystemdBackend, 'running', return_value=(False, {'ActiveState': 'inactive'})), \
                patch.object(backend, 'uninstall_unit', side_effect=lambda scope, tx=None: installed.append(scope)), \
                patch.object(backend, 'unit_transaction', side_effect=run_transaction), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['service', 'uninstall', '--dry-run', '--json']), 0)
        preview = json.loads(out.getvalue())
        self.assertEqual(preview['command'], 'service-uninstall-preview')
        self.assertEqual(preview['data'], {'unit': UNIT_NAME, 'dry_run': True})
        self.assertEqual(installed, [], 'a preview must not remove the unit')
        self.assertEqual(writes, [], 'a preview must not rewrite the manager')
        with patch.object(backend.SystemdBackend, 'running', return_value=(False, {'ActiveState': 'inactive'})), \
                patch.object(backend, 'uninstall_unit', side_effect=lambda scope, tx=None: installed.append(scope)), \
                patch.object(backend, 'unit_transaction', side_effect=run_transaction), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['service', 'uninstall', '--json']), 0)
        applied = json.loads(out.getvalue())
        self.assertEqual(applied['command'], 'service-uninstall')
        self.assertNotIn('dry_run', applied['data'])
        self.assertEqual(len(installed), 1)

    def test_service_uninstall_preview_predicts_the_blocking_preconditions(self):
        from mihomoctl.cli import main
        from mihomoctl.lifecycle import systemd as backend
        self._write_manager()
        with patch.object(backend.SystemdBackend, 'running',
                          return_value=(True, {'ActiveState': 'activating'})), \
                patch.object(backend, 'uninstall_unit') as remove, \
                patch.object(backend, 'unit_transaction') as transaction, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['service', 'uninstall', '--dry-run', '--json']), 2)
        self.assertEqual(json.loads(out.getvalue())['errors'][0]['code'], 'backend-active')
        remove.assert_not_called()
        transaction.assert_not_called()

    def test_duplicate_sensitive_yaml_keys_are_not_echoed_by_cli(self):
        from mihomoctl.cli import main
        sensitive = 'https://subscription.example.invalid/private?token=' + 'never-echo-this-token'
        candidate = self.home / 'candidate.yaml'
        candidate.write_text(json.dumps(sensitive) + ': one\n' + json.dumps(sensitive) + ': two\n')
        candidate.chmod(0o600)
        for json_mode in (True, False):
            arguments = ['config', 'validate', '--file', str(candidate)]
            if json_mode:
                arguments.append('--json')
            with self.subTest(json_mode=json_mode), contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(arguments), 2)
            rendered = out.getvalue() + err.getvalue()
            self.assertNotIn(sensitive, rendered)
            self.assertNotIn('never-echo-this-token', rendered)
            self.assertIn('line 2 column 1', rendered)
            if json_mode:
                document = json.loads(out.getvalue())
                self.assertEqual(document['errors'][0]['code'], 'config-invalid')
        self.assertFalse(self.scope.manager_path.exists())

    def test_schema_error_diagnostics_never_echo_sensitive_keys_or_values(self):
        import copy
        import yaml
        from mihomoctl.cli import main
        sensitive = 'https://subscription.invalid/?token=' + 'never-echo-sensitive-input'
        base = {'version': 1, 'profiles': {'default': {'http_listener': 'proxy'}},
                'bindings': {'worker': {'profile': 'default', 'adapter': 'ci'}}}
        require_private_dir(self.scope.config_root, create=True)
        cases = []
        for location in ((), ('profiles', 'default'), ('bindings', 'worker'), ('core',),
                         ('profiles', 'default', 'health'), ('tun',)):
            shape = copy.deepcopy(base)
            target = shape
            for key in location:
                target = target.setdefault(key, {})
            target[sensitive] = 'value'
            cases.append(shape)
        for key in ('default_profile',):
            shape = copy.deepcopy(base)
            shape[key] = sensitive
            cases.append(shape)
        shape = copy.deepcopy(base)
        shape['bindings']['worker']['profile'] = sensitive
        cases.append(shape)
        # Validate a map key before any RHS parser diagnostic interpolates it.
        for section in ('profiles', 'bindings'):
            for invalid_value in (False, {sensitive: 'value'}):
                shape = copy.deepcopy(base)
                shape[section][sensitive] = invalid_value
                cases.append(shape)
        for index, shape in enumerate(cases):
            self.scope.manager_path.write_text(yaml.safe_dump(shape))
            self.scope.manager_path.chmod(0o600)
            with self.subTest(manager_case=index), contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(['profile', 'list', '--json']), 2)
            self.assertEqual(json.loads(out.getvalue())['errors'][0]['code'], 'config-invalid')
            self.assertNotIn(sensitive, out.getvalue() + err.getvalue())
        self.scope.manager_path.unlink()
        candidate = self.home / 'listener.yaml'
        for item in ({sensitive: 'value'}, {'name': 'proxy', 'type': sensitive},
                     {'name': sensitive, 'type': 'mixed', 'users': 'invalid'}):
            candidate.write_text(yaml.safe_dump({'listeners': [item]}))
            candidate.chmod(0o600)
            with self.subTest(listener=item), contextlib.redirect_stdout(io.StringIO()) as out, \
                    contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(main(['config', 'validate', '--file', str(candidate), '--json']), 2)
            self.assertEqual(json.loads(out.getvalue())['errors'][0]['code'], 'config-invalid')
            self.assertNotIn(sensitive, out.getvalue() + err.getvalue())

    def test_retired_entries_are_safe_single_object_refusals_without_running_children(self):
        from mihomoctl.cli import main
        for command in ('paseo', 'codex', 'opencode', 'diagnose', 'ready'):
            with self.subTest(command=command), contextlib.redirect_stdout(io.StringIO()) as out, \
                    patch('mihomoctl.cli.subprocess.run') as run, patch('mihomoctl.cli.os.execvpe') as execute:
                self.assertEqual(main([command, 'start', '--json', '--', 'unexpected-child']), 2)
                data = json.loads(out.getvalue())
                self.assertEqual(data['errors'][0]['code'], 'retired-command')
                self.assertIn('mihomoctl exec', data['errors'][0]['remediation'])
                run.assert_not_called()
                execute.assert_not_called()
        self.assertFalse(self.scope.manager_path.exists())

    def test_commit_failure_restores_published_files(self):
        require_private_dir(self.scope.config_root, create=True)
        target = self.scope.config_root / 'commit-target'
        target.write_bytes(b'old')
        target.chmod(0o600)
        with patch.object(Transaction, 'commit', side_effect=OSError('journal unavailable')):
            with self.assertRaises(OSError):
                run_transaction(self.scope, 'failure', lambda tx: tx.write_bytes(target, b'new'))
        self.assertEqual(target.read_bytes(), b'old')

    def test_service_uninstall_restores_files_backend_and_reload_on_failure(self):
        from types import SimpleNamespace
        from mihomoctl.config import CoreSettings, Manager, render_manager
        from mihomoctl.cli import cmd_service
        from mihomoctl.lifecycle import systemd
        require_private_dir(self.scope.config_root, create=True)
        for stage in ('reload', 'commit'):
            with self.subTest(stage=stage):
                manager = Manager(core=CoreSettings('/core', '/config', 'systemd'))
                original = render_manager(manager).encode()
                self.scope.manager_path.write_bytes(original)
                self.scope.manager_path.chmod(0o600)
                unit = systemd.unit_path(self.scope)
                require_private_dir(unit.parent, create=True)
                unit.write_text(systemd.UNIT_MARKER + '\n[Service]\n')
                unit.chmod(0o600)
                dropin = systemd.dropin_dir(self.scope) / 'own.conf'
                require_private_dir(dropin.parent, create=True)
                dropin.write_text(systemd.UNIT_MARKER + '\nowned\n')
                dropin.chmod(0o600)
                foreign = dropin.parent / 'foreign.conf'
                foreign.write_text('[Service]\nExternal=yes\n')
                foreign.chmod(0o600)
                app = SimpleNamespace(scope=self.scope, resolve=lambda: (manager, [], None, None, {}))
                reloads = [StateError('reload-failed'), None] if stage == 'reload' else [None, None]
                with patch.object(systemd.SystemdBackend, 'running', return_value=(False, {'ActiveState': 'inactive'})), \
                        patch.object(systemd, '_systemctl', side_effect=reloads) as reload, \
                        patch.object(Transaction, 'commit', side_effect=OSError('journal failed') if stage == 'commit' else None):
                    with self.assertRaises((StateError, OSError)):
                        cmd_service(app, ['uninstall'], True)
                    self.assertEqual(reload.call_count, 2)
                self.assertEqual(self.scope.manager_path.read_bytes(), original)
                self.assertTrue(unit.exists())
                self.assertTrue(dropin.exists())
                self.assertEqual(foreign.read_text(), '[Service]\nExternal=yes\n')

    def test_integration_failure_restores_artifacts_and_reloads_restored_definitions(self):
        from mihomoctl.environment import ProxyEnvironment
        from mihomoctl.integration import systemd_adapter as adapter
        binding = Binding('worker', 'default', 'systemd', 'worker.service')
        old = ProxyEnvironment('default', 'http://user:old@127.0.0.1:7890', 'socks5h://user:old@127.0.0.1:7890', 'localhost')
        new = ProxyEnvironment('default', 'http://user:new@127.0.0.1:7890', 'socks5h://user:new@127.0.0.1:7890', 'localhost')
        with patch.object(adapter, '_daemon_reload'):
            adapter.install(self.scope, binding, old)
        paths = (adapter.env_file(self.scope, binding.name), adapter.dropin_path(self.scope, binding.target), adapter._receipt_file(self.scope, binding))
        before = {path: path.read_bytes() for path in paths}
        for stage in ('reload', 'commit', 'remove', 'recovery'):
            with self.subTest(stage=stage):
                reloads = [None, None] if stage == 'commit' else [StateError('reload-failed'), None]
                if stage == 'recovery':
                    reloads[1] = StateError('restore-reload-failed')
                with patch.object(adapter, '_daemon_reload', side_effect=reloads) as reload, \
                        patch.object(Transaction, 'commit', side_effect=OSError('journal failed') if stage == 'commit' else None):
                    with self.assertRaises(RollbackFailedError if stage == 'recovery' else (StateError, OSError)):
                        if stage == 'remove':
                            adapter.remove(self.scope, binding)
                        else:
                            adapter.install(self.scope, binding, new)
                    self.assertEqual(reload.call_count, 2)
                self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_public_integration_install_recovers_cached_definitions_and_respects_lock(self):
        from types import SimpleNamespace
        from mihomoctl.cli import cmd_integration
        from mihomoctl.config import Manager
        from mihomoctl.environment import ProxyEnvironment
        from mihomoctl.errors import LockError
        from mihomoctl.integration import systemd_adapter as adapter
        from mihomoctl.locks import operation_lock
        binding = Binding('worker', 'default', 'systemd', 'worker.service')
        old = ProxyEnvironment('default', 'http://u:old@127.0.0.1:7890', 'socks5h://u:old@127.0.0.1:7890', 'localhost')
        new = ProxyEnvironment('default', 'http://u:new@127.0.0.1:7890', 'socks5h://u:new@127.0.0.1:7890', 'localhost')
        manager = Manager(bindings={'worker': binding})
        app = SimpleNamespace(scope=self.scope, load_manager=lambda: manager, proxy_environment=lambda _: new)
        with patch.object(adapter, '_daemon_reload'):
            adapter.install(self.scope, binding, old)
        paths = (adapter.env_file(self.scope, binding.name), adapter.dropin_path(self.scope, binding.target), adapter._receipt_file(self.scope, binding))
        before = {path: path.read_bytes() for path in paths}
        with patch.object(adapter, '_daemon_reload', side_effect=[StateError('reload-failed'), None]) as reload:
            with self.assertRaises(StateError):
                cmd_integration(app, ['install', 'worker'], True)
            self.assertEqual(reload.call_count, 2)
        self.assertEqual({path: path.read_bytes() for path in paths}, before)
        with operation_lock(self.scope), patch.object(adapter, '_daemon_reload') as reload:
            with self.assertRaises(LockError):
                cmd_integration(app, ['install', 'worker'], True)
            reload.assert_not_called()
        self.assertEqual({path: path.read_bytes() for path in paths}, before)

    def test_setting_default_profile_preserves_newer_manager_fields(self):
        from types import SimpleNamespace
        import yaml
        from mihomoctl.cli import cmd_profile
        from mihomoctl.config import Manager, CoreSettings
        profiles = {'default': Profile('default', 'proxy'), 'other': Profile('other', 'proxy')}
        old = Manager(core=CoreSettings('/old-core', '/config'), profiles=profiles)
        current = Manager(core=CoreSettings('/new-core', '/config'), profiles=profiles,
                          bindings={'worker': Binding('worker', 'default', 'ci')})
        app = SimpleNamespace(scope=self.scope, load_manager=lambda: old,
                              resolve=lambda _: (current, [], None, profiles['other'], {}))
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cmd_profile(app, ['set-default', 'other'], True), 0)
        written = yaml.safe_load(self.scope.manager_path.read_text())
        self.assertEqual(written['core']['binary'], '/new-core')
        self.assertIn('worker', written['bindings'])
        self.assertEqual(written['default_profile'], 'other')

    def test_integration_lock_contention_cannot_reload_another_transaction(self):
        from mihomoctl.environment import ProxyEnvironment
        from mihomoctl.errors import LockError
        from mihomoctl.integration import systemd_adapter as adapter
        from mihomoctl.locks import operation_lock
        binding = Binding('worker', 'default', 'systemd', 'worker.service')
        proxy = ProxyEnvironment('default', 'http://u:p@127.0.0.1:7890', 'socks5h://u:p@127.0.0.1:7890', 'localhost')
        with operation_lock(self.scope), patch.object(adapter, '_daemon_reload') as reload:
            with self.assertRaises(LockError):
                adapter.install(self.scope, binding, proxy)
            with self.assertRaises(LockError):
                adapter.remove(self.scope, binding)
            reload.assert_not_called()

    def test_systemd_environment_file_uses_actual_single_path_parser_and_literal_glob(self):
        import ctypes
        import shutil
        import subprocess
        from mihomoctl.integration import systemd_adapter as adapter
        executable = shutil.which('systemd-analyze')
        if executable is None:
            self.skipTest('systemd-analyze is unavailable on this non-systemd development host')
        class Glob(ctypes.Structure):
            _fields_ = [('gl_pathc', ctypes.c_size_t), ('gl_pathv', ctypes.POINTER(ctypes.c_char_p)),
                        ('gl_offs', ctypes.c_size_t), ('gl_flags', ctypes.c_int),
                        ('gl_closedir', ctypes.c_void_p), ('gl_readdir', ctypes.c_void_p),
                        ('gl_opendir', ctypes.c_void_p), ('gl_lstat', ctypes.c_void_p),
                        ('gl_stat', ctypes.c_void_p)]
        libc = ctypes.CDLL(None)
        libc.glob.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(Glob)]
        libc.globfree.argtypes = [ctypes.POINTER(Glob)]
        unit = self.home / 'environment-parser.service'
        unit.write_text('[Service]\nType=simple\nExecStart=/usr/bin/true\n')
        directory = unit.parent / (unit.name + '.d')
        directory.mkdir()
        dropin = directory / adapter.DROPIN_NAME
        for suffix in ('ordinary', 'with space', 'literal%percent', 'literal\\backslash', 'literal[*?]pattern'):
            scope = Scope(config_dir=str(self.home / suffix))
            target = adapter.env_file(scope, 'worker')
            require_private_dir(target.parent, create=True)
            target.write_text('HTTP_PROXY=http://example.invalid:7890\n')
            target.chmod(0o600)
            dropin.write_text(adapter.render_dropin(scope, 'worker'))
            result = subprocess.run([executable, 'verify', str(unit)], capture_output=True, text=True,
                env=dict(os.environ, SYSTEMD_LOG_LEVEL='debug', LC_ALL='C'), timeout=20)
            diagnostic = result.stdout + result.stderr
            with self.subTest(path_kind=suffix):
                self.assertEqual(result.returncode, 0, 'systemd-unit-parse-failed')
                self.assertFalse(any('EnvironmentFile=' in line for line in diagnostic.splitlines()),
                                 'systemd-environment-file-parse-warning')
                parsed = [line.strip().split(': ', 1)[1] for line in diagnostic.splitlines()
                          if line.strip().startswith('EnvironmentFile: ')]
                self.assertEqual(len(parsed), 1, 'systemd-did-not-load-environment-file')
                matched = Glob()
                try:
                    self.assertEqual(libc.glob(parsed[0].encode(), 0, None, ctypes.byref(matched)), 0,
                                     'environment-file-glob-did-not-match')
                    self.assertEqual([os.fsdecode(matched.gl_pathv[index]) for index in range(matched.gl_pathc)],
                                     [str(target)])
                finally:
                    libc.globfree(ctypes.byref(matched))
        for suffix in ('bad\npath', 'bad\rpath', 'bad\tpath', 'bad\x00path'):
            with self.subTest(invalid_path=True), self.assertRaises(ConfigError):
                adapter.render_dropin(Scope(config_dir=str(self.home / suffix)), 'worker')

    def test_systemd_foreign_named_unit_is_rejected_before_any_lifecycle_call(self):
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.lifecycle import systemd
        unit = systemd.unit_path(self.scope)
        require_private_dir(unit.parent, create=True)
        unit.write_text('[Service]\nExecStart=/foreign\n')
        unit.chmod(0o600)
        backend = systemd.SystemdBackend(self.scope, Manager(core=CoreSettings('/core', '/config', 'systemd')), [], None)
        for action in ('start', 'stop', 'restart'):
            with self.subTest(action=action), patch.object(systemd, '_systemctl') as command:
                with self.assertRaises(StateError):
                    getattr(backend, action)()
                command.assert_not_called()

    def test_systemd_loaded_foreign_fragment_override_or_active_identity_is_rejected(self):
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.lifecycle import systemd
        manager = Manager(core=CoreSettings('/core', '/config', 'systemd'))
        unit = systemd.unit_path(self.scope)
        require_private_dir(unit.parent, create=True)
        unit.write_text(systemd.unit_text(manager, self.scope))
        unit.chmod(0o600)
        backend = systemd.SystemdBackend(self.scope, manager, [], None)
        for props in ({'ActiveState': 'inactive', 'FragmentPath': '/foreign.service', 'NeedDaemonReload': 'no'},
                      {'ActiveState': 'inactive', 'FragmentPath': str(unit), 'DropInPaths': '/foreign.conf', 'NeedDaemonReload': 'no'},
                      {'ActiveState': 'active', 'FragmentPath': str(unit), 'DropInPaths': '', 'NeedDaemonReload': 'no'}):
            for action in ('start', 'stop', 'restart'):
                with self.subTest(props=props, action=action), patch.object(backend, '_main_pid', return_value=props), \
                        patch.object(backend, 'running_identity', return_value=None), patch.object(systemd, '_systemctl') as command:
                    with self.assertRaises(StateError):
                        getattr(backend, action)()
                    command.assert_not_called()

    def test_stale_cached_systemd_definition_is_refused_before_lifecycle_mutation(self):
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.lifecycle import systemd
        manager = Manager(core=CoreSettings('/core', '/config', 'systemd'))
        unit = systemd.unit_path(self.scope)
        require_private_dir(unit.parent, create=True)
        unit.write_text(systemd.unit_text(manager, self.scope))
        unit.chmod(0o600)
        backend = systemd.SystemdBackend(self.scope, manager, [], None)
        for reload_state in ('yes', '', None):
            props = {'ActiveState': 'inactive', 'FragmentPath': str(unit), 'DropInPaths': '',
                     'NeedDaemonReload': reload_state, 'ExecStart': '/foreign-old-definition'}
            for action in ('start', 'stop', 'restart'):
                with self.subTest(reload=reload_state, action=action), \
                        patch.object(backend, '_main_pid', return_value=props), \
                        patch.object(systemd, '_systemctl') as command:
                    with self.assertRaises(StateError) as error:
                        getattr(backend, action)()
                    self.assertEqual(error.exception.code, 'unit-definition-unverified')
                    command.assert_not_called()
        props['NeedDaemonReload'] = 'no'
        with patch.object(backend, '_main_pid', return_value=props):
            self.assertEqual(backend._require_owned_unit()['NeedDaemonReload'], 'no')

    def test_service_install_lock_contention_never_reloads_or_writes(self):
        from types import SimpleNamespace
        from mihomoctl import cli
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.errors import LockError
        from mihomoctl.lifecycle import systemd
        from mihomoctl.locks import operation_lock
        manager = Manager(core=CoreSettings('/core', '/config', 'process'))
        app = SimpleNamespace(scope=self.scope, resolve=lambda: (manager, [], None, None, {}))
        with operation_lock(self.scope), patch('mihomoctl.lifecycle.process.ProcessBackend.running_identity', return_value=None), \
                patch.object(systemd, 'systemd_available', return_value=True), patch.object(systemd, '_systemctl') as command:
            with self.assertRaises(LockError):
                cli.cmd_service(app, ['install'], True)
            command.assert_not_called()
        self.assertFalse(self.scope.manager_path.exists())
        self.assertFalse(systemd.unit_path(self.scope).exists())

    def test_invalid_restart_candidate_does_not_stop_either_backend(self):
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.errors import ValidationError
        from mihomoctl.lifecycle import process, systemd
        config = self.home / 'candidate.yaml'
        config.write_text('invalid semantic candidate')
        manager = Manager(core=CoreSettings('/core', str(config), 'process'))
        for backend in (process.ProcessBackend(self.scope, manager, [], None),
                        systemd.SystemdBackend(self.scope, manager, [], None)):
            with self.subTest(backend=backend.name), \
                    patch.object(process.runner, 'validate_config', side_effect=ValidationError('core-config-invalid')), \
                    patch.object(backend, 'stop') as stop, patch.object(backend, 'start') as start, \
                    patch.object(backend, 'running_identity', return_value=None), \
                    patch.object(systemd.SystemdBackend, '_require_owned_unit', return_value={'ActiveState': 'inactive'}):
                with self.assertRaises(ValidationError):
                    backend.restart()
                stop.assert_not_called()
                start.assert_not_called()

    def test_process_receipt_failure_or_interrupt_stops_only_verified_child(self):
        from unittest.mock import Mock
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.lifecycle import process
        from mihomoctl.identity import ProcessIdentity
        require_private_dir(self.scope.config_root, create=True)
        config = self.scope.config_root / 'core.yaml'
        config.write_text('rules: [MATCH,DIRECT]\n')
        config.chmod(0o600)
        manager = Manager(core=CoreSettings('/core', str(config), 'process'))
        identity = ProcessIdentity(123456, os.geteuid(), 1, '/core', str(config))
        backend = process.ProcessBackend(self.scope, manager, [], None)
        for failure in (OSError('state publication failed'), KeyboardInterrupt()):
            child = Mock(pid=identity.pid)
            child.poll.return_value = None
            def publication(_identity):
                require_private_dir(self.scope.runtime_state.parent, create=True)
                self.scope.runtime_state.write_text(json.dumps(identity.to_json()))
                self.scope.runtime_state.chmod(0o600)
                raise failure
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(process, 'require_executable_file'), patch.object(process.runner, 'validate_config'), \
                    patch.object(process.subprocess, 'Popen', return_value=child), \
                    patch.object(process.ident, 'read_identity', return_value=identity), \
                    patch.object(process.ident, 'alive', return_value=True), patch.object(process.ident, 'stop') as stop, \
                    patch.object(process.ports, 'wait_listening'), patch.object(backend, '_write_state', side_effect=publication):
                with self.assertRaises(type(failure)):
                    backend.start()
                stop.assert_called_once_with(identity)
                child.terminate.assert_not_called()
                child.kill.assert_not_called()
                self.assertFalse(self.scope.runtime_state.exists())

    def test_process_cleanup_refuses_identity_drift_and_reports_distinct_failure(self):
        from unittest.mock import Mock
        from mihomoctl.lifecycle import process
        from mihomoctl.identity import ProcessIdentity
        child = Mock(pid=123456)
        child.poll.return_value = None
        identity = ProcessIdentity(child.pid, os.geteuid(), 1, '/core', '/config')
        with patch.object(process.ident, 'alive', return_value=False), \
                patch.object(process.ident, 'exited', return_value=False), patch.object(process.ident, 'stop') as stop:
            with self.assertRaises(StateError):
                process._terminate_child(child, identity)
            stop.assert_not_called()
            child.terminate.assert_not_called()
            child.kill.assert_not_called()

    def test_private_forged_identity_receipt_does_not_signal_a_live_unrelated_child(self):
        import subprocess
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.identity import read_identity
        from mihomoctl.lifecycle import process
        require_private_dir(self.scope.state_root, create=True)
        config = str(self.scope.config_root / 'unrelated.yaml')
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)', '-f', config])
        try:
            identity = read_identity(child.pid)
            manager = Manager(core=CoreSettings(identity.exe, config, 'process'))
            backend = process.ProcessBackend(self.scope, manager, [], None)
            state = dict(identity.to_json(), backend='process', binary=identity.exe, start_time=identity.start_time + 1)
            self.scope.runtime_state.write_text(json.dumps(state))
            self.scope.runtime_state.chmod(0o600)
            before = self.scope.runtime_state.read_bytes()
            with self.assertRaises(StateError) as error:
                backend.stop()
            self.assertEqual(error.exception.code, 'pid-reuse-suspected')
            self.assertIsNone(child.poll())
            self.assertEqual(self.scope.runtime_state.read_bytes(), before)
            with self.assertRaises(StateError):
                backend.running_identity()
            self.assertIsNone(child.poll())
        finally:
            child.terminate()
            child.wait(timeout=5)

    def test_unsafe_corrupt_or_cross_uid_receipts_are_preserved_without_signals(self):
        from mihomoctl.config import Manager, CoreSettings
        from mihomoctl.lifecycle import process
        require_private_dir(self.scope.state_root, create=True)
        backend = process.ProcessBackend(self.scope, Manager(core=CoreSettings('/core', '/config', 'process')), [], None)
        state = dict(backend='process', pid=123456, uid=os.geteuid(), start_time=1, exe='/core', binary='/core', config='/config')
        for kind in ('unsafe-file', 'symlink', 'cross-uid', 'corrupt', 'unsafe-parent'):
            with self.subTest(kind=kind):
                path = self.scope.runtime_state
                if path.exists() or path.is_symlink():
                    path.unlink()
                self.scope.state_root.chmod(0o700)
                data = dict(state)
                if kind == 'cross-uid':
                    data['uid'] += 1
                if kind == 'symlink':
                    target = self.scope.state_root / 'target.json'
                    target.write_text(json.dumps(data))
                    target.chmod(0o600)
                    path.symlink_to(target)
                else:
                    path.write_text('malformed{' if kind == 'corrupt' else json.dumps(data))
                    path.chmod(0o644 if kind == 'unsafe-file' else 0o600)
                if kind == 'unsafe-parent':
                    self.scope.state_root.chmod(0o777)
                with patch.object(process.ident, 'stop') as stop:
                    with self.assertRaises((StateError, ConfigError)):
                        backend.stop()
                    stop.assert_not_called()
                    self.assertTrue(path.exists())
        self.scope.state_root.chmod(0o700)

    def test_tun_no_change_refuses_replaced_device_identity(self):
        from types import SimpleNamespace
        from mihomoctl.app import Application
        from mihomoctl.config import Manager, TunSettings
        from mihomoctl.lifecycle import tun
        require_private_dir(self.scope.tun_receipt.parent, create=True)
        self.scope.tun_receipt.write_text(json.dumps({'enabled': True, 'device': 'mihomo0', 'ifindex': 1}))
        self.scope.tun_receipt.chmod(0o600)
        manager = Manager(tun=TunSettings(True, 'mihomo0'))
        fake = SimpleNamespace(resolve=lambda: (manager, [], None, None, {}))
        with patch.object(tun, '_require_system'), patch.object(tun.systemd, 'systemd_available', return_value=True), \
                patch('mihomoctl.app.Application', return_value=fake), \
                patch.object(tun, '_verify_owned', side_effect=StateError('tun-ownership-unverified')) as verify:
            with self.assertRaises(StateError):
                tun.enable(self.scope)
            verify.assert_called_once_with(self.scope, manager)

    def test_tun_kernel_owner_rejects_foreign_persistent_or_unidentified_device(self):
        from mihomoctl.config import Manager, CoreSettings, TunSettings
        from mihomoctl.identity import ProcessIdentity
        from mihomoctl.lifecycle import tun, systemd
        manager = Manager(core=CoreSettings('/core', '/config', 'systemd'), tun=TunSettings(True, 'mihomo0'))
        identity = ProcessIdentity(123, 234, 345, '/core', '/config')
        for persistent, has_fd, actual in ((False, False, identity), (True, True, identity), (False, True, None)):
            observed = {'linkinfo': {'info_kind': 'tun', 'info_data': {'persist': persistent}}}
            with self.subTest(persistent=persistent, has_fd=has_fd, actual=actual), \
                    patch.object(tun, '_read_config', return_value={'mixed-port': 7890, 'authentication': ['user:pass']}), \
                    patch.object(systemd, 'SystemdBackend') as Backend, patch.object(tun, '_owns_tun_fd', return_value=has_fd):
                Backend.return_value.running_identity.return_value = actual
                with self.assertRaises(StateError):
                    tun._kernel_device_owner(self.scope, manager, observed)

    def test_tun_kernel_owner_requires_management_in_the_core_namespace(self):
        from mihomoctl.config import Manager, CoreSettings, TunSettings
        from mihomoctl.identity import ProcessIdentity
        from mihomoctl.lifecycle import tun, systemd
        manager = Manager(core=CoreSettings('/core', '/config', 'systemd'), tun=TunSettings(True, 'mihomo0'))
        actual = ProcessIdentity(os.getpid(), os.geteuid(), 1, '/core', '/config')
        observed = {'linkinfo': {'info_kind': 'tun', 'info_data': {'persist': False}}}
        with patch.object(tun, '_read_config', return_value={'mixed-port': 7890, 'authentication': ['user:pass']}), \
                patch.object(systemd, 'SystemdBackend') as Backend, patch.object(tun, '_owns_tun_fd', return_value=True):
            Backend.return_value.running_identity.return_value = actual
            self.assertEqual(tun._kernel_device_owner(self.scope, manager, observed), actual)

    def test_tun_receipt_reconciliation_is_explicit_and_read_status_never_writes(self):
        from mihomoctl.config import Manager, TunSettings
        from mihomoctl.identity import ProcessIdentity
        from mihomoctl.lifecycle import tun
        require_private_dir(self.scope.tun_receipt.parent, create=True)
        receipt = {'enabled': True, 'device': 'mihomo0', 'ifindex': 1}
        self.scope.tun_receipt.write_text(json.dumps(receipt))
        self.scope.tun_receipt.chmod(0o600)
        original = self.scope.tun_receipt.read_bytes()
        manager = Manager(tun=TunSettings(True, 'mihomo0'))
        observed = {'ifindex': 2}
        identity = ProcessIdentity(123, 234, 345, '/core', '/config')
        with patch.object(tun, 'load_manager', return_value=manager), \
                patch.object(tun, '_verify_owned', return_value=(receipt, observed, identity)):
            self.assertFalse(tun.status(self.scope)['receipt_current'])
            self.assertEqual(self.scope.tun_receipt.read_bytes(), original)
            self.assertTrue(run_transaction(self.scope, 'tun-reconcile', lambda tx: tun.synchronize_receipt(self.scope, manager, tx=tx)))
            updated = json.loads(self.scope.tun_receipt.read_text())
            self.assertEqual(updated['ifindex'], 2)
            self.assertEqual(updated['runtime_identity'], identity.to_json())

    def test_tun_reconciliation_keeps_authorization_private_under_readable_state_root(self):
        from mihomoctl.config import Manager, TunSettings
        from mihomoctl.credentials import write_atomic
        from mihomoctl.identity import ProcessIdentity
        from mihomoctl.lifecycle import tun
        require_private_dir(self.scope.state_root, create=True)
        self.scope.state_root.chmod(0o750)
        receipt = {'enabled': True, 'device': 'mihomo0'}
        run_transaction(self.scope, 'tun-authorization',
                        lambda tx: tx.write_text(self.scope.tun_receipt, json.dumps(receipt)))
        identity = ProcessIdentity(os.getpid(), os.geteuid(), 123, '/core', '/config')
        manager = Manager(tun=TunSettings(True, 'mihomo0'))
        # Kernel ownership is independently covered above. Keep all filesystem
        # publication and permission validation real, including startup's
        # non-transactional reconciliation path.
        with patch.object(tun, '_verify_owned', return_value=(receipt, {'ifindex': 9}, identity)):
            self.assertTrue(tun.synchronize_receipt(self.scope, manager))
        self.assertEqual(self.scope.state_root.stat().st_mode & 0o777, 0o750)
        self.assertEqual(self.scope.tun_receipt.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(self.scope.tun_receipt.stat().st_mode & 0o777, 0o600)
        self.assertEqual(json.loads(self.scope.tun_receipt.read_text())['runtime_identity'], identity.to_json())
        with self.assertRaises(ConfigError):
            write_atomic(self.scope.state_root / 'public-parent-refused.json', '{}')
        self.assertFalse((self.scope.state_root / 'public-parent-refused.json').exists())
        self.scope.tun_receipt.parent.chmod(0o750)
        with patch.object(tun, '_verify_owned', return_value=(receipt, {'ifindex': 10}, identity)):
            with self.assertRaises(ConfigError):
                tun.synchronize_receipt(self.scope, manager)

    def test_tun_commit_failure_restores_previous_runtime_after_file_rollback(self):
        from types import SimpleNamespace
        from mihomoctl.config import CoreSettings, Manager, render_manager
        from mihomoctl.lifecycle import tun, systemd
        require_private_dir(self.scope.config_root, create=True)
        config = self.scope.config_root / 'core.yaml'
        original_config = b'rules: [MATCH,DIRECT]\n'
        config.write_bytes(original_config)
        config.chmod(0o600)
        manager = Manager(core=CoreSettings('/core', str(config), 'systemd'))
        original_manager = render_manager(manager).encode()
        self.scope.manager_path.write_bytes(original_manager)
        self.scope.manager_path.chmod(0o600)
        fake = SimpleNamespace(resolve=lambda: (manager, [], None, None, {'rules': ['MATCH,DIRECT']}), health=lambda: [])
        snapshots = []
        def restart(**kwargs):
            snapshots.append(config.read_bytes())
        device = {'ifindex': 9, 'linkinfo': {'info_kind': 'tun'}}
        with patch.object(tun, '_require_system'), patch.object(systemd, 'systemd_available', return_value=True), \
                patch('mihomoctl.app.Application', return_value=fake), patch.object(systemd, 'SystemdBackend') as Backend, \
                patch.object(systemd, '_systemctl') as reload, \
                patch.object(systemd, 'ensure_service_account', return_value=SimpleNamespace(pw_uid=os.geteuid())), \
                patch.object(tun.runner, 'validate_config'), patch.object(tun, '_device', side_effect=[None, device, None]), \
                patch.object(tun, '_device_route_present', return_value=True), \
                patch.object(Transaction, 'commit', side_effect=OSError('journal failed')):
            Backend.return_value.status.return_value = {'running': True}
            Backend.return_value.restart.side_effect = restart
            with self.assertRaises(OSError):
                tun.enable(self.scope)
            self.assertEqual(reload.call_count, 2)
        self.assertEqual(len(snapshots), 2)
        self.assertIn(b'enable: true', snapshots[0])
        self.assertEqual(snapshots[1], original_config)
        self.assertEqual(self.scope.manager_path.read_bytes(), original_manager)
        self.assertFalse(self.scope.tun_receipt.exists())
        self.assertFalse((systemd.dropin_dir(self.scope) / systemd.TUN_DROPIN).exists())

    def test_migration_journal_rollback_restores_shell_bytes_and_rejects_drift(self):
        startup = self.home / '.bashrc'
        original = b'preserve\r\nmanaged block\r\ntrailer\r\n'
        startup.write_bytes(original)
        startup.chmod(0o640)
        result = run_transaction(self.scope, 'migrate',
            lambda tx: (tx.write_bytes(startup, b'preserve\r\ntrailer\r\n', mode=0o640), str(tx.backup_root))[1],
            allow_paths={startup})
        startup.write_bytes(b'changed after migration')
        with self.assertRaises(TransactionError):
            restore_backup(self.scope, result)
        self.assertEqual(startup.read_bytes(), b'changed after migration')
        startup.write_bytes(b'preserve\r\ntrailer\r\n')
        with self.assertRaisesRegex(TransactionError, 'historical-rollback-disabled'):
            restore_backup(self.scope, result)
        self.assertEqual(startup.read_bytes(), b'preserve\r\ntrailer\r\n')
        self.assertFalse(Path(result).exists())
        self.assertEqual(startup.stat().st_mode & 0o777, 0o640)

    def test_transaction_refuses_symlink_ancestor_and_restores_metadata(self):
        require_private_dir(self.scope.config_root, create=True)
        target = self.scope.config_root / 'owned'
        target.write_bytes(b'old secret')
        target.chmod(0o640)
        def failure(tx):
            tx.write_bytes(target, b'new secret', mode=0o600)
            raise StateError('activation-failed')
        with self.assertRaises(StateError):
            run_transaction(self.scope, 'failure', failure)
        self.assertEqual(target.read_bytes(), b'old secret')
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        (self.scope.config_root / 'link').symlink_to(self.home, target_is_directory=True)
        with self.assertRaises(ConfigError):
            run_transaction(self.scope, 'escape', lambda tx: tx.write_bytes(self.scope.config_root / 'link/escape', b'bad'))
        self.assertFalse((self.home / 'escape').exists())

    def test_migration_imports_real_configuration_is_idempotent_and_preserves_custom_loader(self):
        import yaml
        legacy = self.scope.config_root.parent / 'mihomo'
        require_private_dir(legacy, create=True)
        binary = self.home / 'validation-fixture'
        binary.write_text('#!/bin/sh\nexit 0\n')
        binary.chmod(0o700)
        files = {'mihomo-shell.conf': 'MIHOMO_PORT=7890\n',
                 'client.env': 'MIHOMO_HTTP_PROXY=http://user:pass@127.0.0.1:7890\nMIHOMO_HTTPS_PROXY=http://user:pass@127.0.0.1:7890\nMIHOMO_ALL_PROXY=socks5h://user:pass@127.0.0.1:7890\n',
                 'config.yaml': 'mixed-port: 7890\nauthentication: ["user:pass"]\nrules: ["MATCH,DIRECT"]\n'}
        for name, text in files.items():
            (legacy / name).write_text(text)
            (legacy / name).chmod(0o600)
        startup = self.home / '.bashrc'
        startup.write_text('before\n' + BEGIN_MARKER + '\ncustom_action\n' + END_MARKER + '\nafter\n')
        startup.chmod(0o600)
        before = startup.read_bytes()
        self.assertEqual(preview(self.scope)['loader_blocks'][str(startup)], 'ambiguous')
        with self.assertRaises(StateError):
            apply(self.scope, remove_loader=True, core=str(binary))
        self.assertFalse(self.scope.manager_path.exists())
        self.assertEqual(startup.read_bytes(), before)

        result = apply(self.scope, remove_loader=False, core=str(binary))
        self.assertTrue(result['imported'])
        manager = yaml.safe_load(self.scope.manager_path.read_text())
        self.assertEqual(manager['profiles']['default']['http_listener'], 'mixed-port')
        self.assertEqual(Path(manager['core']['config']).read_text(), files['config.yaml'])
        self.assertTrue(apply(self.scope, remove_loader=False, core=str(binary))['idempotent'])
        self.assertEqual(startup.read_bytes(), before)

    def test_migration_rejects_client_core_authentication_mismatch_before_publication(self):
        from mihomoctl.lifecycle import runner
        legacy = self.scope.config_root.parent / 'mihomo'
        require_private_dir(legacy, create=True)
        contents = {'mihomo-shell.conf': 'MIHOMO_PORT=7890\n',
            'client.env': 'MIHOMO_HTTP_PROXY=http://user:wrong@127.0.0.1:7890\nMIHOMO_HTTPS_PROXY=http://user:wrong@127.0.0.1:7890\nMIHOMO_ALL_PROXY=socks5h://user:wrong@127.0.0.1:7890\n',
            'config.yaml': 'mixed-port: 7890\nauthentication: ["user:correct"]\n'}
        for name, text in contents.items():
            path = legacy / name
            path.write_text(text)
            path.chmod(0o600)
        with patch.object(runner, 'validate_config') as validate:
            with self.assertRaises(ConfigError) as error:
                apply(self.scope, core='/unused')
            self.assertEqual(error.exception.code, 'legacy-credentials-mismatch')
            validate.assert_not_called()
        self.assertFalse(self.scope.manager_path.exists())
        self.assertFalse(self.scope.credentials_dir.exists())

    def test_default_migration_removes_only_receipted_loader_and_can_restore_exact_bytes(self):
        import hashlib
        block = BEGIN_MARKER + '\n# historical exact loader\n' + END_MARKER
        startup = self.home / '.bashrc'
        original = b'prefix\r\n' + block.encode() + b'\r\nsuffix\r\n'
        startup.write_bytes(original)
        startup.chmod(0o640)
        root = self.scope.data_root.parent / 'mihomo-userctl'
        generation = root / 'generations' / 'old-generation'
        require_private_dir(generation, create=True)
        record = generation / 'installation.json'
        record.write_text(json.dumps({'home': str(self.home), 'bashrc': str(startup),
            'loader_sha256': hashlib.sha256(block.encode()).hexdigest()}))
        record.chmod(0o600)
        (root / 'current').symlink_to(generation, target_is_directory=True)
        result = apply(self.scope, import_config=False)
        self.assertEqual(result['loader_removed'], [str(startup)])
        self.assertEqual(startup.read_bytes(), b'prefix\r\nsuffix\r\n')
        self.assertTrue(apply(self.scope, import_config=False)['idempotent'])
        self.assertNotIn('backup', result)
        self.assertEqual(list(self.scope.backups_root.iterdir()), [])
        self.assertEqual(startup.read_bytes(), b'prefix\r\nsuffix\r\n')
        self.assertEqual(startup.stat().st_mode & 0o777, 0o640)


if __name__ == '__main__':
    unittest.main()
