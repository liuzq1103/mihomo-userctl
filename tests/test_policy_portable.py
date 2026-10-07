"""Policy preview/transaction and Node script tests, without Linux listeners."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

if sys.platform == 'win32':
    # Windows verifies pure policy/Node behavior; Linux exercises real flock/UID/PTy.
    with patch.dict(sys.modules, {'fcntl': MagicMock()}):
        from scripts import controller as c
else:
    from scripts import controller as c
import yaml


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / "config.yaml"
        self.original = '# keep listener\nmixed-port: 17890\nsecret: private\nproxy-groups:\n  - name: Proxy\n    type: url-test\n    use: [subscription]\n    url: https://example.com\n    interval: 300\nrules: ["MATCH,DIRECT"]\n'
        self.config.write_text(self.original, encoding="utf-8")
        self.private = patch.object(c, "private", side_effect=lambda p, directory=False: Path(p))
        self.private.start()
        self.addCleanup(self.private.stop)

    def script(self, source):
        path = self.root / "override.js"
        path.write_text(source, encoding="utf-8")
        return path

    def test_manual_keeps_provider_members_and_listener(self):
        original, updated, summary = c.policy_candidate(self.config, group="Proxy")
        data = yaml.safe_load(updated)
        self.assertEqual(data['proxy-groups'][0], {"name": "Proxy", "type": "select", "use": ["subscription"]})
        self.assertIn('# keep listener\nmixed-port: 17890\nsecret: private\n', updated)
        self.assertEqual(self.config.read_text(encoding="utf-8"), original)
        self.assertTrue(data['profile']['store-selected'])
        self.assertEqual(summary['state'], 'preview')

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_real_script_and_error_fallback(self):
        script = self.script('function main(c) { c.rules.unshift("DOMAIN-SUFFIX,openai.com,Proxy"); return c; }')
        _, updated, summary = c.policy_candidate(self.config, script=script)
        self.assertEqual(yaml.safe_load(updated)['rules'][0], 'DOMAIN-SUFFIX,openai.com,Proxy')
        self.assertEqual(summary['rule_count'], 2)
        script = self.script('function main(c) { console.error("private diagnostic"); return c; }')
        with self.assertRaisesRegex(c.ControlError, 'override-failed'):
            c.policy_candidate(self.config, script=script)

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_script_cannot_replace_proxy_listener_or_auth(self):
        script = self.script('function main(c) { c.secret = "changed"; return c; }')
        with self.assertRaisesRegex(c.ControlError, 'may-only-change'):
            c.policy_candidate(self.config, script=script)
        self.assertEqual(self.config.read_text(encoding='utf-8'), self.original)

    def test_validation_failure_and_concurrent_edit_do_not_commit(self):
        original, updated, _ = c.policy_candidate(self.config, group='Proxy')
        with patch.object(c.shutil, 'which', return_value='/fake/mihomo'), patch.object(c.files, 'atomic_bytes', side_effect=lambda p, b: Path(p).write_bytes(b)), patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(c.ControlError, 'validation-failed'):
                c.apply_policy(self.config, original, updated, str(self.root))
        self.assertEqual(self.config.read_text(encoding='utf-8'), original)
        self.config.write_text(original + '# concurrent\n', encoding='utf-8')
        with patch.object(c.shutil, 'which', return_value='/fake/mihomo'), patch.object(c.files, 'atomic_bytes', side_effect=lambda p, b: Path(p).write_bytes(b)), patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(c.ControlError, 'config-changed'):
                c.apply_policy(self.config, original, updated, str(self.root))
        self.assertEqual(list(self.root.glob('*.before-policy-*')), [])

    def test_success_has_backup_and_requires_restart(self):
        original, updated, _ = c.policy_candidate(self.config, group='Proxy')
        with patch.object(c.shutil, 'which', return_value='/fake/mihomo'), patch.object(c.files, 'atomic_bytes', side_effect=lambda p, b: Path(p).write_bytes(b)), patch.object(c.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            result = c.apply_policy(self.config, original, updated, str(self.root))
        self.assertEqual(Path(result['backup']).read_text(encoding='utf-8'), original)
        self.assertEqual(result['state'], 'restart-required')
        self.assertEqual(self.config.read_text(encoding='utf-8'), updated)

    def test_details_opt_in(self):
        class Client:
            def request(self, path):
                return {'connections': [{'metadata': {'host': 'chatgpt.com'}, 'rulePayload': 'chatgpt.com', 'chains': ['Hong Kong', 'Proxy']}]}
        self.assertNotIn('chatgpt.com', json.dumps(c.snapshot(Client(), 'connections')))
        self.assertEqual(c.snapshot(Client(), 'connections', True)['connections'][0]['host'], 'chatgpt.com')

    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_provider_compat_preserves_cache_and_listener(self):
        cache = self.root / 'provider.yaml'
        cache.write_text('proxies:\n  - {name: "US (BGP)+", type: ss, password: private}\n  - {name: "香港", type: ss}\n', encoding='utf-8')
        self.config.write_text(self.original + 'proxy-providers:\n  subscription:\n    path: ' + str(cache).replace('\\', '/') + '\n', encoding='utf-8')
        script = self.script('function main(c) { c["proxy-groups"].push({name: "Ai稳定选择", type: "select", proxies: c.proxies.filter(n => !n.name.includes("香港")).map(n => n.name)}); c.rules.unshift("DOMAIN-SUFFIX,openai.com,Ai稳定选择"); return c; }')
        _, updated, summary = c.policy_candidate(self.config, script=script, flclash=True)
        data = yaml.safe_load(updated)
        group = next(g for g in data['proxy-groups'] if g['name'] == 'Ai稳定选择')
        self.assertEqual(group['use'], ['subscription'])
        self.assertEqual(group['proxies'], [])
        self.assertNotIn('proxies', data)
        self.assertNotIn('password', updated)
        self.assertNotIn('private', json.dumps(summary))
        self.assertEqual(data['secret'], 'private')

    @unittest.skipUnless(shutil.which('node') and os.environ.get('MIHOMO_USERCTL_TEST_OVERRIDE'), 'Optional real user script fixture')
    def test_actual_flclash_rules_script(self):
        cache = self.root / 'subscription.yaml'
        cache.write_text('proxies:\n  - {name: "美国-BGP-01", type: ss}\n  - {name: "香港-BGP-01", type: ss}\n', encoding='utf-8')
        self.config.write_text(self.original + 'proxy-providers:\n  subscription:\n    path: ' + str(cache).replace('\\', '/') + '\n', encoding='utf-8')
        _, updated, _ = c.policy_candidate(self.config, script=os.environ['MIHOMO_USERCTL_TEST_OVERRIDE'], flclash=True)
        data = yaml.safe_load(updated)
        groups = {g['name']: g for g in data['proxy-groups']}
        self.assertEqual(groups['Ai+']['proxies'], ['Ai稳定选择', 'Ai测速备用'])
        self.assertEqual(groups['Ai稳定选择']['use'], ['subscription'])
        self.assertNotIn('香港', groups['Ai稳定选择']['filter'])
        self.assertIn('DOMAIN-SUFFIX,openai.com,Ai+', data['rules'])
        self.assertEqual(data['mixed-port'], 17890)


if __name__ == '__main__':
    unittest.main()
