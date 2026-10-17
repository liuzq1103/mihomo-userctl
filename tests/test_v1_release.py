"""Release discovery, transport and optional notification contracts."""
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from mihomoctl import notifications, release
from mihomoctl.cli import main
from mihomoctl.scope import Scope

ROOT = Path(__file__).resolve().parents[1]


class DiscoveryTests(unittest.TestCase):
    def metadata(self, **changes):
        return dict({'tag_name': 'v9.0.0', 'draft': False, 'prerelease': False}, **changes)

    def test_discovery_and_non_latest_wording(self):
        with patch.object(release, 'metadata', return_value=self.metadata()):
            data = release.check()
        self.assertTrue(data['newer_available'])
        for version in ('1.0.0', '1.2.0', '9.0.0'):
            data = release.observation(self.metadata(tag_name='v1.2.0'), version)
            text = release.check_text(data)
            self.assertNotIn('latest', text.lower())
            self.assertEqual(data['newer_available'], version == '1.0.0')

    def test_invalid_versions_and_urls_refused(self):
        for version in ('1.2', '1.2.3rc1', '../1.2.3', '1.2.3\n', None):
            with self.subTest(version=version), self.assertRaises(release.ReleaseError):
                release.version_key(version)
        for url in ('http://github.com/a', 'https://evil.example/a',
                    'https://github.com@evil.example/a', 'https://u:p@github.com/a',
                    'https://github.com:444/a', 'https://github.com/a\n'):
            with self.subTest(url=url), self.assertRaises(release.ReleaseError):
                release.validate_url(url)

    def test_metadata_failure_and_stable_filter(self):
        def download(data):
            def write(_url, path, *_args):
                Path(path).write_text(json.dumps(data))
            return write
        for changes in ({'draft': True}, {'prerelease': True}, {'tag_name': 'v1.2.0rc1'}):
            with patch.object(release, 'transfer', side_effect=download(self.metadata(**changes))):
                with self.assertRaises(release.ReleaseError):
                    release.metadata()
        with patch.object(release, 'transfer', side_effect=download(self.metadata())):
            self.assertEqual(release.metadata()['tag_name'], 'v9.0.0')
            with self.assertRaises(release.ReleaseError):
                release.metadata('v1.2.0')

    def test_explicit_failure_preserves_envelope_contract(self):
        with patch.object(release, 'check', side_effect=release.ReleaseError('release-network-unavailable')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['release', 'check', '--json']), 2)
        self.assertEqual(json.loads(output.getvalue())['overall'], 'UNVERIFIED')

    def test_transport_timeout_includes_stalled_dns_worker(self):
        run = subprocess.run
        def stalled(_args, **kwargs):
            return run([sys.executable, '-c', 'import time; time.sleep(60)'], **kwargs)
        with tempfile.TemporaryDirectory() as directory, patch.object(release.subprocess, 'run', side_effect=stalled):
            before = time.monotonic()
            with self.assertRaises(release.ReleaseError):
                release.transfer(release.API + '/releases/latest', Path(directory) / 'body', 8192, .2)
            self.assertLess(time.monotonic() - before, 2)

    def test_tls_http_and_proxy_failures_are_unverified(self):
        import ssl
        import urllib.error
        from mihomoctl import release_network
        errors = [ssl.SSLError('TLS failure'), OSError('DNS failure')]
        errors += [urllib.error.HTTPError(release.API, code, 'blocked', {}, None)
                   for code in (403, 407, 429)]
        with tempfile.TemporaryDirectory() as directory:
            for error in errors:
                with patch.object(release_network.urllib.request, 'build_opener') as opener:
                    opener.return_value.open.side_effect = error
                    with self.assertRaises(type(error)):
                        release_network.download(release.API, Path(directory) / 'body', 1024)
                with patch.object(release.subprocess, 'run') as run:
                    run.return_value.returncode = 2
                    with self.assertRaisesRegex(release.ReleaseError, 'release-network-unavailable'):
                        release.transfer(release.API, Path(directory) / 'body', 1024, 1)

    def test_redirect_and_truncated_or_oversized_transport_are_refused(self):
        import urllib.request
        from mihomoctl import release_network
        guard = release_network.RedirectGuard()
        with self.assertRaises(release.ReleaseError):
            guard.redirect_request(urllib.request.Request(release.API), None, 302, '', {}, 'https://evil.example')
        for body, headers, limit in ((b'short', {'Content-Length': '10'}, 32),
                                     (b'0123456789', {}, 4),
                                     (b'x', {'Content-Length': 'invalid'}, 32)):
            response = io.BytesIO(body)
            response.status = 200
            response.headers = headers
            with tempfile.TemporaryDirectory() as directory, \
                    patch.object(release_network.urllib.request, 'build_opener') as opener:
                opener.return_value.open.return_value = response
                with self.assertRaises(ValueError):
                    release_network.download(release.API, Path(directory) / 'body', limit)


@unittest.skipUnless(sys.platform == 'linux' and os.geteuid() != 0, 'Linux user scope')
class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.base.chmod(0o700)
        self.env = patch.dict(os.environ, {key: str(self.base / name) for key, name in (
            ('HOME', 'home'), ('XDG_STATE_HOME', 'state'), ('XDG_DATA_HOME', 'data'),
            ('XDG_CONFIG_HOME', 'config'), ('XDG_CACHE_HOME', 'cache'), ('XDG_RUNTIME_DIR', 'runtime'))})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.scope = Scope()

    def seed(self, **changes):
        path = notifications._paths(self.scope)
        data = {'attempted_at': time.time(), 'observation': release.observation(
            {'tag_name': 'v9.0.0'})}
        data.update(changes)
        notifications.write_atomic(path, json.dumps(data))
        return path

    def test_first_check_is_detached_then_next_entry_notifies_once(self):
        with patch.object(notifications.subprocess, 'Popen') as spawn, \
                patch.object(release, 'check', return_value=release.observation({'tag_name': 'v9.0.0'})):
            self.assertIsNone(notifications.prepare(self.scope))
            self.assertTrue(spawn.call_args.kwargs['start_new_session'])
            self.assertEqual(spawn.call_args.kwargs['stdout'], subprocess.DEVNULL)
            notifications.refresh(self.scope)
            notice = notifications.prepare(self.scope)
            self.assertIn('9.0.0', notice)
            self.assertIn('update --latest', notice)
            self.assertIsNone(notifications.prepare(self.scope))
            self.assertEqual(spawn.call_count, 1)

    def test_failed_attempt_is_rate_limited(self):
        with patch.object(notifications.subprocess, 'Popen', side_effect=OSError) as spawn:
            self.assertIsNone(notifications.prepare(self.scope))
            self.assertIsNone(notifications.prepare(self.scope))
            self.assertEqual(spawn.call_count, 1)

    def test_dedup_survives_current_version_changes(self):
        self.seed()
        self.assertIsNotNone(notifications.prepare(self.scope))
        with patch.object(notifications, '__version__', '9.0.0'):
            self.assertIsNone(notifications.prepare(self.scope))
        with patch.object(notifications, '__version__', '1.0.0'):
            self.assertIsNone(notifications.prepare(self.scope))

    def test_unchanged_state_is_not_rewritten_and_clock_rollback_recovers(self):
        self.seed(notified='9.0.0')
        with patch.object(notifications, 'write_atomic', side_effect=AssertionError('unnecessary write')):
            self.assertIsNone(notifications.prepare(self.scope))
        self.seed(attempted_at=time.time() + 7200)
        with patch.object(notifications.subprocess, 'Popen') as spawn:
            self.assertIn('9.0.0', notifications.prepare(self.scope))
            self.assertEqual(spawn.call_count, 1)

    def test_curses_notice_wraps_each_line_without_control_characters(self):
        from mihomoctl.controller.controller_console import release_notice_lines
        notice = 'Newer release 9.0.0\n' + release.WEB + '/releases/tag/v9.0.0\nUpgrade: mihomoctl update --latest'
        for width in (60, 80, 140):
            lines = release_notice_lines(notice, width)
            self.assertTrue(all('\n' not in line and len(line) <= width-2 for line in lines))
            self.assertIn('Upgrade: mihomoctl update --latest', '\n'.join(lines))
        from mihomoctl.command_spec import validate
        validate('update', ['--latest'])

    def test_bad_state_and_concurrent_lock_are_silent(self):
        path = self.seed()
        for body in ('[]', 'not json', '{"notified":"bad"}', '{"attempted_at":NaN}'):
            notifications.write_atomic(path, body)
            self.assertIsNone(notifications.prepare(self.scope))
        self.seed()
        path.chmod(0o644)
        self.assertIsNone(notifications.prepare(self.scope))
        path.chmod(0o600)
        from mihomoctl.locks import operation_lock
        with operation_lock(self.scope, 'release-notifications'):
            self.assertIsNone(notifications.prepare(self.scope))

    def test_disabled_help_json_and_pipe_do_not_start_checks(self):
        with patch.object(notifications, 'prepare', side_effect=AssertionError('unexpected notification')), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['version', '--json']), 0)
            self.assertEqual(main(['version']), 0)
            self.assertEqual(main(['status', '--help']), 0)
        with patch.dict(os.environ, MIHOMOCTL_NO_UPDATE_CHECK='1'):
            self.assertIsNone(notifications.prepare(self.scope))

    def test_tty_notice_does_not_change_command_result_or_stdout(self):
        self.seed()
        with patch.object(sys.stdin, 'isatty', return_value=True), \
                contextlib.redirect_stdout(io.StringIO()) as out, \
                contextlib.redirect_stderr(io.StringIO()) as err:
            with patch.object(out, 'isatty', return_value=True), patch.object(err, 'isatty', return_value=True):
                self.assertEqual(main(['version']), 0)
        self.assertIn('mihomoctl ', out.getvalue())
        self.assertNotIn('9.0.0', out.getvalue())
        self.assertIn('9.0.0', err.getvalue())

    def test_worker_hard_deadline(self):
        code = ("import sys,runpy,time;sys.path.insert(0,sys.argv[1]);"
                "import mihomoctl.notifications as n;n.refresh=lambda scope:time.sleep(60);"
                "sys.argv=['worker','user'];runpy.run_path(sys.argv[0] if False else "
                "str(__import__('pathlib').Path(n.__file__).with_name('release_worker.py')),run_name='__main__')")
        started = time.monotonic()
        result = subprocess.run([sys.executable, '-I', '-c', code, str(ROOT)],
                                capture_output=True, start_new_session=True, timeout=8)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assertLess(time.monotonic() - started, 7)


if __name__ == '__main__':
    unittest.main()
