"""Config editing must preserve both YAML values and unrelated source bytes."""
import unittest

import yaml

from mihomoctl.controller.controller_config import parse_config, patch_config


class YamlPatchTests(unittest.TestCase):
    def patch(self, original, changes):
        tree = parse_config(original)[2]
        result = patch_config(original, tree, changes)
        expected = yaml.safe_load(original)
        expected.update(changes)
        self.assertEqual(yaml.safe_load(result), expected)
        return result

    def test_containers_are_block_yaml_and_other_bytes_survive(self):
        original = '# header\r\nsecret: "UNCHANGED" # auth\r\nproxies: [] # nodes\r\n# next heading\r\nrules: []\r\n# tail\r\n\r\n'
        result = self.patch(original, {
            'proxies': [{'name': '美国 / 🇺🇸', 'password': 'true', 'port': 1234}],
            'proxy-groups': [{'name': 'Ai+', 'type': 'select', 'proxies': ['美国 / 🇺🇸']}],
            'rules': ['MATCH,Ai+'],
            'rule-providers': {'规则': {'type': 'http', 'url': 'https://example.test/' + 'x' * 200}},
        })
        self.assertTrue(result.startswith('# header\r\nsecret: "UNCHANGED" # auth\r\n'))
        for comment in ('# nodes', '# next heading', '# tail'):
            self.assertIn(comment, result)
        self.assertIn('proxies: # nodes\r\n  - name:', result)
        self.assertEqual(result.count('# nodes'), 1)
        self.assertNotIn('\n', result.replace('\r\n', ''))
        self.assertNotIn('proxies: [{', result)

    def test_unchanged_children_keep_their_format_and_inline_comments(self):
        original = 'proxy-groups:\n  - name: "Ai+" # label\n    type: url-test # strategy\n    proxies: ["a", "b"] # untouched\n# rules heading\nrules: ["MATCH,DIRECT"]\n'
        result = self.patch(original, {'proxy-groups': [{'name': 'Ai+', 'type': 'select', 'proxies': ['a', 'b']}]})
        self.assertIn('  - name: "Ai+" # label\n', result)
        self.assertIn('    proxies: ["a", "b"] # untouched\n', result)
        self.assertIn('type: select # strategy', result)
        self.assertTrue(result.endswith('# rules heading\nrules: ["MATCH,DIRECT"]\n'))

    def test_structural_changes_preserve_surviving_mapping_and_sequence_entries(self):
        source = 'profile:\n  keep: "unchanged" # attached\n  old: yes\nrules:\n  - "MATCH,DIRECT" # surviving\n'
        result = self.patch(source, {'profile': {'keep': 'unchanged', 'new': 'off'},
                                     'rules': ['DOMAIN,example.test,REJECT', 'MATCH,DIRECT']})
        self.assertIn('  keep: "unchanged" # attached\n', result)
        self.assertIn('  - "MATCH,DIRECT" # surviving\n', result)
        deleted = self.patch(result, {'rules': ['MATCH,DIRECT']})
        self.assertIn('  - "MATCH,DIRECT" # surviving\n', deleted)

    def test_structural_and_nested_leaf_changes_keep_source_and_blank_line_count(self):
        source = 'profile:\n  nested:\n    a: "keep" # attached\n\n    b: old\n'
        result = self.patch(source, {'profile': {'nested': {'a':'keep','b':'new'}, 'added':'off'}})
        self.assertIn('    a: "keep" # attached\n\n    b: new\n', result)
        self.assertEqual(result.count('\n\n'), 1)

    def test_explicit_collection_tags_and_nested_eof_scalars(self):
        for tag in ('!!map', '!s!map'):
            source = '%TAG !s! tag:yaml.org,2002:\n---\nprofile: '+tag+'\n  keep: "old" # keep\n'
            self.assertIn('  keep: "old" # keep\n', self.patch(source, {'profile': {'keep':'old','new':'off'}}))
        source = 'rules: !!seq\n  - "a" # keep\n'
        self.assertIn('  - "a" # keep\n', self.patch(source, {'rules':['a','b']}))
        for style in ('|','>'):
            source = 'profile:\n  keep: '+style+'\n    a'
            result = self.patch(source, {'profile': {'keep':'a','new':'off'}})
            self.assertTrue(result.endswith('keep: '+style+'\n    a'))
            self.patch('rules:\n  - '+style+'\n    a', {'rules':['a','b']})

    def test_explicit_scalar_keys_and_edited_nested_eof_sequence_scalar(self):
        source='profile:\n  ? "keep"\n  : old\n'
        result=self.patch(source,{'profile':{'keep':'old','new':'off'}})
        self.assertIn('? "keep"\n  : old',result)
        for label in ('a','changed'):
            source='items:\n  - name: x\n    label: |\n      a'
            result=self.patch(source,{'items':[{'name':'longer-name','label':label},'b']})
            self.assertEqual(yaml.safe_load(result)['items'][0]['label'],label)
        source='%TAG !s! tag:yaml.org,2002:\n---\nitems:\n  - !s!map\n    name: x\n    label: |\n      a'
        self.patch(source,{'items':[{'name':'longer-name','label':'a'},'b']})

    def test_indentless_sequence_can_become_empty_scalar_or_mapping(self):
        source='profile:\n- a\n- b\nrules: []\n'
        for value in ([],{},'off',None,{'value':'new'}):
            self.patch(source,{'profile':value})
        source='? profile\n:\n- a\n- b\nrules: []\n'
        for value in ([],{},'off',None,{'value':'new'}):self.patch(source,{'profile':value})
        self.patch('profile: !!seq\n  - a\nrules: []\n',{'profile':{'value':'new'}})
        self.patch('profile: !!map\n  a: old\nrules: []\n',{'profile':['new']})

    def test_sequence_indicator_lines_survive_separated_child_nodes(self):
        source='items:\n  - # first\n    name: "x" # keep\n  - # second\n    name: "y"\nrules: []\n'
        result=self.patch(source,{'items':[{'name':'x'},{'name':'y'},{'name':'z'}]})
        self.assertIn('  - # first\n    name: "x" # keep\n',result)
        self.assertIn('  - # second\n    name: "y"\n',result)
        result=self.patch(source,{'items':[{'name':'y'}]})
        self.assertIn('  - # second\n    name: "y"\n',result)
        self.patch('items:\n  -\n    scalar\n  -\n    other\n',{'items':['scalar','other','new']})

    def test_root_explicit_key_eof_scalar_and_explicit_scalar_type_changes(self):
        for newline in ('\n','\r\n'):
            for style in ('|','>','|-','>+'):
                source=('? profile\n: '+style+'\n  a').replace('\n',newline)
                result=self.patch(source,{'rules':[]})
                self.assertTrue(result.endswith(source))
        for tag in ('!!str','!s!str'):
            source='%TAG !s! tag:yaml.org,2002:\n---\nprofile:\n  value: '+tag+' old\n'
            self.patch(source,{'profile':{'value':1}})
        self.patch('profile:\n  value: !!int 1\n',{'profile':{'value':'1'}})

    def test_replaced_container_retains_comments_without_mistaking_string_hashes(self):
        original = 'rules:\n  # rule heading\n  - "MATCH,DIRECT" # old rule\n  # footer\nsecret: "x#not-comment"\n'
        result = self.patch(original, {'rules': ['DOMAIN,example.test,DIRECT', 'MATCH,REJECT']})
        for comment in ('# rule heading', '# old rule', '# footer'):
            self.assertIn(comment, result)
        self.assertEqual(result.count('#not-comment'), 1)
        self.assertTrue(result.endswith('secret: "x#not-comment"\n'))

    def test_string_types_regex_urls_and_unicode(self):
        values = ['true', 'off', 'null', '0123', '2026-10-27', '1e3', '', 'a: b',
                  '# literal', '中文🇭🇰', r'(?i)^(?:us|u\.s\.a)[\\/].{200}$',
                  'https://example.test/a?x=1&y=' + 'x' * 500 + '#fragment']
        result = self.patch('proxies: []\n', {'proxies': [{'name': s, 'password': s} for s in values]})
        self.assertEqual([n['name'] for n in yaml.safe_load(result)['proxies']], values)
        self.assertIn(values[-1], result)
        self.assertIn(values[-2], yaml.safe_load(result)['proxies'][-2]['name'])

    def test_multiline_strings_preserve_significant_trailing_newlines(self):
        for value in ('a\n', 'a\n\n', '\n\n', 'a\nb\n\n', 'a\n# content\n'):
            with self.subTest(value=repr(value)):
                result = self.patch('profile:\n  value: old\n', {'profile': {'value': value}})
                self.assertEqual(yaml.safe_load(result)['profile']['value'], value)

    def test_empty_containers_noop_and_missing_final_newline(self):
        text = '# header\nproxies: []\n\n# footer'
        self.assertEqual(self.patch(text, {}), text)
        self.assertEqual(self.patch(text, {'proxies': []}), text)
        result = self.patch(text, {'rules': []})
        self.assertIn('# footer\nrules: []\n', result)

    def test_nested_type_change_is_not_elided(self):
        result = self.patch('profile:\n  value: true\n', {'profile': {'value': 1}})
        self.assertIs(type(yaml.safe_load(result)['profile']['value']), int)

    def test_block_scalar_and_nested_section_replacement(self):
        text = 'profile:\n  label: |\n    a#b\n    c\n  old: yes\n# boundary\nrules: []\n'
        result = self.patch(text, {'profile': {'label': 'changed', 'new': 'off'}})
        self.assertIn('# boundary\nrules: []\n', result)

    def test_existing_block_scalar_edit_preserves_next_child_boundary(self):
        text = 'profile:\n  label: |\n    a\n  old: yes\n'
        result = self.patch(text, {'profile': {'label': 'changed', 'old': True}})
        self.assertIn('label: changed\n  old: yes\n', result)

    def test_resolved_key_collisions_are_rejected(self):
        for text in ('profile:\n  true: first\n  True: second\n',
                     'profile:\n  1: first\n  true: second\n'):
            with self.subTest(text=text), self.assertRaisesRegex(Exception, 'config-duplicate-or-complex-key'):
                parse_config(text)

    def test_container_ending_in_block_scalar_preserves_boundary(self):
        for newline in ('\n', '\r\n'):
            for style in ('|', '>'):
                for body in (f'profile:\n  label: {style}\n    a\n', f'profile:\n  - {style}\n    a\n'):
                    text = (body + '# next heading\nrules: []\n').replace('\n', newline)
                    result = self.patch(text, {'profile': {'new': 'off'}})
                    self.assertTrue(result.endswith(newline + '# next heading' + newline + 'rules: []' + newline))

    def test_adding_missing_key_does_not_change_eof_block_scalar(self):
        for style in ('|', '>', '|-', '|+'):
            for newline in ('\n', '\r\n'):
                text = ('profile: '+style+'\n  a').replace('\n', newline)
                result = self.patch(text, {'rules': []})
                self.assertEqual(yaml.safe_load(result)['profile'], yaml.safe_load(text)['profile'])
                self.assertTrue(result.endswith(text))

    def test_block_scalar_trailing_blank_lines_survive(self):
        for newline in ('\n', '\r\n'):
            text = 'profile:\n  label: |\n    a\n\n  \n# next heading\nrules: []\n'.replace('\n', newline)
            result = self.patch(text, {'profile': {'new': 'off'}})
            self.assertIn(("\n\n  \n# next heading\nrules: []\n").replace('\n', newline), result)

    def test_nan_untouched_noop_and_unrelated_change(self):
        text='profile:\n  value: .nan\nrules: []\n'
        self.assertEqual(patch_config(text,parse_config(text)[2],{}),text)
        result=patch_config(text,parse_config(text)[2],{'rules':['MATCH,DIRECT']})
        self.assertTrue(result.startswith('profile:\n  value: .nan\n'))

    def test_replaced_container_blank_separator_and_cr_only(self):
        for newline in ('\n','\r\n','\r'):
            text='profile:\n  first: old\n\n  second: old\nrules: []\n'.replace('\n',newline)
            result=self.patch(text,{'profile':{'new':'off'}})
            self.assertIn(newline+ '  '+newline,result)
            if newline=='\r': self.assertNotIn('\n',result)

    def test_string_key_tag_directive_keeps_document_context(self):
        text='%TAG !s! tag:yaml.org,2002:\n---\nprofile:\n  !s!str value: old\n'
        result=self.patch(text,{'profile':{'value':'new'}})
        self.assertIn('!s!str value: new',result)
        self.assertTrue(result.startswith('%TAG !s! tag:yaml.org,2002:\n---\n'))


if __name__ == '__main__':
    unittest.main()
