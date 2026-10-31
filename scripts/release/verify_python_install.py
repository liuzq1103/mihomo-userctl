#!/usr/bin/env python3
"""Install, run and uninstall candidate Python distributions under isolated UIDs.

The supervisor runs only in an explicitly disposable Linux namespace. Workers
never elevate, change startup files, initialize a manager or access the index.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


def invoke(argv, env, cwd=None, success=True, timeout=240):
    result = subprocess.run(list(map(str, argv)), env=env, cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    if success and result.returncode:
        # Install output can contain user paths; keep reports bounded and private.
        raise RuntimeError('installation-command-failed: ' + Path(str(argv[0])).name + ': ' +
                           result.stderr[-1600:])
    return result


def check_cli(path, env, version):
    help_result = invoke([path, '--help'], env)
    if 'Agent workflow' not in help_result.stdout:
        raise RuntimeError('installed-agent-help-missing')
    result = json.loads(invoke([path, 'version', '--json'], env).stdout)
    if result.get('schema') != 'mihomoctl/v1' or result.get('data', {}).get('mihomoctl') != version:
        raise RuntimeError('installed-version-mismatch')
    blocked = invoke([path, 'update', '--latest', '--json'], env, success=False)
    if blocked.returncode != 2 or 'external-installation-managed-externally' not in blocked.stdout:
        raise RuntimeError('external-update-was-not-refused')


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


def worker(args):
    home = Path.home()
    env = dict(os.environ, PIP_NO_INDEX='1', PIP_FIND_LINKS=str(args.wheelhouse),
               PIP_CONFIG_FILE='/dev/null', PIP_DISABLE_PIP_VERSION_CHECK='1',
               PYTHONNOUSERSITE='1', UV_PYTHON_DOWNLOADS='never',
               UV_CACHE_DIR=str(home / 'uv-cache'), UV_TOOL_DIR=str(home / 'uv-tools'),
               UV_TOOL_BIN_DIR=str(home / 'bin'), PIPX_HOME=str(home / 'pipx'),
               PIPX_BIN_DIR=str(home / 'bin'), MIHOMOCTL_NO_UPDATE_CHECK='1')
    env.update({name: str(home / directory) for name, directory in (
        ('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
        ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'),
        ('XDG_RUNTIME_DIR', 'runtime'))})
    protected = {}
    for name in ('.bashrc', '.zshrc', '.profile', 'config/mihomoctl/sentinel'):
        path = home / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text('preserve existing user file\n')
        path.chmod(0o600)
        protected[path] = path.read_bytes()
    tools = home / 'tools'
    invoke([args.python, '-m', 'venv', tools], env)
    py = tools / 'bin/python'
    invoke([py, '-m', 'pip', 'install', '--no-index', '--find-links', args.wheelhouse,
            'uv==0.9.5', 'pipx==1.8.0', 'setuptools==80.9.0', 'wheel==0.45.1'], env)
    env['PATH'] = str(tools / 'bin') + ':/usr/bin:/bin'
    receipt = json.loads((args.artifacts / 'build-receipt.json').read_text())
    version = receipt['version']
    requirement = 'mihomo-userctl==' + version
    wheel = next(args.artifacts.glob('mihomo_userctl-*-py3-none-any.whl'))
    sdist = next(args.artifacts.glob('mihomo_userctl-*.tar.gz'))
    cases = []

    uv = tools / 'bin/uv'
    invoke([uv, 'tool', 'install', '--no-index', '--find-links', args.wheelhouse,
            '--python', args.python, requirement], env)
    check_cli(home / 'bin/mihomoctl', env, version)
    invoke([uv, 'tool', 'upgrade', '--no-index', '--find-links', args.wheelhouse, 'mihomo-userctl'], env)
    invoke([uv, 'tool', 'uninstall', 'mihomo-userctl'], env)
    if (home / 'bin/mihomoctl').exists():
        raise RuntimeError('uv-uninstall-left-launcher')
    cases.append('uv-tool')

    pipx = tools / 'bin/pipx'
    invoke([pipx, 'install', '--python', args.python, requirement], env)
    check_cli(home / 'bin/mihomoctl', env, version)
    invoke([pipx, 'upgrade', 'mihomo-userctl'], env)
    invoke([pipx, 'uninstall', 'mihomo-userctl'], env)
    if (home / 'bin/mihomoctl').exists():
        raise RuntimeError('pipx-uninstall-left-launcher')
    cases.append('pipx')

    # An action-provided, non-externally-managed interpreter permits --user.
    user_env = dict(env)
    user_env.pop('PYTHONNOUSERSITE')
    invoke([args.python, '-m', 'pip', 'install', '--user', requirement], user_env)
    check_cli(home / '.local/bin/mihomoctl', user_env, version)
    invoke([args.python, '-m', 'pip', 'install', '--user', '--upgrade', requirement], user_env)
    invoke([args.python, '-m', 'pip', 'uninstall', '-y', 'mihomo-userctl'], user_env)
    if (home / '.local/bin/mihomoctl').exists():
        raise RuntimeError('pip-user-uninstall-left-launcher')
    cases.append('pip-user')

    distro_stdlib = invoke(['/usr/bin/python3', '-c', 'import sysconfig; print(sysconfig.get_path("stdlib"))'], env).stdout.strip()
    pep668 = 'not-marked'
    if (Path(distro_stdlib) / 'EXTERNALLY-MANAGED').exists():
        refusal = invoke(['/usr/bin/python3', '-m', 'pip', 'install', '--user', requirement], user_env, success=False)
        if refusal.returncode == 0 or 'externally-managed-environment' not in refusal.stderr:
            raise RuntimeError('pep668-user-install-boundary-not-confirmed')
        pep668 = 'refused'

    for kind in ('wheel', 'sdist', 'source', 'editable', 'index'):
        target = home / kind
        invoke([args.python, '-m', 'venv', target], env)
        runtime_py = target / 'bin/python'
        if kind in ('source', 'editable'):
            source = home / (kind + '-source')
            source.mkdir(mode=0o700)
            with tarfile.open(args.artifacts / ('mihomo-userctl-' + version + '.tar.gz')) as archive:
                # The supervisor verified the exact archive hash and members.
                archive.extractall(source)
            source = next(source.iterdir())
            for path in [source, *source.rglob('*')]:
                path.chmod(0o700 if path.is_dir() else 0o600)
            invoke([runtime_py, '-m', 'pip', 'install', 'setuptools==80.9.0', 'wheel==0.45.1'], env)
            command = [runtime_py, '-m', 'pip', 'install', '--no-build-isolation']
            if kind == 'editable':
                command.append('-e')
            invoke([*command, source], env)
        elif kind == 'index':
            # Exercise name-based resolver discovery with the exact candidate.
            index = home / 'index-root'
            package_dir = index / 'simple/mihomo-userctl'
            package_dir.mkdir(parents=True)
            shutil.copyfile(wheel, package_dir / wheel.name)
            (package_dir / 'index.html').write_text('<a href="' + wheel.name + '">' + wheel.name + '</a>')
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(QuietHandler, directory=str(index)))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                index_env = dict(env, PIP_NO_INDEX='0')
                invoke([runtime_py, '-m', 'pip', 'install', '--index-url',
                        'http://127.0.0.1:' + str(server.server_port) + '/simple/',
                        '--find-links', args.wheelhouse, requirement], index_env)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
        else:
            invoke([runtime_py, '-m', 'pip', 'install', wheel if kind == 'wheel' else sdist], env)
        check_cli(target / 'bin/mihomoctl', env, version)
        if kind == 'wheel':
            invoke([runtime_py, '-c', 'import importlib.util; assert importlib.util.find_spec("textual") is None'], env)
            invoke([runtime_py, '-m', 'pip', 'install', 'mihomo-userctl[tui]==' + version], env)
            invoke([runtime_py, '-c', 'import textual; from importlib.metadata import version; assert version("textual") == "8.2.8"'], env)
            cases.append('tui-extra')
        invoke([runtime_py, '-m', 'pip', 'uninstall', '-y', 'mihomo-userctl'], env)
        if (target / 'bin/mihomoctl').exists():
            raise RuntimeError('pip-uninstall-left-launcher')
        cases.append(kind)

    if any(path.read_bytes() != content for path, content in protected.items()):
        raise RuntimeError('protected-user-files-changed')
    if (home / 'config/mihomoctl/manager.yaml').exists():
        raise RuntimeError('package-install-initialized-manager')
    tested_python = invoke([args.python, '-c', 'import platform; print(platform.python_version())'], env).stdout.strip()
    print(json.dumps({'uid': os.geteuid(), 'cases': cases, 'protected_files_unchanged': True,
                      'external_update_refused': True, 'pep668': pep668, 'python': tested_python,
                      'tools': {'uv': invoke([uv, '--version'], env).stdout.strip(),
                                'pipx': invoke([pipx, '--version'], env).stdout.strip()},
                      'success': True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--wheelhouse', type=Path, required=True)
    parser.add_argument('--python', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--worker', action='store_true')
    args = parser.parse_args()
    if args.worker:
        worker(args)
        return
    if sys.platform != 'linux' or os.geteuid() != 0 or os.environ.get('MIHOMO_V1_DISPOSABLE_VM') != '1':
        parser.error('requires an explicitly disposable Linux root namespace')
    network_isolated = {name for _, name in socket.if_nameindex()} == {'lo'}
    if not network_isolated:
        parser.error('isolated network namespace required')
    receipt = json.loads((args.artifacts / 'build-receipt.json').read_text())
    if receipt.get('distribution') != 'mihomo-userctl':
        parser.error('new distribution candidate required')
    for name, digest in receipt['sha256'].items():
        path = args.artifacts / name
        if Path(name).name != name or path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            parser.error('candidate hash mismatch')
    with tempfile.TemporaryDirectory(prefix='mihomoctl-python-install-') as temporary:
        base = Path(temporary)
        base.chmod(0o755)
        inputs = base / 'inputs'
        inputs.mkdir(mode=0o755)
        for dirname, source in (('artifacts', args.artifacts), ('wheelhouse', args.wheelhouse)):
            target = inputs / dirname
            target.mkdir(mode=0o755)
            for path in source.iterdir():
                if not path.is_file() or path.is_symlink():
                    continue
                shutil.copyfile(path, target / path.name)
                (target / path.name).chmod(0o644)
        # Wheelhouse name installs use precisely the candidate wheel.
        for wheel in (inputs / 'artifacts').glob('*.whl'):
            shutil.copyfile(wheel, inputs / 'wheelhouse' / wheel.name)
        script = inputs / 'worker.py'
        shutil.copyfile(__file__, script)
        script.chmod(0o644)
        users = []
        for uid in (62051, 62052):
            print('Checking isolated installation UID ' + str(uid), file=sys.stderr, flush=True)
            home = base / ('user-' + str(uid))
            home.mkdir(mode=0o700)
            os.chown(home, uid, uid)
            command = ['setpriv', '--reuid=' + str(uid), '--regid=' + str(uid), '--clear-groups',
                       str(args.python), str(script), '--worker', '--artifacts', str(inputs / 'artifacts'),
                       '--wheelhouse', str(inputs / 'wheelhouse'), '--python', str(args.python)]
            result = invoke(command, {'HOME': str(home), 'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}, timeout=1800)
            users.append(json.loads(result.stdout.splitlines()[-1]))
        report = {'success': all(row['success'] for row in users), 'version': receipt['version'],
                  'commit': receipt['commit'], 'source_dirty': receipt['source'] != 'git-commit',
                  'os': 'ubuntu', 'ubuntu': platform.freedesktop_os_release()['VERSION_ID'],
                  'python': platform.python_version(), 'network_isolated': True,
                  'artifact_sha256': receipt['sha256'], 'users': users}
        if args.report:
            args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
        print(json.dumps(report, sort_keys=True))


if __name__ == '__main__':
    main()
