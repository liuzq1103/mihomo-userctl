"""Real pinned scripts and explicit policy overlays retain host configuration."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import yaml
from mihomoctl.controller.controller_config import parse_config
from mihomoctl.controller.controller_policy import policy_candidate
from mihomoctl.controller.controller_subscriptions import Subscriptions
from mihomoctl.controller.controller_types import ControlError


class PolicyOverlayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        env = patch.dict(os.environ, {'HOME': str(self.root), 'XDG_DATA_HOME': str(self.root / 'data')})
        env.start(); self.addCleanup(env.stop)
        self.home = self.root / 'core'; self.home.mkdir(mode=0o700)
        self.config = self.root / 'config.yaml'
        self.original = '''# host settings
mixed-port: 25000
secret: PRIVATE-SECRET
profile: {store-selected: false, store-fake-ip: false}
proxies: [{name: 美国-01, type: direct}]
proxy-providers: {subscription: {type: file, path: providers/sub.yaml}}
proxy-groups: [{name: Proxy, type: select, proxies: [DIRECT]}]
rules: [MATCH,Proxy]
'''.replace('rules: [MATCH,Proxy]', 'rules: ["MATCH,Proxy"]')
        self.config.write_bytes(self.original.encode()); self.config.chmod(0o600)
        (self.home/'providers').mkdir(mode=0o700)
        (self.home/'providers/sub.yaml').write_text('proxies: [{name: 美国-01, type: direct}]\n')
        (self.home/'providers/sub.yaml').chmod(0o600)
        self.fixtures = Path(__file__).parent / 'fixtures/flclash'

    def test_fixed_fixture_hashes_match_recorded_commits(self):
        for record in json.loads((self.fixtures/'sources.json').read_text()):
            self.assertEqual(hashlib.sha256((self.fixtures/record['file']).read_bytes()).hexdigest(), record['sha256'])

    def test_server_yaml_overlay_keeps_nodes_provider_and_host_bytes(self):
        sub = Subscriptions(self.config, self.home)
        with patch('mihomoctl.controller.controller_subscriptions.validate_candidate'):
            plan = sub.preview(raw=(self.fixtures/'1.1.1-server-policy.yaml').read_bytes(), policy='policy')
        candidate = (sub.root/(plan['id']+'.candidate.yaml')).read_text()
        before, after = yaml.safe_load(self.original), yaml.safe_load(candidate)
        for field in ('proxies','proxy-providers','secret','mixed-port'):
            self.assertEqual(after[field], before[field])
        self.assertTrue(candidate.startswith(self.original.split('proxy-groups:')[0]))
        self.assertEqual(plan['policy'], 'policy')
        with patch('mihomoctl.lifecycle.runner.validate_config'), patch('mihomoctl.controller.controller_transaction.find_core', return_value='/usr/bin/true'):
            sub.apply(plan['id'], plan['sha256'])
        self.assertEqual(yaml.safe_load(self.config.read_text())['proxy-providers'], before['proxy-providers'])

    def test_overlay_rejects_host_fields_nodes_and_missing_provider_reference(self):
        sub = Subscriptions(self.config, self.home)
        for incoming in (b'secret: changed\n', b'proxies: []\n',
                         b'proxy-groups: [{name: Bad, type: select, use: [missing]}]\n'):
            with self.subTest(incoming=incoming), self.assertRaises(ControlError):
                sub.preview(raw=incoming, policy='policy')
        self.assertEqual(self.config.read_bytes(), self.original.encode())

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_real_scripts_metadata_stripped_without_weakening_host_boundary(self):
        for version in ('1.1.0','1.1.1'):
            script = self.root/'override.js'; script.write_bytes((self.fixtures/(version+'-override.js')).read_bytes()); script.chmod(0o600)
            for compat in (False, True):
                with self.subTest(version=version, compat=compat):
                    _, candidate, _ = policy_candidate(self.config, script=script, flclash=compat, home_dir=self.home)
                    data = yaml.safe_load(candidate)
                    self.assertNotIn('__flclashRules', data)
                    self.assertEqual(data['secret'], 'PRIVATE-SECRET')
                    self.assertEqual(data['proxy-providers'], yaml.safe_load(self.original)['proxy-providers'])
                    for field,value in yaml.safe_load(self.original).items():
                        if field not in ('proxy-groups','rules','rule-providers'):
                            self.assertEqual(data[field],value)
            for field in ('secret', 'mixed-port', 'tun'):
                script.write_text('function main(c) { c.__flclashRules={applied:true}; c['+json.dumps(field)+']="unsafe"; return c; }')
                with self.subTest(field=field), self.assertRaisesRegex(ControlError, 'may-only-change'):
                    policy_candidate(self.config, script=script, home_dir=self.home)

    def test_partial_overlay_each_field_preserves_omitted_sections_and_auto_is_full_provider(self):
        incoming=[{'rules':['MATCH,DIRECT']},
                  {'proxy-groups':[{'name':'Proxy','type':'select','proxies':['DIRECT']}]},
                  {'rule-providers':{'sites':{'type':'inline','behavior':'domain','payload':['example.test']}}}]
        for change in incoming:
            sub=Subscriptions(self.config,self.home)
            with self.subTest(field=list(change)),patch('mihomoctl.controller.controller_subscriptions.validate_candidate'):
                plan=sub.preview(raw=yaml.safe_dump(change).encode(),policy='policy')
                candidate=(sub.root/(plan['id']+'.candidate.yaml')).read_text()
                data=yaml.safe_load(candidate);before=yaml.safe_load(self.original)
                self.assertEqual(plan['fields'],list(change))
                for field,value in before.items():
                    if field not in change:self.assertEqual(data[field],value)
        sub=Subscriptions(self.config,self.home)
        with patch('mihomoctl.controller.controller_subscriptions.validate_candidate'):
            plan=sub.preview(raw=b'rules: ["MATCH,DIRECT"]\n',policy='auto')
        self.assertEqual(plan['policy'],'provider')

    def test_overlay_candidate_and_plan_tampering_are_rejected(self):
        sub=Subscriptions(self.config,self.home)
        with patch('mihomoctl.controller.controller_subscriptions.validate_candidate'):
            plan=sub.preview(raw=b'rules: ["MATCH,DIRECT"]\n',policy='policy')
        path=sub.root/(plan['id']+'.candidate.yaml')
        path.write_bytes(path.read_bytes()+b'# changed\n')
        with self.assertRaisesRegex(ControlError,'subscription-candidate-changed'):
            sub.apply(plan['id'],plan['sha256'])
        plan_path=sub.root/(plan['id']+'.json');state=json.loads(plan_path.read_text());state['candidate_sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
        plan_path.write_text(json.dumps(state));plan_path.chmod(0o600)
        with self.assertRaisesRegex(ControlError,'subscription-candidate-changed'):
            sub.apply(plan['id'],plan['sha256'])
        self.assertEqual(self.config.read_text(),self.original)


if __name__ == '__main__': unittest.main()
