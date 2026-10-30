"""The public grammar, shared by dispatch validation, help and generated interfaces.

Building or parsing a parser never loads manager configuration or credentials.
"""
import argparse
import re

from .errors import UsageError


class Parser(argparse.ArgumentParser):
    def error(self, message):
        # Argument values can be private: never echo argparse's raw diagnostic.
        known = sorted({option for action in self._actions for option in action.option_strings})
        raise UsageError('usage-error', 'invalid arguments for ' + self.prog,
                         self.prog + ' --help; valid options: ' + ', '.join(known))


PARAM_HELP = {
    '--core': 'trusted Mihomo executable; does not download a core',
    '--config': 'explicit core YAML file (private, same scope)',
    '--port': 'explicit authenticated loopback proxy port; otherwise allocate per user',
    '--allow-non-loopback': 'authorize this exact non-loopback address (repeatable; no firewall changes)',
    '--profile': 'named manager profile; mutually exclusive with --binding',
    '--binding': 'declared integration binding', '--file': 'configuration file to validate',
    '--dry-run': 'preview without applying the requested change',
    '--apply': 'apply only after reviewing the preview and obtaining explicit authorization',
    '--plan-sha256': 'reset preview digest; required with --apply; stale state requires a new preview',
    '--allow-cross-level': 'explicitly authorize selecting a leaf in a group containing subgroups',
    '--reveal': 'explicitly expose credentials; never upload or log this output',
    '--output': 'private output file; writes credentials with mode 0600',
    '--output-dir': 'destination directory; exported files may contain credentials',
    '--source-file': 'private subscription YAML file; never pass a subscription URL as an argument',
    '--url-file': 'private file containing the subscription URL',
    '--stdin': 'read subscription input from stdin',
    '--policy': 'subscription merge policy; preview before applying',
    '--sha256': 'expected SHA-256 from the reviewed input or preview',
    '--version': 'explicit pinned version vX.Y.Z',
    '--provider': 'exact provider identity; never resolve duplicate names by guessing',
    '--global': 'use the global node identity rather than a provider identity',
    '--engine': 'human interactive frontend; plain is the terminal fallback',
    '--plain': 'human interactive plain menu', '--theme': 'human interface color theme',
    '--ascii': 'use ASCII interface characters', '--home-dir': 'explicit private Mihomo data directory',
    '--script': 'trusted override script; executes code during preview',
    '--flclash-compat': 'explicit compatibility mode for a trusted FlClash script',
    '--details': 'include sensitive connection details; do not log or share',
    '--lines': 'maximum log lines (default: 50)', '--follow': 'stream logs until interrupted',
    '--path': 'trusted existing executable to adopt', '--archive': 'reviewed local dashboard archive',
    '--latest': 'fetch a reviewed stable release from the official repository',
    '--allow-same-version': 'explicitly allow reinstalling the installed version',
    '--allow-downgrade': 'explicitly authorize installing an older version',
    '--wheelhouse': 'trusted local dependency wheel directory (no index access)',
    '--python': 'trusted existing Python interpreter',
    '--remove-loader': 'explicitly remove the reviewed legacy shell loader',
    '--no-import': 'migrate without importing the legacy configuration',
    '--egress-url': 'optional public HTTPS probe; does not prove another application used the proxy',
    '--url': 'public HTTPS health-check target', '--expected-status': 'accepted probe HTTP status range',
    '--interval': 'probe interval in seconds', '--timeout': 'probe timeout in milliseconds',
    '--lazy': 'whether the core may defer idle-group probes',
    '--tolerance': 'URLTest switching tolerance in milliseconds', '--preset': 'explicit probe settings preset',
    '--extras': 'optional dependency group (repeatable)', '--no-extras': 'clear optional dependencies',
    '--target': 'explicit validated release platform',
    'group': 'exact Selector group name from groups --json',
    'node': 'exact unambiguous node/member name; quote spaces and Unicode',
    'name': 'exact configured name', 'id': 'private preview identifier',
    'source': 'reviewed local release archive or directory', 'backup': 'historical rollback is disabled',
    'kind': 'group or provider probe settings', 'record': 'DNS record type (default: A)',
    'mode': 'running-core routing mode; existing connections remain open',
}


def arg(name, **kwargs):
    kwargs.setdefault('help', PARAM_HELP.get(name, 'explicit ' + name.lstrip('-').replace('-', ' ')))
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
    'reset': [arg('--dry-run', action='store_true'), arg('--apply', action='store_true'), arg('--core'), arg('--plan-sha256')],
    'rollback': [arg('backup')],
    'release': {'check': [], 'fetch': [arg('--output-dir', required=True),
                                      arg('--version', type=core_version),
                                      arg('--target', choices=('linux-x86_64', 'ubuntu22.04-x86_64-py310',
                                                               'ubuntu24.04-x86_64-py312'))]},
    'update': [arg('source', nargs='?'), arg('--dry-run', action='store_true'),
               arg('--latest', action='store_true'),
               arg('--allow-same-version', action='store_true'), arg('--allow-downgrade', action='store_true'),
               arg('--wheelhouse'), arg('--python'),
               arg('--extras', action='append', default=None, metavar='GROUP', help='select optional dependencies (repeatable)'),
               arg('--no-extras', action='store_const', const=[], dest='extras', help='clear optional dependencies')],
    'rules': {'status': RULES, 'check': RULES}, 'version': [],
    # Existing compatibility entries, intentionally omitted from completion.
    'profiles': [], 'export': [arg('--binding', required=True)] + EXPORT,
}
NATIVE['service']['uninstall'] = [arg('--dry-run', action='store_true')]

CONTROLLER_OPTIONS = [
    arg('--allow-cross-level', action='store_true'),
    arg('--config'), arg('--home-dir'), arg('--port', type=int), arg('--archive'), arg('--sha256'),
    arg('--plain', action='store_true'), arg('--engine', choices=('curses', 'textual', 'plain')),
    arg('--theme', choices=('dark', 'light'), default=None), arg('--ascii', action='store_true', dest='ascii_only'),
    arg('--source-file'), arg('--url-file'), arg('--stdin', action='store_true', dest='source_stdin'),
    arg('--policy', choices=('auto', 'nodes', 'provider', 'policy'), default=None), arg('--script'),
    arg('--apply', action='store_true'), arg('--details', action='store_true'),
    arg('--flclash-compat', action='store_true'), arg('--provider'), arg('--global', action='store_true', dest='global_node'),
]
PROBE_OPTIONS = [arg('--url'), arg('--expected-status'), arg('--interval', type=int),
                 arg('--timeout', type=int), arg('--lazy', choices=('true', 'false')),
                 arg('--tolerance', type=int), arg('--preset', choices=('resilient',))]
BRIDGED = {
    'controller': {'status': [], 'initialize': [arg('--port', type=int), arg('--home-dir')],
                   'setup': [arg('--port', type=int), arg('--home-dir'), arg('--archive'), arg('--sha256')], 'token': []},
    'nodes': [], 'groups': [], 'select': [arg('group'), arg('node'), arg('--allow-cross-level', action='store_true')],
    'latency': [arg('node'), arg('--provider'), arg('--global', action='store_true', dest='global_node')],
    'connections': [arg('--details', action='store_true')], 'traffic': [],
    'subscription': {'preview': [arg('--source-file'), arg('--url-file'), arg('--stdin', action='store_true'),
                                arg('--policy', choices=('auto','nodes','provider','policy')), arg('--home-dir')],
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
    grouped = ('--dry-run','--apply') if context in ('migrate', 'reset') else ('--output','--reveal') if context == 'env export' else ('--extras','--no-extras') if context == 'update' else ()
    group = parser.add_mutually_exclusive_group(required=context != 'update') if grouped else None
    for name, kwargs in rows:
        (group if name in grouped else parser).add_argument(name, **kwargs)
    parser.add_argument('--json', action='store_true', help='emit the mihomoctl/v1 JSON envelope')


def command_parser(command, spec=None):
    if spec is None:
        spec = NATIVE.get(command, BRIDGED.get(command))
    if spec is None:
        raise UsageError('unknown-command', 'unknown command; see mihomoctl --help')
    parser = Parser(prog='mihomoctl ' + command, allow_abbrev=False,
                    description=command_description(command), formatter_class=argparse.RawDescriptionHelpFormatter)
    if isinstance(spec, dict):
        sub = parser.add_subparsers(dest='action', required=True, parser_class=Parser)
        for action, rows in spec.items():
            child = sub.add_parser(action, allow_abbrev=False,
                                   description=command_description(command + ' ' + action),
                                   formatter_class=argparse.RawDescriptionHelpFormatter)
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


COMMAND_GROUPS = {
    "Common": {
        "start": "Start the managed Mihomo runtime.",
        "stop": "Stop the managed runtime.",
        "restart": "Restart to apply saved configuration.",
        "status": "Show runtime facts and evidence.",
        "tui": "Open the interactive console.",
        "health": "Check runtime readiness and proxy access.",
        "doctor": "Diagnose configuration and runtime prerequisites.",
    },
    "Service and configuration": {
        "init": "Initialize a user-scoped runtime configuration.",
        "reset": "Restore the managed runtime to its initial defaults.",
        "logs": "Read managed runtime logs.",
        "config": "Validate the active or specified configuration.",
        "service": "Manage the owned systemd service.",
        "core": "Install, adopt or list Mihomo binaries.",
        "tun": "Inspect or change explicit TUN settings.",
        "controller": "Inspect or initialize the local controller.",
    },
    "Nodes and routing": {
        "nodes": "List exact node names from the core proxy table.",
        "groups": "Inspect routing groups and selected chains.",
        "select": "Select a member of a manual group.",
        "latency": "Probe one node against the public HTTPS target.",
        "connections": "Inspect active connection chains.",
        "traffic": "Sample upload and download rates.",
        "subscription": "Preview and apply a private subscription.",
        "providers": "List proxy providers and their state.",
        "provider": "Request a proxy provider refresh.",
        "dns": "Query DNS through the controller.",
        "mode": "Change the running core routing mode.",
        "health-check": "Preview or save group/provider probe settings.",
        "manual": "Preview conversion to a manual routing group.",
        "override": "Preview a trusted routing script.",
        "rules": "Inspect and validate custom rule state.",
        "ui": "Show the configured dashboard access URL.",
    },
    "Environment and access": {
        "profile": "Inspect and select proxy profiles.",
        "env": "Show or export scoped proxy variables.",
        "exec": "Run a child with a selected proxy environment.",
        "direct": "Run a child with proxy variables removed.",
        "integration": "Inspect and export declarative application bindings.",
    },
    "Installation and release": {
        "version": "Show the installed CLI version.",
        "update": "Preview or install a reviewed release.",
        "release": "Check or fetch release artifacts.",
        "rollback": "Historical rollback is not supported.",
        "migrate": "Preview or apply migration from the legacy layout.",
    },
}


def grouped_help():
    lines = ["Usage: mihomoctl [--user|--system] COMMAND [OPTIONS] [--json]",
             "Agent-first user-level Mihomo manager for shared Linux servers."]
    for title, commands in COMMAND_GROUPS.items():
        lines.extend(("", title + ":"))
        lines.extend("  %-14s %s" % (name, description) for name, description in commands.items())
    lines.extend(("", AGENT_GUIDE, "", "Use mihomoctl COMMAND --help for options and side effects."))
    return "\n".join(lines)


SIDE_EFFECTS = {
    'init': 'Writes private manager/configuration/credentials; no download or start. Existing state is preserved.',
    'start': 'Starts only the owned runtime. May allocate authenticated loopback ports.',
    'stop': 'Stops only the owned runtime; interrupts its proxy connections.',
    'restart': 'Stops and starts the owned runtime to apply saved configuration.',
    'select': 'Changes a Selector immediately; read-back confirms selection. May persist the current choice; existing connections stay open. Record the old choice first. --allow-cross-level requires explicit authorization.',
    'tui': 'INTERACTIVE HUMAN OPERATION ONLY. May initialize, save configuration or change the runtime after confirmation. Agents must use explicit CLI commands.',
    'reset': 'DESTRUCTIVE: replaces configuration and credentials and stops the owned runtime. First use --dry-run; only after explicit human authorization use --apply --plan-sha256 HASH. No historical rollback.',
    'migrate': 'Preview with --dry-run. --apply changes owned legacy configuration; --remove-loader explicitly changes the reviewed legacy loader.',
    'subscription preview': 'Reads private input; may download subscription/provider resources; writes private temporary preview material. Does not apply configuration.',
    'subscription apply': 'Writes the reviewed preview after digest validation. Configuration changes need explicit restart.',
    'core install': 'Acquires and verifies an explicit fixed core version. Does not start it or replace an active core.',
    'core update': 'Installs an explicitly selected verified core; active-core replacement remains explicit.',
    'core adopt': 'Records a trusted existing binary; does not copy or download it.',
    'update': 'Complete installations only: atomically replaces managed program code. Does not replace the active core. --latest downloads reviewed assets; local-source updates are offline. External Python installs must use their package manager.',
    'release check': 'Queries official stable-release metadata; does not install or prove the current version is latest.',
    'release fetch': 'Downloads and validates official assets into the explicit output directory; does not install.',
    'provider refresh': 'Requests a provider download/refresh; response confirms the request, not refresh completion.',
    'latency': 'Sends a public HTTPS probe through the exact node identity; may update core probe state. Not application end-to-end evidence.',
    'health': 'Probes local authenticated listeners; an explicit egress URL sends an external request. Does not prove another application used a remote node.',
    'health-check': 'Preview by default; --apply saves probe settings. Explicit restart required.',
    'manual': 'Preview by default; --apply converts the group to a Selector in saved configuration. Explicit restart required.',
    'override': 'Executes the explicitly trusted script for preview; --apply writes its reviewed configuration. Explicit restart required.',
    'mode': 'Changes running-core routing mode immediately; does not save configuration or close existing connections.',
    'exec': 'After local health passes, replaces this process with COMMAND and injects private proxy variables into that child only. Child exit/signal semantics are preserved.',
    'direct': 'Replaces this process with COMMAND after removing proxy variables from that child only.',
    'env export': 'Writes a private environment file; --reveal explicitly prints credentials instead. Does not modify the caller shell.',
    'env show': 'Read-only and redacted by default. --reveal explicitly exposes credentials.',
    'profile set-default': 'Saves the manager default profile; existing processes keep their environment.',
    'integration export': 'Writes declared integration files, which may contain private credentials; no third-party restart.',
    'integration install': 'Installs only the declared owned integration files; no third-party restart.',
    'integration remove': 'Removes only receipt-owned integration files; no third-party restart.',
    'service': 'Explicit optional systemd backend operations; process mode does not require systemd. Install/start/stop/restart/uninstall affect only the owned service.',
    'tun': 'Inspection is read-only; enable/disable require explicit --system and administrator authorization. Never self-elevates.',
    'controller': 'status is read-only; initialize/setup write private controller configuration. token reveals the secret only in a private terminal, never JSON.',
    'dns': 'Sends a DNS query through the local owned controller.',
    'rollback': 'Historical rollback is disabled. Unfinished transaction recovery remains available automatically.',
}


def command_description(command):
    root = command.split()[0]
    summary = next((items[root] for items in COMMAND_GROUPS.values() if root in items), '')
    effect = SIDE_EFFECTS.get(command, SIDE_EFFECTS.get(root, 'Read-only inspection; default output omits credentials.'))
    return summary + '\n\nEffects: ' + effect


AGENT_GUIDE = '''Agent workflow (observe -> adjust -> verify -> restore):
  mihomoctl status --json
  mihomoctl doctor --json
  mihomoctl groups --json                 # record each affected Selector's original choice
  mihomoctl nodes --json                  # preserve provider identity; never guess duplicate names
  mihomoctl select 'Region' 'Node' --json  # first adjust a region's direct member
  mihomoctl select 'Entry' 'Region' --json # then adjust the entry group; do not skip layers
  mihomoctl health check --json
  mihomoctl exec -- curl --head https://example.com
  mihomoctl select 'Entry' 'Original' --json
  mihomoctl groups --json                 # restore every changed group and verify again
Selection/probe success does not prove a particular application's request used a remote node.
If a change fails, inspect again; never assume a successful HTTP write actually took effect.
If the original state needs cross-level authorization, obtain it before temporary adjustment.

Initialization and private subscription workflow:
  mihomoctl init --core /absolute/path/to/trusted/mihomo
  mihomoctl subscription preview --source-file /private/subscription.yaml --policy nodes --json
  mihomoctl subscription apply PREVIEW_ID --sha256 REVIEWED_SHA256 --json
  mihomoctl start --json

Machine interface: --json emits mihomoctl/v1 {schema,command,scope,overall,data,checks,errors}.
PASS=0; FAIL=1; UNVERIFIED=2. exec/direct preserve the child's exit code after it starts.
Scope flags precede COMMAND. Arguments after exec/direct -- belong unchanged to the child.

Safety and authorization:
  Default: user/process; each Linux account owns its manager, credentials, core and ports.
  Authenticated 127.0.0.1 listeners by default; non-local addresses need exact explicit authorization.
  No sudo/self-elevation, shell startup edits, global proxy takeover or other-user operations.
  --system must be explicit. systemd --user is optional. Configuration/credentials stay private.
  Never pass secrets or subscription URLs on argv, print --reveal/token output into logs, or auto-run tui.
  Agents must not reset without reviewed --dry-run output and explicit human authorization.
  reset --apply also requires --plan-sha256 from that preview; changed state invalidates the preview.
  Do not use reset to restore node choices. Current selection persists; historical rollback is disabled.
  Use the original package manager to upgrade/uninstall uv/pipx/pip installations.'''
