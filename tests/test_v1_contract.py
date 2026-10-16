"""Black-box CLI grammar, no-side-effect help and documentation drift regressions."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from mihomoctl import command_spec as spec
from mihomoctl.cli import main
from mihomoctl.release_identity import check, version_from_pyproject
from scripts.ci import check_docs_v1 as docs

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux runtime contract')
class PublicGrammarTests(unittest.TestCase):
    def test_every_public_help_works_without_configuration_or_operational_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ, HOME=folder, XDG_CONFIG_HOME=folder + '/config',
                               XDG_DATA_HOME=folder + '/data', XDG_STATE_HOME=folder + '/state',
                               XDG_CACHE_HOME=folder + '/cache', XDG_RUNTIME_DIR=folder + '/runtime')
            commands = []
            for name in (*spec.NATIVE, *spec.BRIDGED):
                commands.append([name])
                definition = spec.NATIVE.get(name, spec.BRIDGED.get(name))
                if isinstance(definition, dict):
                    commands.extend([name, action] for action in definition)
            commands += [['health', 'check']]
            with patch.dict(os.environ, environment, clear=True), \
                    patch('mihomoctl.app.Application.load_manager', side_effect=AssertionError('help read manager')), \
                    patch('subprocess.run', side_effect=AssertionError('help spawned process')), \
                    patch('socket.socket', side_effect=AssertionError('help connected')):
                for words in commands:
                    with self.subTest(command=words), contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(main([*words, '--help', '--json']), 0)
                        result = json.loads(output.getvalue())
                        self.assertEqual(result['overall'], 'PASS')
                        self.assertIn('usage: mihomoctl', result['data']['help'])
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_real_process_help_and_retired_rejections(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ, HOME=folder, XDG_CONFIG_HOME=folder + '/config')
            for words, expected in ((['subscription', 'apply', '--help'], 0),
                                    (['rules', 'check', '--help'], 0),
                                    (['core', 'version'], 2), (['core', 'adopt', '--invented'], 2),
                                    *[([name, '--help'], 2) for name in spec.RETIRED]):
                with self.subTest(words=words):
                    result = subprocess.run([sys.executable, '-m', 'mihomoctl', *words],
                                            cwd=ROOT, env=environment, capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, expected, result.stderr)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_direct_preserves_child_argv_and_clears_all_eight_proxy_keys(self):
        from mihomoctl.environment import PROXY_KEYS
        with tempfile.TemporaryDirectory() as folder:
            child = Path(folder) / 'codex'
            child.write_text('#!' + sys.executable + '\nimport os,sys,json\nprint(json.dumps([sys.argv[1:], {k:v for k,v in os.environ.items() if k.lower() in ("http_proxy","https_proxy","all_proxy","no_proxy")}]))\n')
            child.chmod(0o700)
            arguments = ['--help', '--json', '--system', '检查当前项目', '--', '--binding', 'x y']
            environment = dict(os.environ, **{key: 'inherited-private-value' for key in PROXY_KEYS})
            result = subprocess.run([sys.executable, '-m', 'mihomoctl', 'direct', '--', str(child), *arguments],
                                    cwd=ROOT, env=environment, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [arguments, {}])


class DriftGateTests(unittest.TestCase):
    def test_docs_gate_rejects_real_unknown_actions_options_and_retired_examples(self):
        for command in ('mihomoctl core version', 'mihomoctl codex start',
                        'mihomoctl rules check --invented', 'mihomoctl subscription apply X',
                        'mihomoctl core install --version v1.19.32 --allow-unpinned'):
            with self.subTest(command=command), self.assertRaises(Exception):
                docs.check_command(command, full=True)
        for command in ('mihomoctl rules check --json', 'mihomoctl core adopt --path /trusted/core',
                        'mihomoctl subscription apply X --sha256 ' + 'a' * 64,
                        'mihomoctl exec -- codex --help --invented-child-option'):
            docs.check_command(command, full=True)

    def test_documented_anchors_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'guide.md'
            path.write_text('# Correct heading\n')
            with patch.object(docs, 'ROOT', root):
                errors = []
                docs.check_links(path, '[ok](#correct-heading) [bad](#removed-heading)', errors)
                self.assertEqual(len(errors), 1)
                self.assertIn('broken-anchor', errors[0])

    def test_all_release_stamps_are_checked_against_pyproject(self):
        # pyproject.toml is the release version authority, so derive the stamp
        # from it instead of repeating a literal that every bump must edit.
        version = version_from_pyproject(ROOT)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = ('pyproject.toml', 'mihomoctl/__init__.py', 'release-manifest.json',
                     'CHANGELOG.md', 'README.md', 'README.en.md', 'INSTALL.md')
            for name in names:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, path)
            self.assertEqual(check(root), version)
            for name in names:
                path = root / name
                original = path.read_text()
                path.write_text(original.replace(version, '1.0.2'))
                with self.subTest(name=name), self.assertRaises(ValueError):
                    check(root)
                path.write_text(original)


if __name__ == '__main__':
    unittest.main()
