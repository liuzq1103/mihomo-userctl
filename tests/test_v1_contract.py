"""Black-box CLI grammar, no-side-effect help and documentation drift regressions."""
import contextlib
import io
import json
import os
import hashlib
import re
import shlex
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tarfile
import unittest
from unittest.mock import patch

from mihomoctl import command_spec as spec
from mihomoctl.cli import main
from mihomoctl.release_identity import check, version_from_pyproject
from scripts.ci import check_docs_v1 as docs

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'linux', 'Linux runtime contract')
class PublicGrammarTests(unittest.TestCase):
    def test_update_extra_flags_reach_local_and_latest_installers(self):
        for latest in (False, True):
            target = 'mihomoctl.release.update_latest' if latest else 'mihomoctl.installation.update'
            for flags, selection in (([], None), (['--extras', 'tui', '--extras', 'other'], ['tui', 'other']),
                                     (['--no-extras'], [])):
                with patch(target, return_value={}) as update, patch('mihomoctl.installation.require_managed_update'), contextlib.redirect_stdout(io.StringIO()):
                    code = main(['update', *(['--latest'] if latest else ['/source']), *flags, '--json'])
                self.assertEqual(code, 0)
                self.assertEqual(update.call_args.kwargs['extras'], selection)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['update', '--extras', 'tui', '--no-extras', '--json']), 2)

    def test_grouped_guide_and_bare_command_contract(self):
        groups = spec.COMMAND_GROUPS
        names = [name for commands in groups.values() for name in commands]
        self.assertCountEqual(names, spec.public_commands())
        self.assertEqual(len(names), len(set(names)))
        with contextlib.redirect_stdout(io.StringIO()) as help_output:
            self.assertEqual(main(['--help']), 0)
        for title, commands in groups.items():
            self.assertIn(title + ':', help_output.getvalue())
            for name, description in commands.items():
                self.assertTrue(description.strip())
                self.assertTrue(description.isascii())
                self.assertIn(name, help_output.getvalue())
                self.assertIn(description, help_output.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as error:
            self.assertEqual(main([]), 2)
        self.assertEqual(output.getvalue(), help_output.getvalue())
        self.assertIn('usage-error: a command is required', error.getvalue())
        self.assertIn('--help', error.getvalue())
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--json']), 2)
        self.assertEqual(json.loads(output.getvalue())['errors'][0]['code'], 'usage-error')

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

    def test_reset_requires_exactly_one_of_preview_or_apply(self):
        with tempfile.TemporaryDirectory() as folder:
            environment = dict(os.environ, HOME=folder, XDG_CONFIG_HOME=folder + '/config',
                               XDG_DATA_HOME=folder + '/data', XDG_STATE_HOME=folder + '/state',
                               XDG_CACHE_HOME=folder + '/cache', XDG_RUNTIME_DIR=folder + '/runtime')
            with patch.dict(os.environ, environment, clear=True):
                # Neither action, both actions, or a value flag with no action.
                for words in (['reset'], ['reset', '--dry-run', '--apply'],
                              ['reset', '--core', '/missing/core']):
                    with self.subTest(words=words), contextlib.redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(main([*words, '--json']), 2)
                        self.assertEqual(json.loads(output.getvalue())['errors'][0]['code'], 'usage-error')
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
    def test_docs_gate_accepts_top_level_help(self):
        for command in ('mihomoctl --help', 'mihomoctl -h', 'mihomoctl help', 'mihomoctl help nodes'):
            docs.check_command(command, full=True)

    def test_installer_scope_gate_distinguishes_outer_and_quoted_operators(self):
        for operator in ('|', '&&', ';'):
            with self.subTest(operator=operator), self.assertRaisesRegex(ValueError, 'unscoped-installer'):
                docs.check_command('mihomoctl exec -- curl -fsSL https://example.invalid/install ' + operator + ' bash', full=True)
        docs.check_command("mihomoctl exec -- bash -o pipefail -c 'curl -fsSL https://example.invalid/install | bash'", full=True)

    def test_documented_fixed_core_version_must_have_a_maintained_asset_pin(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'mihomoctl').mkdir()
            (root / 'mihomoctl/mihomo-digests.json').write_text('{"pins": []}')
            with patch.object(docs, 'ROOT', root):
                with self.assertRaisesRegex(ValueError, 'documented-core-version-without-pin'):
                    docs.check_command('mihomoctl core install --version v1.19.32', full=True)
                docs.check_command('mihomoctl core install --version v1.19.32 --sha256 ' + 'a' * 64, full=True)

    def test_multiline_installer_shell_is_checked_without_hiding_following_examples(self):
        path = ROOT / 'docs/en/first-run.md'
        errors = []
        docs.check_commands(path, "```bash\nmihomoctl exec -- bash -c '\ntrue\n'\nmihomoctl core version\n```", errors)
        self.assertEqual(len(errors), 1)
        errors = []
        docs.check_commands(path, "```bash\nmihomoctl exec -- bash -c '\ntrue\n```", errors)
        self.assertTrue(any('unclosed-shell-quote' in error for error in errors))
        errors = []
        docs.check_commands(path, '```bash\nmihomoctl exec -- curl -fsSL https://example.invalid/install ' + '\\' + '\n | bash\n```', errors)
        self.assertTrue(any('unscoped-installer-pipeline' in error for error in errors))

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


@unittest.skipUnless(sys.platform == 'linux', 'Execute documented Bash recipes on Linux')
class InstallationRecipeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / 'private home'
        self.home.mkdir(mode=0o700)
        self.bin = self.home / 'bin'
        self.bin.mkdir(mode=0o700)
        from mihomoctl.environment import PROXY_KEYS
        self.env = {key: value for key, value in os.environ.items() if key not in PROXY_KEYS}
        self.env.update(HOME=str(self.home), PATH=str(self.bin) + ':' + os.environ['PATH'],
                        PYTHONPATH=str(ROOT), MIHOMOCTL_NO_UPDATE_CHECK='1')
        self.env.update({name: str(self.home / suffix) for name, suffix in (
            ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
            ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'), ('XDG_RUNTIME_DIR', 'runtime'))})

    def recipe(self, topic, marker, language='en'):
        body = (ROOT / 'docs' / language / topic).read_text(encoding='utf-8')
        return next(block for block in re.findall(r'```bash\n(.*?)```', body, re.S) if marker in block)

    def run_shell(self, program):
        return subprocess.run(['bash', '-euo', 'pipefail', '-c', program], env=self.env,
                              capture_output=True, text=True, timeout=20)

    def executable(self, name, body):
        target = self.bin / name
        target.write_text(body, encoding='utf-8')
        target.chmod(0o700)

    def proxy_fixture(self):
        # Exercise the real exec implementation/execve, with only its local
        # health precondition replaced. No listener, download or secret needed.
        self.executable('mihomoctl', '#!' + sys.executable + '''
import sys
from types import SimpleNamespace
from mihomoctl.cli import cmd_exec
from mihomoctl.envelope import Check, PASS
from mihomoctl.environment import ProxyEnvironment
assert sys.argv[1:3] == ['exec', '--']
app = SimpleNamespace(health=lambda **kw: [Check('fixture', PASS)],
                      proxy_environment=lambda profile: ProxyEnvironment('test', 'http://proxy.invalid:7890', 'socks5h://proxy.invalid:7891', 'localhost'))
cmd_exec(app, [], sys.argv[3:], False)
''')
        self.executable('curl', '#!' + sys.executable + '''
import os, sys
from pathlib import Path
from mihomoctl.environment import PROXY_KEYS
if not all(key in os.environ for key in PROXY_KEYS):
    sys.exit(73)
if 'https://assets.invalid/core' in sys.argv:
    sys.exit(0)
mode = os.environ.get('FIXTURE_DOWNLOAD', 'script')
if mode == 'fail':
    sys.exit(22)
body = ('<!DOCTYPE html><html><body>Region unavailable</body></html>' if mode == 'html'
        else '#!/usr/bin/env bash\\nset -e\\ncurl https://assets.invalid/core\\nprintf ran > "$HOME/install-ran"\\n')
if '--dump-header' in sys.argv:
    Path(sys.argv[sys.argv.index('--dump-header') + 1]).write_text('HTTP/2 200\\n')
if '--output' in sys.argv:
    Path(sys.argv[sys.argv.index('--output') + 1]).write_text(body)
else:
    print(body)
''')

    def test_entire_pipeline_inherits_proxy_but_outer_right_hand_side_does_not(self):
        self.proxy_fixture()
        bad = 'mihomoctl exec -- curl -fsSL https://claude.ai/install.sh | bash'
        result = self.run_shell(bad)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertFalse((self.home / 'install-ran').exists())
        for lang in ('en', 'zh-CN'):
            result = self.run_shell(self.recipe('first-run.md', "-o pipefail -c", lang))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((self.home / 'install-ran').exists())
            (self.home / 'install-ran').unlink()
        self.env['FIXTURE_DOWNLOAD'] = 'fail'
        result = self.run_shell(self.recipe('first-run.md', '-o pipefail -c'))
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertFalse((self.home / 'install-ran').exists())

    def test_reviewed_download_stops_on_failure_and_200_html_before_execution(self):
        self.proxy_fixture()
        for lang in ('en', 'zh-CN'):
            program = self.recipe('first-run.md', '# installer-download', lang) + '\n' + self.recipe('first-run.md', '# installer-execute-after-review', lang)
            for mode in ('fail', 'html', 'script'):
                self.env['FIXTURE_DOWNLOAD'] = mode
                with self.subTest(language=lang, response=mode):
                    result = self.run_shell(program)
                    self.assertEqual(result.returncode == 0, mode == 'script', result.stderr)
                    self.assertEqual((self.home / 'install-ran').exists(), mode == 'script')
                    for marker in self.home.glob('claude-installer.*/download-checked'):
                        self.assertEqual(mode, 'script')
                        self.assertEqual(marker.parent.stat().st_mode & 0o777, 0o700)
                    if mode == 'script':
                        (self.home / 'install-ran').unlink()
                    for directory in self.home.glob('claude-installer.*'):
                        shutil.rmtree(directory)

    def test_new_core_recipe_initializes_and_validates_without_start(self):
        self.executable('mihomoctl', '#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$HOME/core-commands"\n')
        for lang in ('en', 'zh-CN'):
            result = self.run_shell(self.recipe('setup.md', 'core install --version', lang))
            self.assertEqual(result.returncode, 0, result.stderr)
            commands = (self.home / 'core-commands').read_text().splitlines()
            self.assertEqual(commands[0], 'core install --version v1.19.32')
            self.assertEqual(commands[-1], 'config validate')
            self.assertEqual(sum(line.startswith('init --core ') for line in commands), 1)
            self.assertFalse(any(line.split()[0] in ('start', 'restart', 'service') for line in commands))
            (self.home / 'core-commands').unlink()

    def test_existing_manager_is_preserved_when_new_install_init_is_repeated(self):
        from mihomoctl.app import Application
        from mihomoctl.errors import UsageError
        with patch.dict(os.environ, self.env, clear=True):
            app = Application()
            manager = app.scope.manager_path
            manager.parent.mkdir(parents=True, mode=0o700)
            manager.write_bytes(b'existing manager and configuration must remain untouched\n')
            before = {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()}
            with patch('mihomoctl.lifecycle.runner.run_core', side_effect=AssertionError('unexpected core execution')):
                with self.assertRaisesRegex(UsageError, 'exists'):
                    app.initialize('/missing/core')
            self.assertEqual(before, {str(path): path.read_bytes() for path in self.home.rglob('*') if path.is_file()})

    def test_fixed_version_on_arm64_still_requires_corresponding_digest(self):
        from types import SimpleNamespace
        from mihomoctl import coreinstall
        from mihomoctl.errors import SupplyChainError
        scope = SimpleNamespace(require_mutation=lambda: None)
        with patch('mihomoctl.coreinstall.platform.machine', return_value='aarch64'), \
                patch('mihomoctl.coreinstall._download', side_effect=AssertionError('unexpected download')):
            with self.assertRaisesRegex(SupplyChainError, 'not pinned'):
                coreinstall.install(scope, 'v1.19.32')

    def test_both_offline_layout_recipes_resolve_private_dependencies(self):
        version = version_from_pyproject(ROOT)
        bundle = 'mihomo-userctl-' + version + '-offline-ubuntu22.04-x86_64-py310'
        payload = self.home / 'payload'
        (payload / 'release').mkdir(parents=True)
        (payload / 'wheelhouse').mkdir()
        (payload / 'wheelhouse/dependency.whl').write_bytes(b'fixture')
        source = self.home / ('mihomo-userctl-' + version)
        source.mkdir()
        (source / 'install.sh').write_text('#!/usr/bin/env bash\nset -eu\n[[ "$*" == *"$HOME/"* ]]\nprintf "%s\\n" "$*" >> "$HOME/install-commands"\n')
        archive = payload / 'release' / (source.name + '.tar.gz')
        with tarfile.open(archive, 'w:gz') as tar:
            tar.add(source, arcname=source.name)
        sums = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.relative_to(payload).as_posix() + '\n'
                       for path in payload.rglob('*') if path.is_file())
        (payload / 'SHA256SUMS').write_text(sums)
        packages = self.home / 'packages'
        packages.mkdir()
        outer = packages / (bundle + '.tar.gz')
        with tarfile.open(outer, 'w:gz') as tar:
            tar.add(payload, arcname=bundle)
        outer.with_name(outer.name + '.sha256').write_text(hashlib.sha256(outer.read_bytes()).hexdigest() + '  ' + outer.name + '\n')
        fetched = self.home / 'fetched'
        shutil.copytree(payload, fetched / 'kit')
        for lang in ('en', 'zh-CN'):
            for layout in ('fetch', 'archive'):
                program = self.recipe('offline-install.md', '# offline-' + layout + '-layout', lang)
                program = program.replace('KIT=/absolute/private/mihomoctl-kit', 'KIT=' + shlex.quote(str(fetched)))
                program = program.replace('PACKAGES=/absolute/private/packages', 'PACKAGES=' + shlex.quote(str(packages)))
                program += '\n' + self.recipe('offline-install.md', '# offline-controller-install', lang)
                with self.subTest(language=lang, layout=layout):
                    result = self.run_shell(program)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    commands = (self.home / 'install-commands').read_text().splitlines()
                    self.assertEqual(len(commands), 2)
                    self.assertTrue(commands[0].endswith('--dry-run'))
                    self.assertEqual(commands[0].removesuffix(' --dry-run'), commands[1])
                    (self.home / 'install-commands').unlink()


if __name__ == '__main__':
    unittest.main()
