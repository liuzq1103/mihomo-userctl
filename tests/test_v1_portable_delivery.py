"""Fail-closed runtime pruning and publication identity regressions."""
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.release import trim_portable_runtime as pruning
from scripts.release import publish_release as publication


class RuntimePruningTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        for alias, canonical in pruning.ALIASES.items():
            for name in (alias, canonical):
                path = self.root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixed interpreter or library')
        for name in pruning.TOOLS:
            (self.root / 'bin' / name).write_bytes(b'#!/bin/sh\npython3.12')
        for name in pruning.DIRECTORIES:
            directory = self.root / name
            directory.mkdir(parents=True, exist_ok=True)
            (directory / 'data').write_bytes(b'development-only')
        (self.root / 'lib/libpython3.so').write_bytes(b'stable ABI')

    def test_pruning_preserves_canonical_libraries_and_removes_broken_wrappers(self):
        result = pruning.trim(self.root)
        self.assertGreater(result['removed_logical_bytes'], 0)
        self.assertTrue((self.root / 'bin/python3').is_file())
        self.assertTrue((self.root / 'lib/libpython3.12.so.1.0').is_file())
        self.assertTrue((self.root / 'lib/libpython3.so').is_file())
        self.assertEqual({p.name for p in (self.root / 'bin').iterdir()}, {'python3'})

    def test_changed_alias_or_missing_layout_blocks_before_removal(self):
        (self.root / 'bin/python').write_bytes(b'unexpected')
        with self.assertRaisesRegex(ValueError, 'alias-layout'):
            pruning.trim(self.root)
        self.assertTrue((self.root / 'bin/python3.12').exists())

    def test_elf_consumer_of_removed_alias_blocks(self):
        (self.root / 'lib/extension.so').write_bytes(b'\x7fELFfixture')
        with patch.object(pruning.subprocess, 'run') as readelf:
            readelf.return_value.stdout = '(NEEDED) Shared library: [libpython3.12.so]'
            with self.assertRaisesRegex(ValueError, 'library-required'):
                pruning.trim(self.root)
        self.assertTrue((self.root / 'include').is_dir())

    def test_third_party_elf_is_included_in_bundle_scan(self):
        runtime = self.root / 'runtime'
        runtime.mkdir()
        for path in list(self.root.iterdir()):
            if path != runtime:
                shutil.move(str(path), runtime / path.name)
        consumer = self.root / 'lib/extension.so'
        consumer.parent.mkdir(parents=True)
        consumer.write_bytes(b'\x7fELFfixture')
        with patch.object(pruning.subprocess, 'run') as readelf:
            readelf.return_value.stdout = '(NEEDED) Shared library: [libpython3.12.so]'
            with self.assertRaisesRegex(ValueError, 'library-required'):
                pruning.trim(runtime, scan_root=self.root)

    def test_pruned_notice_requires_manual_review(self):
        (self.root / 'include/LICENSE').write_text('retain me')
        with self.assertRaisesRegex(ValueError, 'license-requires-review'):
            pruning.trim(self.root)


class PublicationIdentityTests(unittest.TestCase):
    def test_public_tag_must_exist(self):
        with patch.object(publication, 'command', return_value='[[]]'):
            publication.check_existing_tag('owner/repo', 'v1.4.1', 'a' * 40)
            with self.assertRaisesRegex(ValueError, 'published-tag-missing'):
                publication.check_existing_tag('owner/repo', 'v1.4.1', 'a' * 40, required=True)

    def test_draft_lookup_paginates(self):
        rows = [{'tag_name': 'v0.' + str(i)} for i in range(100)]
        with patch.object(publication, 'api', side_effect=[rows, [{'tag_name': 'v1.4.1', 'id': 9}], {'id': 9}]) as api:
            self.assertEqual(publication.find_release('owner/repo', 'v1.4.1'), {'id': 9})
            self.assertIn('page=2', api.call_args_list[1].args[1])

    def test_existing_annotated_tag_must_peel_to_validated_commit(self):
        commit = 'a' * 40
        row = [[{'ref': 'refs/tags/v1.4.1', 'object': {'type': 'tag', 'sha': 'b' * 40}}]]
        with patch.object(publication, 'command', return_value=json.dumps(row)), \
                patch.object(publication, 'api', return_value={'object': {'type': 'commit', 'sha': 'c' * 40}}):
            with self.assertRaisesRegex(ValueError, 'tag-commit-mismatch'):
                publication.check_existing_tag('owner/repo', 'v1.4.1', commit)

    def test_successful_non_main_run_is_rejected(self):
        row = {'repository': {'full_name': 'owner/repo'}, 'head_branch': 'feature',
               'head_sha': 'a' * 40, 'event': 'push', 'status': 'completed',
               'conclusion': 'success', 'path': '.github/workflows/test.yml'}
        with patch.object(publication, 'api', return_value=row):
            with self.assertRaisesRegex(ValueError, 'successful-main'):
                publication.validate_run('owner/repo', '123', 'a' * 40)

    def test_public_assets_and_notes_are_never_repaired(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'release-notes.md').write_text('reviewed notes', encoding='utf-8')
            record = {'target_commitish': 'a' * 40, 'prerelease': False,
                      'draft': False, 'body': 'different notes', 'name': 'mihomoctl v1.4.1', 'assets': []}
            with patch.object(publication, 'check_existing_tag'), \
                    patch.object(publication, 'find_release', return_value=record), \
                    patch.object(publication, 'command') as command:
                with self.assertRaisesRegex(ValueError, 'public-notes'):
                    publication.deliver('owner/repo', 'a' * 40, '1.4.1', root, {}, False)
                command.assert_not_called()
                record['body'] = 'reviewed notes'
                with self.assertRaisesRegex(ValueError, 'public-assets'):
                    publication.deliver('owner/repo', 'a' * 40, '1.4.1', root, {'missing': {}}, False)
                command.assert_not_called()

    def test_draft_resume_only_uploads_missing_assets_and_verifies_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'release-notes.md').write_text('reviewed notes', encoding='utf-8')
            record = {'target_commitish': 'a' * 40, 'prerelease': False,
                      'draft': True, 'body': 'reviewed notes', 'name': 'mihomoctl v1.4.1',
                      'assets': [{'name': 'existing', 'size': 3, 'digest': 'sha256:abc'}], 'html_url': 'draft'}
            inventory = {'existing': {'bytes': 3, 'sha256': 'abc'}, 'missing': {'bytes': 4, 'sha256': 'def'}}
            with patch.object(publication, 'check_existing_tag'), \
                    patch.object(publication, 'find_release', return_value=record), \
                    patch.object(publication, 'command') as command, \
                    patch.object(publication, 'download_verify') as download:
                result = publication.deliver('owner/repo', 'a' * 40, '1.4.1', root, inventory, False)
                self.assertFalse(result['published'])
                self.assertEqual(command.call_count, 1)
                self.assertEqual(command.call_args.args[-1], root / 'assets/missing')
                self.assertNotIn('--clobber', command.call_args.args)
                download.assert_called_once()
