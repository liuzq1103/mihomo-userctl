"""Agent help, guarded layered choices and reset authorization contracts."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from mihomoctl.command_spec import command_parser, grouped_help
from mihomoctl.controller.controller_service import select
from mihomoctl.controller.controller_types import ControlError


class SelectionClient:
    def __init__(self):
        self.rows = {'Entry': {'type': 'Selector', 'all': ['Region', 'leaf', 'DIRECT'], 'now': 'Region'},
                     'Region': {'type': 'Selector', 'all': ['leaf'], 'now': 'leaf'},
                     'leaf': {'type': 'Http'}, 'DIRECT': {'type': 'Direct'}}
        self.puts = []
        self.stick = True

    def verify(self):
        pass

    def request(self, path, method='GET', body=None, **kwargs):
        if path == '/proxies':
            return {'proxies': self.rows}
        if path == '/providers/proxies':
            return {'providers': {}}
        if method == 'PUT':
            self.puts.append((path, body))
            if self.stick:
                self.rows[path.rsplit('/', 1)[-1]]['now'] = body['name']
            return {}
        raise AssertionError(path)


class AgentContractTests(unittest.TestCase):
    def test_aggregate_leaf_requires_authorization_and_can_be_restored(self):
        client = SelectionClient()
        with self.assertRaisesRegex(ControlError, 'cross-level-selection-refused'):
            select(client, 'Entry', 'leaf')
        self.assertEqual(client.puts, [])
        select(client, 'Entry', 'leaf', allow_cross_level=True)
        select(client, 'Entry', 'Region')
        self.assertEqual(client.rows['Entry']['now'], 'Region')

    def test_direct_and_flat_groups_do_not_require_cross_level_authorization(self):
        client = SelectionClient()
        select(client, 'Entry', 'DIRECT')
        select(client, 'Region', 'leaf')

    def test_authorization_does_not_bypass_membership_or_readback(self):
        client = SelectionClient()
        with self.assertRaisesRegex(ControlError, 'node-not-in-group'):
            select(client, 'Entry', 'missing', allow_cross_level=True)
        self.assertEqual(client.puts, [])
        client.stick = False
        with self.assertRaisesRegex(ControlError, 'selection-not-confirmed'):
            select(client, 'Entry', 'leaf', allow_cross_level=True)

    def test_agent_guide_and_command_effects_are_configuration_free(self):
        with patch('pathlib.Path.read_text', side_effect=AssertionError('help read a file')):
            guide = grouped_help()
            for word in ('observe', 'restore', 'PASS=0', 'UNVERIFIED=2', '--system', '--plan-sha256'):
                self.assertIn(word, guide)
            for name in ('reset', 'select', 'subscription', 'update', 'tui', 'integration', 'core'):
                self.assertIn('Effects:', command_parser(name).format_help())

    def test_invalid_private_argument_never_leaks(self):
        from mihomoctl.cli import main
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = main(['select', 'entry', 'PRIVATE-PASSWORD', '--bad', '--json'])
        payload = json.loads(output.getvalue())
        self.assertEqual(code, 2)
        self.assertNotIn('PRIVATE-PASSWORD', json.dumps(payload))
        self.assertIn('mihomoctl select', payload['errors'][0]['detail'])
