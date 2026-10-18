#!/usr/bin/env python3
"""Read-only checks for current documentation, using the actual CLI grammar."""
import argparse
import ast
import contextlib
import io
import json
from pathlib import Path
import re
import shlex
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mihomoctl import command_spec as spec
from mihomoctl.errors import UsageError
from mihomoctl.release_identity import check as check_version

BILINGUAL_TOPICS = ('README.md', 'setup.md', 'subscriptions.md', 'rules.md', 'first-run.md',
                    'security.md', 'update.md', 'offline-install.md', 'agent-install-prompt.md',
                    'agent-local-install-prompt.md', 'codex-install-prompt.md', 'troubleshooting.md',
                    'operations/integrations.md', 'operations/release.md',
                    'reference/cli.md', 'reference/configuration.md')


def documents():
    yield from (ROOT / name for name in ('README.md', 'README.en.md', 'README.zh-CN.md',
                                        'INSTALL.md', 'CHANGELOG.md', 'SECURITY.md'))
    yield from (p for p in sorted((ROOT / 'docs').rglob('*.md')) if 'archive' not in p.relative_to(ROOT / 'docs').parts)


def relative(path):
    return path.relative_to(ROOT).as_posix()


def headings(body):
    result, counts = set(), {}
    for title in re.findall(r'^#{1,6}\s+(.+)', body, re.M):
        title = re.sub(r'[^\w\- ]', '', title.strip().lower(), flags=re.UNICODE).replace(' ', '-')
        count = counts.get(title, 0)
        counts[title] = count + 1
        result.add(title + ('-' + str(count) if count else ''))
    return result


def check_links(path, text, errors):
    for raw in re.findall(r'\]\(([^)]+)\)', text):
        raw = raw.strip().strip('<>')
        if re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', raw):
            continue
        address, _, anchor = raw.partition('#')
        target = path.parent / unquote(address) if address else path
        if not target.exists():
            errors.append('broken-link: ' + relative(path) + ' -> ' + raw)
        elif anchor and target.suffix == '.md' and unquote(anchor) not in headings(target.read_text(encoding='utf-8-sig')):
            errors.append('broken-anchor: ' + relative(path) + ' -> ' + raw)


def command_tokens(command):
    tokens = shlex.split(command)
    if tokens and tokens[0] == 'mihomoctl':
        tokens.pop(0)
    while tokens and tokens[0] in ('--user', '--system', '--json'):
        tokens.pop(0)
    return tokens


def check_command(command, full=False):
    # Keep quoted shell programs opaque, but detect an outer installer pipeline.
    # exec only replaces one process; it cannot scope the caller's pipe/sequence.
    shell = shlex.shlex(command, posix=True, punctuation_chars='|&;')
    shell.whitespace_split = True
    words = list(shell)
    if '--' in words:
        head, child = words[:words.index('--')], words[words.index('--') + 1:]
        if 'exec' in head and child and Path(child[0]).name in ('curl', 'wget'):
            for index, word in enumerate(child[:-1]):
                if word in ('|', '|&', '&&', ';') and Path(child[index + 1]).name in ('bash', 'sh', 'zsh'):
                    raise ValueError('unscoped-installer-pipeline')
    values = command_tokens(command)
    if not values or '[' in command or 'COMMAND' in values or any('/' in v for v in values[:1]):
        return
    name = values.pop(0)
    if name == 'core' and values[:1] == ['install'] and '--version' in values and '--sha256' not in values:
        index = values.index('--version') + 1
        version = values[index] if index < len(values) else ''
        if re.fullmatch(r'v\d+\.\d+\.\d+', version):
            pins = json.loads((ROOT / 'mihomoctl/mihomo-digests.json').read_text(encoding='utf-8'))['pins']
            asset = 'mihomo-linux-amd64-compatible-' + version + '.gz'
            if not any(pin['version'] == version and pin['asset'] == asset for pin in pins):
                raise ValueError('documented-core-version-without-pin')
    if name in spec.RETIRED:
        raise ValueError('retired-command-in-example')
    parser = spec.command_parser(name)
    if name == 'health' and values[:1] == ['check']:
        values.pop(0)
    if '--' in values:
        values = values[:values.index('--')]
    values = [v for v in values if v != '--json']
    if full:
        with contextlib.redirect_stdout(io.StringIO()):
            try:
                spec.validate(name, values)
            except SystemExit as error:
                if error.code:
                    raise ValueError('invalid-help-example') from None
        return
    # Inline references may omit required values, but named flags/actions must exist.
    action = next((a for a in parser._actions if isinstance(a, argparse._SubParsersAction)), None)
    if action and values and not values[0].startswith('-'):
        if values[0] not in action.choices:
            raise ValueError('unknown-subcommand')
        parser = action.choices[values.pop(0)]
    known = {flag for a in parser._actions for flag in a.option_strings}
    if any(v.startswith('--') and v.split('=', 1)[0] not in known for v in values):
        raise ValueError('unknown-command-option')


def check_commands(path, text, errors):
    fence = None
    pending = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r'^\s*(`{3,}|~{3,})(.*)', line)
        if marker:
            if pending:
                errors.append('invalid-cli-example: %s:%d: unclosed-shell-quote' % (relative(path), pending[0]))
                pending = None
            if fence is None:
                fence = (marker[1][0], marker[2].strip())
            elif marker[1][0] == fence[0]:
                fence = None
            continue
        examples = []
        if pending:
            examples.append((pending[1] + '\n' + line, True))
        elif fence and fence[1] in ('bash', 'sh', 'shell') and line.strip().startswith('mihomoctl '):
            examples.append((line.strip(), True))
        elif fence is None:
            examples.extend((item, False) for item in re.findall(r'`(mihomoctl [^`]+)`', line))
        for command, full in examples:
            try:
                check_command(command, full)
                pending = None
            except (UsageError, ValueError) as error:
                if full and str(error) in ('No closing quotation', 'No escaped character'):
                    pending = (pending[0] if pending else number, command)
                else:
                    errors.append('invalid-cli-example: %s:%d: %s' % (relative(path), number, str(error)))
                    pending = None
    if fence:
        errors.append('unclosed-code-fence: ' + relative(path))


def check_installer_options(path, text, errors):
    # Read the actual installer parser declarations, without invoking installation.
    tree = ast.parse((ROOT / 'mihomoctl/bootstrap.py').read_text(encoding='utf-8'))
    known = {'--rollback', '--help'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument':
            known.update(arg.value for arg in node.args if isinstance(arg, ast.Constant)
                         and isinstance(arg.value, str) and arg.value.startswith('--'))
    for number, line in enumerate(text.splitlines(), 1):
        for segment in re.split(r'[`|\n;]|&&', line):
            match = re.search(r'(?<![\w.-])install\.sh\b', segment)
            if match and re.match(r'\s+--', segment[match.end():]):
                for flag in re.findall(r'--[a-z][a-z-]*', segment[match.end():]):
                    if flag not in known:
                        errors.append('unknown-install-parameter: %s:%d: %s' % (relative(path), number, flag))


def main():
    errors = []
    for path in documents():
        if not path.is_file():
            errors.append('required-document-missing: ' + relative(path))
            continue
        body = path.read_text(encoding='utf-8-sig')
        if '\ufffd' in body:
            errors.append('replacement-character: ' + relative(path))
        check_links(path, body, errors)
        # Changelog entries are dated historical records, not current tutorials.
        current = body.split('\n## [', 2)[:2] if path.name == 'CHANGELOG.md' else None
        check_commands(path, '\n## ['.join(current) if current else body, errors)
        if path.name != 'CHANGELOG.md':
            check_installer_options(path, body, errors)
    for language in ('en', 'zh-CN'):
        for topic in BILINGUAL_TOPICS:
            if not (ROOT / 'docs' / language / topic).is_file():
                errors.append('bilingual-topic-missing: ' + language + '/' + topic)
    for name, target in (('README.md', 'README.en.md'), ('README.en.md', 'README.md'), ('README.zh-CN.md', 'README.md')):
        body = (ROOT / name).read_text(encoding='utf-8')
        if '](' + target + ')' not in body or 'INSTALL.md' not in body:
            errors.append('readme-navigation-missing: ' + name)
    try:
        check_version(ROOT)
    except ValueError as error:
        errors.append(str(error))
    for error in errors:
        print(error)
    if not errors:
        print('documentation: required V1 documents, current CLI examples, languages, links and anchors passed')
    return 1 if errors else 0


if __name__ == '__main__':
    sys.exit(main())
