"""Provider target identity, routing, refresh races and safe DTOs."""
import json
import unittest
from urllib.parse import quote
from unittest.mock import patch

from mihomoctl.controller import controller_service as service
from mihomoctl.controller.controller_types import ControlError


class Client:
    def verify(self): pass
    def __init__(self):
        self.calls = []
        self.global_rows = {'DIRECT': {'type': 'Direct'}, 'Ai+': {'type': 'Selector', 'all': ['美国 / +?%'], 'now': '美国 / +?%'}}
        self.providers = {'订阅 /?%': {'vehicleType': 'HTTP', 'url': 'PRIVATE-URL', 'proxies': [
            {'name': '美国 / +?%', 'type': 'Shadowsocks', 'password': 'PRIVATE-PASSWORD'}]}}
        self.failure = None
        self.remove = False

    def request(self, path, **kwargs):
        self.calls.append(path)
        if path == '/proxies': return {'proxies': self.global_rows}
        if path == '/providers/proxies': return {'providers': self.providers}
        if self.failure:
            if self.remove: self.providers = {}
            raise ControlError(self.failure, 1)
        return {'delay': 37}


class ProviderNodeTests(unittest.TestCase):
    def setUp(self):
        self.client = Client()
        self.service = service.ConsoleService.__new__(service.ConsoleService)
        self.service.client = lambda: self.client

    def test_provider_only_node_visible_chain_complete_and_safe(self):
        rows = service.proxies(self.client)
        self.assertEqual(rows['Ai+']['chain_state'], 'complete')
        self.assertEqual(rows['Ai+']['missing_member_count'], 0)
        nodes = service.snapshot(self.client, 'nodes')['nodes']
        self.assertEqual(len(nodes), 2)
        text = json.dumps([nodes, rows])
        self.assertNotIn('PRIVATE-', text)
        self.assertEqual(rows['Ai+']['member_targets'], [{'name': '美国 / +?%', 'provider': '订阅 /?%'}])

    def test_single_and_batch_use_same_provider_route_and_encoding(self):
        one = self.service.latency('美国 / +?%')
        batch = self.service.batch_latency([{'name': '美国 / +?%', 'provider': '订阅 /?%'}])
        self.assertEqual(one['delay_ms'], batch['results'][0]['delay_ms'])
        paths = [p for p in self.client.calls if '?' in p and p != '/providers/proxies']
        expected = '/providers/proxies/' + quote('订阅 /?%', safe='') + '/' + quote('美国 / +?%', safe='') + '/healthcheck?'
        self.assertTrue(all(p.startswith(expected) for p in paths))

    def test_same_names_are_qualified_and_batch_not_deduplicated_by_name(self):
        self.client.providers['other'] = self.client.providers['订阅 /?%']
        with self.assertRaisesRegex(ControlError, 'ambiguous-node'):
            self.service.latency('美国 / +?%')
        targets = [{'name': '美国 / +?%', 'provider': p} for p in self.client.providers]
        result = self.service.batch_latency(targets + targets)
        self.assertEqual(result['target_count'], 2)
        self.assertTrue(all(row['state'] == 'success' for row in result['results']))
        self.assertEqual(service.proxies(self.client)['Ai+']['chain_state'], 'ambiguous-reference')

    def test_global_and_provider_same_name_have_distinct_identity(self):
        self.client.global_rows['美国 / +?%'] = {'type': 'Shadowsocks'}
        with self.assertRaisesRegex(ControlError, 'ambiguous-node'):
            self.service.latency('美国 / +?%')
        self.service.latency({'name': '美国 / +?%', 'provider': None})
        self.assertTrue(self.client.calls[-1].startswith('/proxies/'))
        self.service.latency('美国 / +?%', provider='订阅 /?%')
        self.assertTrue(self.client.calls[-1].startswith('/providers/proxies/'))
        rows=service.proxies(self.client)
        self.assertEqual(rows['Ai+']['chain_state'],'ambiguous-reference')
        self.assertEqual({t['provider'] for t in rows['Ai+']['member_targets']},{None,'订阅 /?%'})
        with self.assertRaisesRegex(ControlError,'ambiguous-node'):
            service.select(self.client,'Ai+','美国 / +?%')

    def test_batch_extra_fields_never_reach_failure_or_cancellation_dtos(self):
        import threading
        stopped=threading.Event();stopped.set()
        for event in (None,stopped):
            with self.assertRaisesRegex(ControlError,'invalid-node-target') as caught:
                self.service.batch_latency([{'name':'x','provider':'p','password':'PRIVATE-PASSWORD'}],event)
            self.assertNotIn('PRIVATE-PASSWORD',str(caught.exception))

    def test_equivalent_global_batch_targets_deduplicate_without_hiding_ambiguity(self):
        targets=['DIRECT',{'name':'DIRECT','provider':None}]
        for ordered in (targets,list(reversed(targets))):
            result=self.service.batch_latency(ordered)
            self.assertEqual(result['target_count'],1)
            self.assertEqual(result['results'][0]['state'],'success')
        self.client.providers['other']={'vehicleType':'HTTP','proxies':[{'name':'DIRECT','type':'Direct'}]}
        result=self.service.batch_latency(['DIRECT',{'name':'DIRECT','provider':None}])
        self.assertEqual(result['target_count'],2)
        self.assertEqual({row.get('error') for row in result['results']},{'ambiguous-node',None})

    def test_unique_provider_query_and_explicit_target_deduplicate_in_either_order(self):
        import threading
        self.client.providers={'p':{'vehicleType':'HTTP','proxies':[{'name':'only','type':'Direct','password':'PRIVATE-PASSWORD'}]}}
        targets=['only',{'name':'only','provider':'p'}]
        for ordered in (targets,list(reversed(targets))):
            result=self.service.batch_latency(ordered)
            self.assertEqual(result['target_count'],1)
            self.assertEqual(result['results'][0]['provider'],'p')
            self.assertEqual(result['results'][0]['state'],'success')
            cancelled=threading.Event();cancelled.set()
            result=self.service.batch_latency(ordered,cancelled)
            self.assertEqual(result['target_count'],1)
            self.assertEqual(result['results'][0],{'name':'only','provider':'p','state':'cancelled'})
            self.assertNotIn('PRIVATE-',json.dumps(result))

    def test_cli_provider_option_reaches_same_resolver(self):
        import contextlib,io,json
        from mihomoctl.controller import controller
        with patch.object(controller,'read_config',return_value=('',{},None)), \
                patch.object(controller,'endpoint',return_value=(1234,'private')), \
                patch.object(controller,'Client',return_value=self.client), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            controller.main(['latency','美国 / +?%','--provider','订阅 /?%','--json'])
        self.assertEqual(json.loads(output.getvalue())['provider'],'订阅 /?%')
        self.assertTrue(self.client.calls[-1].startswith('/providers/proxies/'))

    def test_cli_can_explicitly_address_global_collision(self):
        import contextlib,io
        from mihomoctl.controller import controller
        name=next(iter(self.client.providers.values()))['proxies'][0]['name']
        self.client.global_rows[name]={'type':'Shadowsocks'}
        with patch.object(controller,'read_config',return_value=('',{},None)), \
                patch.object(controller,'endpoint',return_value=(1234,'private')), \
                patch.object(controller,'Client',return_value=self.client),contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(ControlError,'ambiguous-node'):controller.main(['latency',name,'--json'])
            controller.main(['latency',name,'--global','--json'])
        self.assertTrue(self.client.calls[-1].startswith('/proxies/'))

    def test_http_status_classification_at_client_boundary(self):
        from mihomoctl.controller.controller_api import Client as HTTPClient
        from unittest.mock import Mock
        import threading
        client=HTTPClient(1234,'PRIVATE-CONTROLLER-KEY')
        for status,expected in ((404,'controller-capability-unsupported'),(405,'controller-capability-unsupported'),
                                (501,'controller-capability-unsupported'),(503,'node-unreachable'),(504,'delay-timeout')):
            response=Mock(status=status);connection=Mock();connection.getresponse.return_value=response
            with self.subTest(status=status),patch('http.client.HTTPConnection',return_value=connection):
                with self.assertRaisesRegex(ControlError,expected):
                    client.request('/test',optional=True,status_codes={503:'node-unreachable',504:'delay-timeout'})
        response=Mock(status=501);connection.getresponse.return_value=response
        with patch.object(client,'verify'),patch('http.client.HTTPConnection',return_value=connection):
            with self.assertRaisesRegex(ControlError,'controller-capability-unsupported'):
                list(client.lines('/logs',threading.Event()))

    def test_refresh_removal_unsupported_timeout_and_unknown_are_distinct(self):
        for code, remove, expected in [('node-not-in-core', True, 'node-disappeared'),
                                       ('node-not-in-core', False, 'controller-capability-unsupported'),
                                       ('node-unreachable', False, 'node-unreachable'),
                                       ('delay-timeout', False, 'delay-timeout')]:
            self.setUp()
            self.client.failure, self.client.remove = code, remove
            with self.subTest(code=code, remove=remove), self.assertRaisesRegex(ControlError, expected):
                self.service.latency('美国 / +?%')
        self.setUp()
        with self.assertRaisesRegex(ControlError, 'unknown-node'):
            self.service.latency('does-not-exist')
        self.assertTrue(all('/healthcheck?' not in p for p in self.client.calls))

    def test_implicit_compatible_provider_does_not_duplicate_builtin_nodes(self):
        self.client.providers['default'] = {'vehicleType': 'Compatible', 'proxies': [{'name': 'DIRECT', 'type': 'Direct'}]}
        self.assertEqual(self.service.latency('DIRECT')['provider'], None)

    def test_unknown_input_never_echoes_possible_credentials(self):
        with self.assertRaisesRegex(ControlError,'unknown-node') as caught:
            self.service.latency('https://example.test/PRIVATE-PASSWORD')
        self.assertNotIn('PRIVATE-PASSWORD',str(caught.exception))

    def test_sensitive_unknown_batch_and_cancellation_project_names_and_identity_safely(self):
        import threading
        from mihomoctl.controller.controller_types import node_identity
        name='https://example.test/PRIVATE-PASSWORD'
        for target in (name,{'name':name,'provider':None},{'name':'missing','provider':'https://PRIVATE-PROVIDER/'}):
            for cancel in (False,True):
                event=threading.Event()
                if cancel:event.set()
                result=self.service.batch_latency([target],event)
                self.assertNotIn('PRIVATE-',json.dumps(result))
                row=result['results'][0]
                self.assertEqual(row['state'],'cancelled' if cancel else 'failed')
                expected=node_identity(target['name'],target.get('provider')) if isinstance(target,dict) else node_identity(target)
                self.assertEqual(row['target_id'],expected)


if __name__ == '__main__': unittest.main()
