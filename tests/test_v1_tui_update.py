"""Connection privacy/identity and bounded progressive probing contracts."""
import json
import threading
import unittest
from collections import Counter

from mihomoctl.controller.controller_service import ConsoleService, snapshot
from mihomoctl.controller.controller_state import Store
from mihomoctl.controller.controller_types import ControlError


class ProbeClient:
    def __init__(self, count=20):
        self.calls = Counter()
        self.nodes = {str(i): {'type': 'Direct'} for i in range(count)}
        self.lock = threading.Lock()
        self.release = threading.Event()
        self.full = threading.Event()
        self.active = self.maximum = self.probes = 0
        self.block = False

    def request(self, path, **kwargs):
        with self.lock:
            self.calls[path.split('?')[0]] += 1
        if path == '/proxies':
            return {'proxies': self.nodes}
        if path == '/providers/proxies':
            return {'providers': {}}
        with self.lock:
            self.active += 1
            self.probes += 1
            self.maximum = max(self.maximum, self.active)
            if self.active == 8:
                self.full.set()
        try:
            if self.block and not self.release.wait(10):
                raise RuntimeError('test probe was not released')
            return {'delay': 25}
        finally:
            with self.lock:
                self.active -= 1


class TuiUpdateTests(unittest.TestCase):
    def service(self, client):
        result = ConsoleService.__new__(ConsoleService)
        result.client = lambda: client
        return result

    def test_batch_reads_directory_once_and_defensive_callback_preserves_results(self):
        client = ProbeClient()
        progress = []
        def result(row):
            row['name'] = 'changed by callback'
        report = self.service(client).batch_latency([str(i) for i in range(20)],
            progress=lambda done, total: progress.append((done, total)), on_result=result)
        self.assertEqual(client.calls['/proxies'], 1)
        self.assertEqual(client.calls['/providers/proxies'], 1)
        self.assertEqual({r['name'] for r in report['results']}, set(client.nodes))
        self.assertEqual(progress, [(i, 20) for i in range(1, 21)])

    def test_eight_active_cancel_stops_unsent_and_keeps_completed(self):
        client = ProbeClient()
        client.block = True
        cancel = threading.Event()
        reports = []
        errors = []
        def batch():
            try:
                reports.append(self.service(client).batch_latency(list(client.nodes), cancel))
            except Exception as error:
                errors.append(error)
        worker = threading.Thread(target=batch)
        worker.start()
        try:
            self.assertTrue(client.full.wait(10))
            cancel.set()
        finally:
            client.release.set()
            worker.join(10)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors)
        self.assertEqual(client.maximum, 8)
        self.assertEqual(client.probes, 8)
        states = Counter(row['state'] for row in reports[0]['results'])
        self.assertEqual(states, {'success': 8, 'cancelled': 12})

    def test_observer_exceptions_never_abort_probes_or_leak_exception_text(self):
        client = ProbeClient()
        def broken(*args):
            raise RuntimeError('PRIVATE-CALLBACK-DETAIL')
        report = self.service(client).batch_latency(list(client.nodes), progress=broken, on_result=broken)
        self.assertEqual(len(report['results']), 20)
        self.assertTrue(all(r['state'] == 'success' for r in report['results']))
        self.assertEqual(report['callback_errors'], {'on_result': 20, 'progress': 20})
        self.assertNotIn('PRIVATE-CALLBACK-DETAIL', json.dumps(report))

    def test_exceptional_provider_404_reconciles_removal_and_unsupported(self):
        for removed in (False, True):
            class Client:
                failed = False
                def __init__(self):
                    self.calls = Counter()
                def request(self, path, **kwargs):
                    self.calls[path] += 1
                    if path == '/proxies':
                        return {'proxies': {}}
                    if path == '/providers/proxies':
                        return {'providers': {} if removed and self.failed else
                            {'p': {'vehicleType': 'HTTP', 'proxies': [{'name': 'x', 'type': 'Direct'}]}}}
                    self.failed = True
                    raise ControlError('node-not-in-core')
            client = Client()
            report = self.service(client).batch_latency([{'name': 'x', 'provider': 'p'}])
            self.assertEqual(report['results'][0]['error'],
                'node-disappeared' if removed else 'controller-capability-unsupported')
            # This is the approved exceptional reconciliation, not an ordinary
            # stable-batch directory reread for every node.
            self.assertEqual(client.calls['/proxies'], 2)
            self.assertEqual(client.calls['/providers/proxies'], 2)

    def test_results_arrive_before_slow_probe_finishes(self):
        client = ProbeClient(2)
        slow = threading.Event()
        release = threading.Event()
        delivered = threading.Event()
        original = client.request
        def request(path, **kwargs):
            if path.startswith('/proxies/1/delay'):
                slow.set()
                if not release.wait(10):
                    raise RuntimeError('slow test probe was not released')
            return original(path, **kwargs)
        client.request = request
        reports = []
        worker = threading.Thread(target=lambda: reports.append(self.service(client).batch_latency(
            ['0', '1'], on_result=lambda row: delivered.set())))
        worker.start()
        try:
            self.assertTrue(slow.wait(10))
            self.assertTrue(delivered.wait(10))
            self.assertTrue(worker.is_alive())
        finally:
            release.set()
            worker.join(10)
        self.assertEqual(len(reports[0]['results']), 2)

    def test_precancelled_batch_performs_no_network(self):
        client = ProbeClient()
        cancel = threading.Event()
        cancel.set()
        report = self.service(client).batch_latency(['0', '1'], cancel)
        self.assertEqual(client.calls, {})
        self.assertTrue(all(r['state'] == 'cancelled' for r in report['results']))

    def test_projection_identity_privacy_and_duplicate_fallback(self):
        item = {'metadata': {'host': 'private.example', 'destinationIP': '203.0.113.7',
                'destinationPort': '443', 'sourceIP': '127.0.0.1', 'sourcePort': '8888',
                'network': 'tcp', 'processPath': 'PRIVATE-PATH'},
                'start': '2026-10-30T10:00:00Z', 'chains': ['Proxy'], 'upload': 1, 'download': 2}
        class Client:
            def request(self, *args, **kwargs):
                return {'connections': [item, item]}
        client = Client()
        before = snapshot(client, 'connections', id_key=b'local')
        self.assertNotIn('private.example', json.dumps(before))
        self.assertNotIn('203.0.113.7', json.dumps(before))
        self.assertNotEqual(before['connections'][0]['id'], before['connections'][1]['id'])
        item.update(upload=100, download=200, chains=['Other'], rule='Changed')
        after = snapshot(client, 'connections', id_key=b'local')
        self.assertEqual([r['id'] for r in before['connections']], [r['id'] for r in after['connections']])
        display = snapshot(client, 'connections', id_key=b'local', tui=True)
        self.assertEqual(display['connections'][0]['host'], 'private.example')
        self.assertEqual(display['connections'][0]['destination_ip'], '203.0.113.7')
        self.assertNotIn('PRIVATE-PATH', json.dumps(display))
        self.assertNotIn('sourceIP', json.dumps(display))
        self.assertNotIn('rule_payload', display['connections'][0])
        self.assertTrue(all(r['identity_verified'] is False for r in display['connections']))

        first = dict(item, upload=10)
        second = dict(item, upload=20)
        class Reordered:
            entries = [first, second]
            def request(self, *args, **kwargs):
                return {'connections': self.entries}
        reordered = Reordered()
        before = snapshot(reordered, 'connections', id_key=b'local', tui=True)['connections']
        reordered.entries.reverse()
        after = snapshot(reordered, 'connections', id_key=b'local', tui=True)['connections']
        self.assertEqual({r['id'] for r in before}, {r['id'] for r in after})
        self.assertTrue(all(r['identity_verified'] is False for r in after))

    def test_invalid_connections_do_not_become_zero(self):
        class Client:
            def request(self, *args, **kwargs):
                return {'connections': value}
        for value in (False, 0, '', {}):
            with self.subTest(value=value), self.assertRaisesRegex(ControlError, 'controller-connections-invalid'):
                snapshot(Client(), 'connections')
        for value in (None, []):
            self.assertEqual(snapshot(Client(), 'connections')['connections'], [])

    def test_partial_map_survives_event_coalescing_and_rejects_old_generations(self):
        store = Store(workers=1)
        try:
            first = store.begin_probe()
            for i in range(500):
                store.probe_result(first, {'name': str(i), 'delay_ms': i + 1})
            self.assertEqual(len(store.take_probe_results(finish=True)), 500)
            store.probe_result(first, {'name': 'late'})
            second = store.begin_probe()
            store.probe_result(first, {'name': 'old'})
            store.probe_result(second, {'name': 'current'})
            self.assertEqual(store.take_probe_results(), [{'name': 'current'}])
        finally:
            store.close()


if __name__ == '__main__':
    unittest.main()
