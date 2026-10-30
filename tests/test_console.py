"""State, real socket ownership, bounded jobs and node-only transactions."""
import hashlib
import contextlib
import io
import json
import importlib.util
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock

if sys.platform != "linux":
    raise unittest.SkipTest("Linux ownership, private paths and sockets")

from mihomoctl.controller import controller_state as state, controller_runtime as runtime
from mihomoctl.controller import controller_subscriptions as subscriptions, controller_transaction as transaction
from mihomoctl.controller.controller_types import ControlError
from mihomoctl.controller.controller_service import ConsoleService


class StoreTests(unittest.TestCase):
    def test_cli_delay_and_bridge_envelopes_preserve_codes_and_useful_detail(self):
        from mihomoctl.controller import controller
        from mihomoctl.cli import main
        from mihomoctl.controller.controller_types import ERROR_LABELS
        client = Mock()
        with patch('mihomoctl.bridge.bridge_environment', side_effect=lambda scope: contextlib.nullcontext({})), \
                patch.object(controller, 'read_config', return_value=(None, {}, None)), \
                patch.object(controller, 'endpoint', return_value=(1234, 'token')), \
                patch.object(controller, 'Client', return_value=client), \
                patch('mihomoctl.controller.controller_service.node_directory', return_value=({}, [{'name': 'A', 'provider': None}], 'supported')) as core:
            for code in ('node-not-in-core', 'node-unreachable', 'delay-timeout', 'controller-unreachable'):
                client.request.side_effect = ControlError(code, 1)
                with contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(['latency', 'A', '--json']), 1)
                error = json.loads(output.getvalue())['errors'][0]
                self.assertEqual(error['code'], code)
                if code in ERROR_LABELS:
                    self.assertIn(ERROR_LABELS[code], error['detail'])
                    self.assertNotIn(code, error['detail'])
                else:
                    self.assertNotIn('detail', error)
            core.return_value = ({}, [], 'supported')
            name = '👩\u200d💻\ufeff\u200b'
            with contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(['latency', name, '--json']), 1)
            error = json.loads(output.getvalue())['errors'][0]
            self.assertEqual(error['code'], 'unknown-node')
            self.assertIn(repr(name), error['detail'])
        self.assertEqual(str(ControlError('unlabelled', detail='useful')), 'unlabelled: useful')
        self.assertEqual(str(ControlError('controller-unreachable')), 'controller-unreachable')

    def test_plain_error_and_conditional_textual_hint(self):
        from mihomoctl.controller import controller_console as console
        from mihomoctl.controller.controller_types import ERROR_LABELS, TUI_INSTALL_COMMAND
        for available in (None, object()):
            service = Mock()
            service.read.side_effect = ControlError('node-not-in-core')
            with contextlib.redirect_stdout(io.StringIO()) as output, \
                    patch.object(console.sys.stdin, 'isatty', return_value=True), \
                    patch.object(console.sys.stdout, 'isatty', return_value=True), \
                    patch.object(console.importlib.util, 'find_spec', return_value=available), \
                    patch('builtins.input', side_effect=['1', 'q']):
                console.plain_console(service)
            self.assertEqual(TUI_INSTALL_COMMAND in output.getvalue(), available is None)
            self.assertIn('node-not-in-core', output.getvalue())
            self.assertIn(ERROR_LABELS['node-not-in-core'], output.getvalue())

    def test_curses_failure_draws_code_and_label(self):
        from mihomoctl.controller import controller_console as console
        from mihomoctl.controller.controller_types import ERROR_LABELS
        window = Mock()
        window.getmaxyx.return_value = (24, 80)
        window.getch.side_effect = [ord('t'), ord('q')]
        curses = Mock(KEY_UP=259, KEY_DOWN=258, KEY_LEFT=260, KEY_RIGHT=261, KEY_ENTER=343,
                      A_BOLD=1, A_DIM=2, A_REVERSE=4, A_NORMAL=0, error=RuntimeError)
        curses.wrapper.side_effect = lambda callback: callback(window)
        with patch.dict(sys.modules, {'curses': curses}), \
                patch.object(console.sys.stdin, 'isatty', return_value=True), \
                patch.object(console.sys.stdout, 'isatty', return_value=True), \
                patch('mihomoctl.notifications.take_tui_notice', return_value=None), \
                patch.object(console, 'snapshot', return_value={'groups': [
                    {'name': 'G', 'type': 'Selector', 'selected': 'A', 'members': ['A'], 'selectable': True}]}), \
                patch.object(console, 'measure_delay', side_effect=ControlError('node-unreachable')):
            console.tui(Mock())
        drawn = ' '.join(str(call.args[2]) for call in window.addstr.call_args_list)
        self.assertIn('node-unreachable', drawn)
        self.assertIn(ERROR_LABELS['node-unreachable'], drawn)

    def test_delay_http_failures_and_batch_keep_specific_codes(self):
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from mihomoctl.controller.controller_api import Client
        from mihomoctl.controller.controller_service import measure_delay
        from mihomoctl.controller.controller_types import ERROR_LABELS, TEST_URL
        from urllib.parse import parse_qs, urlsplit
        class Handler(BaseHTTPRequestHandler):
            status = 404
            seen = []
            def do_GET(self):
                type(self).seen.append(self.path)
                self.send_response(type(self).status)
                self.end_headers()
                self.wfile.write(b'{}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        client = Client(server.server_port, 'fixture')
        service = ConsoleService.__new__(ConsoleService)
        with patch.object(service, 'client', return_value=client), \
                patch('mihomoctl.controller.controller_service.node_directory', return_value=({}, [{'name': 'A /旗', 'provider': None}], 'supported')):
            for status, code in ((404, 'node-not-in-core'), (503, 'node-unreachable'), (504, 'delay-timeout')):
                Handler.status = status
                with self.subTest(status=status):
                    with self.assertRaises(ControlError) as caught:
                        measure_delay(client, 'A /旗')
                    self.assertEqual(caught.exception.code, code)
                    self.assertIn(ERROR_LABELS[code], str(caught.exception))
                    with self.assertRaises(ControlError) as caught:
                        service.latency('A /旗')
                    self.assertEqual(caught.exception.code, code)
                    result = service.batch_latency(['A /旗'])
                    self.assertEqual(result['results'][0]['error'], code)
            # Unmapped requests and explicitly optional capabilities keep the old behavior.
            with self.assertRaises(ControlError) as caught:
                client.request('/version')
            self.assertEqual(caught.exception.code, 'controller-request-failed')
            Handler.status = 404
            with self.assertRaises(ControlError) as caught:
                client.request('/optional', optional=True)
            self.assertEqual(caught.exception.code, 'controller-capability-unsupported')
        path = Handler.seen[0]
        self.assertTrue(path.startswith('/proxies/A%20%2F%E6%97%97/delay?'))
        self.assertEqual(parse_qs(urlsplit(path).query), {'url': [TEST_URL], 'timeout': ['5000']})

    def test_unknown_node_includes_exact_requested_spelling(self):
        service = ConsoleService.__new__(ConsoleService)
        name = '🇺🇸 US / 节点\u200d\u200b\ufeff'
        with patch.object(service, 'client'), patch('mihomoctl.controller.controller_service.node_directory', return_value=({}, [], 'supported')):
            with self.assertRaises(ControlError) as caught:
                service.latency(name)
        self.assertEqual(caught.exception.code, 'unknown-node')
        self.assertIn(repr(name), str(caught.exception))

    def test_curses_legend_fits_terminal_cells(self):
        from mihomoctl.controller.controller_console import legend_lines, display_width, curses_header
        for width in (30, 40, 60, 80, 100):
            lines = legend_lines(width - 3)
            self.assertEqual(len(lines), 2)
            self.assertTrue(all(display_width(line) <= width - 3 for line in lines))
            for key in ('Tab', 'Enter', '/', 'r', 't', 'c', 'f', 'm', 'o', 'y', 'q'):
                self.assertIn(key, ' '.join(lines))
        for width in (57, 77, 97):
            header = curses_header(width)
            self.assertIn('Nodes', header)
            self.assertIn('节点', header)
            self.assertLessEqual(display_width(header), width)
            for key in ('/', 'c', 'o', 'm', 'Search', 'Conn', 'Override', 'Manual'):
                self.assertIn(key, header)

    def test_curses_legend_never_raises_or_drops_keys_at_narrow_widths(self):
        from mihomoctl.controller.controller_console import legend_lines, curses_header, wrap_cells, release_notice_lines
        for width in (0, 1, 5, 10, 20, 25, 30, 40, 60, 80):
            with self.subTest(width=width):
                rows = legend_lines(width)
                self.assertLessEqual(len(rows), 2)
                keys = ' '.join(rows).split()
                for key in ('↑↓', 'Tab', 'Enter', 'q', '/', 'r', 't', 'c', 'f', 'm', 'o', 'y'):
                    self.assertIn(key, keys)
                # Other width-sensitive render helpers must degrade without raising.
                self.assertIsInstance(curses_header(width), str)
                self.assertTrue(wrap_cells('节点 A', width))
                self.assertTrue(release_notice_lines('A release notice', width))

    def test_main_module_keeps_generic_guidance_for_unlabelled_errors(self):
        import runpy
        from mihomoctl.controller import controller_config
        with patch.object(controller_config, 'read_config', side_effect=ControlError('unlabelled-fixture')), \
                patch.object(sys, 'argv', ['controller.py', 'latency', 'A', '--json']), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(SystemExit):
                runpy.run_module('mihomoctl.controller.controller', run_name='__main__')
        error = json.loads(output.getvalue())['error']
        self.assertIn('操作未完成；请检查私有配置及运行环境', error['message'])
        self.assertNotEqual(error['code'], error['message'])

    def test_stream_stop_prevents_late_data_and_redacts_reader_failure(self):
        store = state.Store()
        self.addCleanup(store.close)
        entered, release = threading.Event(), threading.Event()
        def stream(emit, stop):
            emit({"message": "safe"})
            entered.set()
            release.wait(2)
            emit({"message": "late"})
        self.assertTrue(store.stream("logs", stream))
        self.assertTrue(entered.wait(1))
        self.assertFalse(store.stream("logs", stream))
        store.stop_stream("logs")
        release.set()
        time.sleep(.03)
        self.assertEqual(list(store.state.logs), [{"message": "safe"}])
        def failed(emit, stop):
            raise RuntimeError("PRIVATE-CREDENTIAL")
        store.stream("logs", failed)
        for _ in range(100):
            if store.state.snapshots["logs"].error:
                break
            time.sleep(.01)
        self.assertEqual(store.state.snapshots["logs"].error, "stream-unverified")
        self.assertEqual(store.state.snapshots["logs"].freshness, "stale")

    def test_late_result_does_not_replace_newer_snapshot(self):
        store = state.Store()
        self.addCleanup(store.close)
        entered, release = threading.Event(), threading.Event()
        def old():
            entered.set(); release.wait(2)
            return "old"
        store.submit("nodes", old)
        self.assertTrue(entered.wait(1))
        self.assertFalse(store.submit("nodes", lambda: "duplicate"))
        store.invalidate("nodes")
        store.submit("nodes", lambda: "new")
        for _ in range(100):
            if store.state.snapshots["nodes"].value == "new":
                break
            time.sleep(.01)
        release.set(); time.sleep(.03)
        self.assertEqual(store.state.snapshots["nodes"].value, "new")

    def test_failed_refresh_retains_stale_data_and_redacts_exception(self):
        store = state.Store()
        self.addCleanup(store.close)
        store.state.snapshots["runtime"] = state.Snapshot(value={"service": "active"}, freshness="fresh")
        def failed():
            raise RuntimeError("https://private-token@private-host/")
        store.submit("runtime", failed)
        for _ in range(100):
            if store.drain():
                break
            time.sleep(.01)
        snapshot = store.state.snapshots["runtime"]
        self.assertEqual(snapshot.freshness, "stale")
        self.assertEqual(snapshot.value, {"service": "active"})
        self.assertEqual(snapshot.error, "operation-unverified")
        for index in range(3000):
            store.state.logs.append(index)
        self.assertEqual(len(store.state.logs), 2000)


class RuntimeTests(unittest.TestCase):

    def test_live_socket_owned_by_service_allowed_other_service_blocked(self):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0)); listener.listen()
            port = listener.getsockname()[1]
            properties = {"MainPID": str(os.getpid()), "ControlGroup": "", "ActiveState": "active"}
            with patch.object(runtime, "service_properties", return_value=properties):
                runtime.gate("mihomo", [port], after=True)
            with patch.object(runtime, "service_properties", return_value={"MainPID": "0"}):
                with self.assertRaisesRegex(ControlError, "ownership-unverified"):
                    runtime.gate("mihomo", [port])

    def test_wildcard_and_foreign_uid_are_blocked(self):
        with socket.socket() as listener:
            listener.bind(("0.0.0.0", 0)); listener.listen()
            with patch.object(runtime, "service_properties", return_value={"MainPID": str(os.getpid())}):
                with self.assertRaisesRegex(ControlError, "port-collision"):
                    runtime.gate("mihomo", [listener.getsockname()[1]])
        with patch.object(runtime, "listeners", return_value=[{"uid": os.getuid()+1, "family": "tcp", "address": "0100007F"}]), patch.object(runtime, "service_properties", return_value={}):
            with self.assertRaisesRegex(ControlError, "port-collision"):
                runtime.gate("mihomo", [17890])

    def test_missing_listener_cannot_pass_post_start(self):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
        with patch.object(runtime, "service_properties", return_value={}):
            runtime.gate("mihomo", [port])
            with self.assertRaisesRegex(ControlError, "listener-missing"):
                runtime.gate("mihomo", [port], after=True)


@unittest.skipUnless(importlib.util.find_spec("yaml"), "optional Controller YAML dependency")
class ConfiguredPortsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "config.yaml"

    def configure(self, text):
        self.config.write_text(text, encoding="utf-8")
        self.config.chmod(0o600)
        return text

    def test_listeners_only_config_matching_the_port_is_accepted(self):
        text = self.configure("listeners:\n- name: in\n  type: mixed\n  listen: 127.0.0.1\n"
                              "  port: 25000\n  udp: false\n  users:\n"
                              "  - {username: fixture-user, password: fixture-password}\n")
        self.assertEqual(runtime.configured_ports(self.config, 25000),
                         ([25000], hashlib.sha256(text.encode()).hexdigest()))

    def test_listeners_only_config_with_wrong_port_is_blocked(self):
        self.configure("listeners:\n- name: in\n  type: mixed\n  listen: 127.0.0.1\n  port: 25001\n")
        with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
            runtime.configured_ports(self.config, 25000)

    def test_legacy_mixed_port_still_accepted_and_mismatch_blocked(self):
        text = self.configure("mixed-port: 25000\n")
        self.assertEqual(runtime.configured_ports(self.config, 25000),
                         ([25000], hashlib.sha256(text.encode()).hexdigest()))
        self.configure("mixed-port: 25001\n")
        with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
            runtime.configured_ports(self.config, 25000)

    def test_non_mixed_listener_on_the_same_port_is_blocked(self):
        for kind in ("http", "socks"):
            with self.subTest(kind=kind):
                self.configure("listeners:\n- type: %s\n  listen: 127.0.0.1\n  port: 25000\n" % kind)
                with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
                    runtime.configured_ports(self.config, 25000)

    def test_mixed_entry_matches_from_any_position_or_count(self):
        mixed, wrong, other = ("- {name: in, type: mixed, port: 25000}\n",
                               "- {name: bad, type: mixed, port: 25001}\n",
                               "- {name: side, type: http, port: 25002}\n")
        for entries, accepted in ((mixed + other, True), (other + mixed, True),
                                  (wrong + mixed, True), (mixed + mixed, True),
                                  (wrong + other, False)):
            with self.subTest(entries=entries):
                self.configure("listeners:\n" + entries)
                if accepted:
                    self.assertEqual(runtime.configured_ports(self.config, 25000)[0], [25000])
                else:
                    with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
                        runtime.configured_ports(self.config, 25000)

    def test_legacy_mismatch_blocks_even_when_a_listener_would_match(self):
        self.configure("mixed-port: 25001\nlisteners:\n- {type: mixed, port: 25000}\n")
        with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
            runtime.configured_ports(self.config, 25000)

    def test_listener_port_shapes_and_structures_never_coerce(self):
        for body in ('- {type: mixed, port: "25000"}\n', "- {type: mixed, port: 25000.0}\n",
                     "- {type: mixed, port: true}\n", "- {type: mixed, port: null}\n",
                     "- {type: mixed}\n", "- {port: 25000}\n", "- mixed\n"):
            with self.subTest(body=body):
                self.configure("listeners:\n" + body)
                with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
                    runtime.configured_ports(self.config, 25000)
        for value in ("{name: in, type: mixed, port: 25000}", "mixed", ""):
            with self.subTest(value=value):
                self.configure("listeners: %s\n" % value)
                with self.assertRaisesRegex(ControlError, "configured-port-mismatch"):
                    runtime.configured_ports(self.config, 25000)

    def test_controller_port_append_and_conflict(self):
        secret = "secret: %s\n" % ("a" * 32)
        for header in ("listeners:\n- {type: mixed, listen: 127.0.0.1, port: 25000}\n",
                       "mixed-port: 25000\n"):
            with self.subTest(header=header.splitlines()[0]):
                self.configure(header + "external-controller: 127.0.0.1:26000\n" + secret)
                self.assertEqual(runtime.configured_ports(self.config, 25000)[0], [25000, 26000])
        self.configure("listeners:\n- {type: mixed, listen: 127.0.0.1, port: 25000}\n"
                       "external-controller: 127.0.0.1:25000\n" + secret)
        with self.assertRaisesRegex(ControlError, "controller-port-conflicts-with-proxy-port"):
            runtime.configured_ports(self.config, 25000)

    def test_digest_follows_file_bytes_and_absent_config_stays_compatible(self):
        self.assertEqual(runtime.configured_ports(self.config, 25000), ([25000], None))
        text = self.configure("listeners:\n- {type: mixed, listen: 127.0.0.1, port: 25000}\n")
        first = runtime.configured_ports(self.config, 25000)[1]
        self.assertEqual(first, hashlib.sha256(text.encode()).hexdigest())
        self.configure(text + "# extra byte\n")
        self.assertNotEqual(runtime.configured_ports(self.config, 25000)[1], first)




class DiagnosisTests(unittest.TestCase):
    def test_invalid_private_url_never_enters_subprocess_argv(self):
        service = ConsoleService("/not/read/by/this/test")
        with patch.object(subprocess, "run") as run:
            for target in ("https://user:private@example.com/", "https://example.com/?token=private", "http://example.com/", "https://localhost/"):
                with self.assertRaises(ControlError):
                    service.diagnose("url", target)
            with self.assertRaises(ControlError):
                service.diagnose("process", "1;kill")
            run.assert_not_called()

    def test_process_report_keeps_original_status_and_strips_terminal_controls(self):
        service = ConsoleService("/not/read/by/this/test")
        # V1 calls the shared same-UID reader in process; the Bash CLI is never
        # spawned. The contract under test is unchanged: the reader's own status
        # is preserved verbatim and terminal controls never reach the caller.
        item = {"pid": 123, "name": "untrusted\u001b[31m", "parent": {"pid": 1, "same_user": False},
                "proxy_environment": {"present": 0, "expected": 8, "classification": "direct",
                                      "matches_current_config": None},
                "connections": {"listener_established": 0, "other_non_loopback_established": 0}}
        with patch("mihomoctl.controller.process_reader.inspect", return_value=item) as inspect:
            result = service.diagnose("process", "123")
        inspect.assert_called_once()
        self.assertEqual(result["overall"], "PASS")
        self.assertEqual(result["scope"], "current-user-only")
        self.assertEqual(result["process"]["pid"], 123)
        self.assertEqual(result["process"]["proxy_environment"], item["proxy_environment"])
        self.assertNotIn("\u001b", result["process"]["name"])

    def test_process_diagnosis_keeps_the_reader_status_on_a_diagnostic_error(self):
        from mihomoctl.controller import process_reader as reader
        service = ConsoleService("/not/read/by/this/test")
        with patch("mihomoctl.controller.process_reader.inspect",
                   side_effect=reader.DiagnosticError("process-unreadable")):
            with self.assertRaisesRegex(reader.DiagnosticError, "process-unreadable"):
                service.diagnose("process", "123")


@unittest.skipUnless(importlib.util.find_spec("yaml"), "optional Controller YAML dependency")
class SubscriptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        environment = patch.dict(os.environ, {"HOME": str(self.root), "XDG_DATA_HOME": str(self.root / "data")})
        environment.start(); self.addCleanup(environment.stop)
        self.config = self.root / "config.yaml"
        self.original = '# private listener\nmixed-port: 17890\nsecret: unchanged-secret\nproxies: [{name: old, type: ss, password: KEEP}]\nproxy-groups: [{name: Proxy, type: select, proxies: [old]}]\nrules: [MATCH,DIRECT]\n'
        self.write(self.config, self.original)
        self.source = self.root / "source.yaml"
        self.write(self.source, 'proxies: [{name: new, type: ss, server: PRIVATE, port: 443, password: PRIVATE-TOKEN}]\n')
        self.service = subscriptions.Subscriptions(self.config, str(self.root))

    def write(self, path, content):
        path.write_text(content, encoding="utf-8"); path.chmod(0o600)

    def test_preview_private_apply_preserves_non_node_fields(self):
        plan = self.service.preview(source_file=self.source)
        self.assertEqual(self.config.read_text(), self.original)
        self.assertNotIn("PRIVATE", json.dumps(plan))
        for path in self.service.root.iterdir():
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/usr/bin/true"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(result["state"], "restart-required")
        self.assertNotIn("backup", result)
        import yaml
        before, after = yaml.safe_load(self.original), yaml.safe_load(self.config.read_text())
        before.pop("proxies"); after.pop("proxies")
        self.assertEqual(before, after)

    def test_full_config_alias_duplicate_and_nonprivate_rejected(self):
        # Each case asserts its own error code. A bare ControlError would also
        # be satisfied by an unrelated failure such as a missing core binary,
        # which silently disarmed the first case until 1.1.1.
        for content, code in (('proxies: []\nsecret: bad\n', "subscription-only-node-list-supported"),
                              ('proxies: &n []\n', "config-anchors-or-document-end-not-supported"),
                              ('proxies: []\nproxies: []\n', "config-duplicate-or-complex-key")):
            self.write(self.source, content)
            with self.assertRaisesRegex(ControlError, code):
                self.service.preview(source_file=self.source)
        self.source.chmod(0o644)
        with self.assertRaisesRegex(ControlError, "controller-path-must-be-private-owned-regular"):
            self.service.preview(source_file=self.source)
        self.assertEqual(self.config.read_text(), self.original)

    def test_drift_tampering_validation_failure_leave_active_bytes(self):
        plan = self.service.preview(source_file=self.source)
        self.write(self.config, self.original + "# concurrent edit\n")
        with self.assertRaisesRegex(ControlError, "subscription-config-changed"):
            self.service.apply(plan["id"], plan["sha256"])
        self.write(self.config, self.original)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/usr/bin/true"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(ControlError, "validation-failed"):
                self.service.apply(plan["id"], plan["sha256"])
        candidate = self.service.root / (plan["id"] + ".candidate.yaml")
        self.write(candidate, candidate.read_text() + "secret: replaced\n")
        with self.assertRaisesRegex(ControlError, "candidate-changed"):
            self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(list(self.root.glob("*.before-policy-*")), [])

    def test_download_rejects_insecure_url_before_connection(self):
        with patch.object(subscriptions.http.client, "HTTPSConnection") as connect:
            for url in ("http://example.com/private", "https://u:p@example.com/", "https://example.com/#token", "https://example.com/\nsecret"):
                with self.assertRaises(ControlError):
                    subscriptions.download(url)
            connect.assert_not_called()

    def test_post_replace_failure_restores_original_and_retains_private_backup(self):
        plan = self.service.preview(source_file=self.source)
        atomic = transaction.files.atomic_bytes
        failed = False
        def fail_after_replace(path, data, *args):
            nonlocal failed
            atomic(path, data, *args)
            if Path(path) == self.config and not failed:
                failed = True
                raise OSError("simulated directory fsync failure")
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/usr/bin/true"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)), patch.object(transaction.files, "atomic_bytes", side_effect=fail_after_replace):
            with self.assertRaisesRegex(ControlError, "original-restored"):
                self.service.apply(plan["id"], plan["sha256"])
        self.assertEqual(self.config.read_text(), self.original)
        self.assertEqual(len(list(self.root.glob("*.before-policy-*"))), 0)

    def test_crlf_bytes_are_preserved_in_backup_and_unmodified_sections(self):
        original = self.original.replace("\n", "\r\n").encode()
        self.config.write_bytes(original)
        plan = self.service.preview(source_file=self.source)
        with patch.dict(os.environ, {"MIHOMO_CORE_BIN": "/usr/bin/true"}), patch.object(transaction.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            result = self.service.apply(plan["id"], plan["sha256"])
        self.assertNotIn("backup", result)
        self.assertIn(b"mixed-port: 17890\r\nsecret: unchanged-secret\r\n", self.config.read_bytes())


class BatchTests(unittest.TestCase):
    def test_bounded_batch_and_cancellation(self):
        service = ConsoleService("/not/read/by/this/test")
        cancelled, started, release = threading.Event(), [], threading.Event()
        lock = threading.Lock()
        class Client:
            def request(self, path, **kwargs):
                if path == '/proxies':
                    return {'proxies': {str(n): {'type': 'Direct'} for n in range(20)}}
                if path == '/providers/proxies':
                    return {'providers': {}}
                return probe(path)
        def probe(path):
            with lock:
                started.append(path)
                if len(started) == 8:
                    cancelled.set(); release.set()
            release.wait(10)
            return {"delay": 1}
        with patch.object(service, "client", return_value=Client()):
            result = service.batch_latency([str(n) for n in range(20)], cancelled)
        self.assertEqual(len(started), 8)
        self.assertEqual(sum(row["state"] == "cancelled" for row in result["results"]), 12)
