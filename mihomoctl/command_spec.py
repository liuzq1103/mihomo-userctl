"""The public grammar, shared by dispatch validation, help and generated interfaces.

Building or parsing a parser never loads manager configuration or credentials.
"""
import argparse
import re

from .errors import UsageError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argument values can be private: never echo argparse's raw diagnostic.
        raise UsageError('usage-error', 'invalid command arguments; see --help')


def arg(name, **kwargs):
    return name, kwargs


def core_version(value):
    if not re.fullmatch(r'v\d+\.\d+\.\d+', value):
        raise argparse.ArgumentTypeError('expected vX.Y.Z')
    return value


PROFILE = [arg('--profile'), arg('--binding')]
CORE = [arg('--version', required=True, type=core_version), arg('--sha256'), arg('--dry-run', action='store_true')]
EXPORT = [arg('--output-dir'), arg('--reveal', action='store_true')]
RULES = [arg('--home-dir'), arg('--config')]
NATIVE = {
    'init': [arg('--core', required=True), arg('--port', type=int), arg('--config'),
             arg('--allow-non-loopback', action='append', default=[])],
    'start': [], 'stop': [], 'restart': [], 'status': [],
    'logs': [arg('--lines', type=int, default=50), arg('--follow', action='store_true')],
    'config': {'validate': [arg('--file'), arg('--profile')], 'check': [arg('--file'), arg('--profile')]},
    'profile': {'list': [], 'show': [arg('name')], 'validate': [arg('name')], 'set-default': [arg('name')]},
    'env': {'show': PROFILE + [arg('--reveal', action='store_true')],
            'export': PROFILE + [arg('--output'), arg('--reveal', action='store_true')]},
    'exec': PROFILE, 'direct': [],
    'integration': {'list': [], 'show': [arg('name')], 'check': [arg('name')],
                    'export': [arg('name')] + EXPORT, 'install': [arg('name')], 'remove': [arg('name')]},
    'service': {name: [] for name in ('install', 'start', 'stop', 'restart', 'status')},
    'tun': {name: [] for name in ('status', 'enable', 'disable')},
    'core': {'install': CORE, 'update': CORE, 'adopt': [arg('--path', required=True)], 'list': []},
    'health': PROFILE + [arg('--egress-url')], 'doctor': [],
    'migrate': [arg('--dry-run', action='store_true'), arg('--apply', action='store_true'),
                arg('--remove-loader', action='store_true'), arg('--no-import', action='store_true'), arg('--core')],
    'rollback': [arg('backup')],
    'release': {'check': [], 'fetch': [arg('--output-dir', required=True),
                                      arg('--version', type=core_version),
                                      arg('--target', choices=('ubuntu22.04-x86_64-py310',
                                                               'ubuntu24.04-x86_64-py312'))]},
    'update': [arg('source', nargs='?'), arg('--dry-run', action='store_true'),
               arg('--allow-same-version', action='store_true'), arg('--allow-downgrade', action='store_true'),
               arg('--wheelhouse'), arg('--python')],
    'rules': {'status': RULES, 'check': RULES}, 'version': [],
    # Existing compatibility entries, intentionally omitted from completion.
    'profiles': [], 'export': [arg('--binding', required=True)] + EXPORT,
}
NATIVE['service']['uninstall'] = [arg('--dry-run', action='store_true')]

CONTROLLER_OPTIONS = [
    arg('--config'), arg('--home-dir'), arg('--port', type=int), arg('--archive'), arg('--sha256'),
    arg('--plain', action='store_true'), arg('--engine', choices=('curses', 'textual', 'plain')),
    arg('--theme', choices=('dark', 'light'), default=None), arg('--ascii', action='store_true', dest='ascii_only'),
    arg('--source-file'), arg('--url-file'), arg('--stdin', action='store_true', dest='source_stdin'),
    arg('--policy', choices=('auto', 'nodes', 'provider'), default=None), arg('--script'),
    arg('--apply', action='store_true'), arg('--details', action='store_true'),
    arg('--flclash-compat', action='store_true'),
]
PROBE_OPTIONS = [arg('--url'), arg('--expected-status'), arg('--interval', type=int),
                 arg('--timeout', type=int), arg('--lazy', choices=('true', 'false')),
                 arg('--tolerance', type=int), arg('--preset', choices=('resilient',))]
BRIDGED = {
    'controller': {'status': [], 'initialize': [arg('--port', type=int), arg('--home-dir')],
                   'setup': [arg('--port', type=int), arg('--home-dir'), arg('--archive'), arg('--sha256')], 'token': []},
    'nodes': [], 'groups': [], 'select': [arg('group'), arg('node')], 'latency': [arg('node')],
    'connections': [arg('--details', action='store_true')], 'traffic': [],
    'subscription': {'preview': [arg('--source-file'), arg('--url-file'), arg('--stdin', action='store_true'),
                                arg('--policy', choices=('auto','nodes','provider')), arg('--home-dir')],
                      'apply': [arg('id'), arg('--sha256', required=True), arg('--home-dir')]},
    'tui': [row for row in CONTROLLER_OPTIONS if row[0] in ('--plain','--engine','--theme','--ascii','--stdin',
            '--policy','--script','--details','--flclash-compat','--home-dir')],
    'providers': [], 'provider': {'refresh': [arg('name')]},
    'dns': [arg('name'), arg('record', nargs='?', default='A')], 'mode': [arg('mode', choices=('rule','global','direct'))],
    'health-check': [arg('kind', choices=('group','provider')), arg('name'), arg('--apply', action='store_true'), arg('--home-dir')],
    'manual': [arg('group'), arg('--apply', action='store_true'), arg('--home-dir')],
    'override': [arg('--script', required=True), arg('--apply', action='store_true'),
                 arg('--flclash-compat', action='store_true'), arg('--home-dir')], 'ui': [], 'dashboard': [],
}
RETIRED = ('paseo','codex','opencode','diagnose','ready')
ALIASES = ('profiles','export','dashboard')


def options(parser, rows, context=''):
    grouped = ('--dry-run','--apply') if context == 'migrate' else ('--output','--reveal') if context == 'env export' else ()
    group = parser.add_mutually_exclusive_group(required=True) if grouped else None
    for name, kwargs in rows:
        (group if name in grouped else parser).add_argument(name, **kwargs)
    parser.add_argument('--json', action='store_true', help='emit the mihomoctl/v1 JSON envelope')


def command_parser(command, spec=None):
    if spec is None:
        spec = NATIVE.get(command, BRIDGED.get(command))
    if spec is None:
        raise UsageError('unknown-command', 'unknown command; see mihomoctl --help')
    parser = Parser(prog='mihomoctl ' + command, allow_abbrev=False)
    if isinstance(spec, dict):
        sub = parser.add_subparsers(dest='action', required=True, parser_class=Parser)
        for action, rows in spec.items():
            child = sub.add_parser(action, allow_abbrev=False)
            options(child, rows + ([arg('--config')] if command in BRIDGED else []), command + ' ' + action)
    else:
        rows = list(spec)
        if command in BRIDGED:
            rows += [arg('--config')]
        if command == 'health-check':
            rows += PROBE_OPTIONS
        options(parser, rows, command)
    return parser


def leaf_parser(name):
    # Handlers and the outer dispatcher both consume this same grammar.
    if name in NATIVE and not isinstance(NATIVE[name], dict):
        return command_parser(name)
    for command in NATIVE:
        spec = NATIVE[command]
        if isinstance(spec, dict) and name.startswith(command + '-'):
            action = name[len(command)+1:]
            if action in spec:
                return command_parser(command + ' ' + action, spec[action])
    raise UsageError('usage-error', 'unknown action; see --help')


def validate(command, args):
    values = list(args)
    if command == 'health' and values[:1] == ['check']:
        values.pop(0)
    if command == 'integration' and not values:
        values = ['list']
    return command_parser(command).parse_args(values)


def public_commands():
    return [name for name in (*NATIVE, *BRIDGED) if name not in ALIASES]
