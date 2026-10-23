#!/usr/bin/env python3
"""Exercise the delivered bundle offline, optionally under two distinct UIDs.

Run with --real-users inside a disposable network namespace as root. Workers run
unprivileged; no accounts or services are created and all homes are temporary.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import shlex
import socket
import subprocess
import sys
import tempfile
import time
import platform

ROOT = Path(__file__).resolve().parents[2]


def run(command, env, **options):
    result = subprocess.run(list(map(str, command)), env=env, capture_output=True,
                            text=True, timeout=120, **options)
    if result.returncode:
        raise RuntimeError('delivered-command-failed: ' + Path(command[0]).name + '\n' + result.stderr[-2000:])
    return result


def terminal_probe(command, env, during=None, remote_runtime=None):
    master, slave = pty.openpty()
    import fcntl
    import struct
    import termios
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 24, 80, 0, 0))
    argv = command if isinstance(command, list) else [str(command)]
    child = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave,
                             env=dict(env, TERM='xterm-256color'), start_new_session=True)
    os.close(slave)
    output, rss, started = bytearray(), 0, time.monotonic()
    first_render = None
    phase, next_key = 0, started + 2
    try:
        while time.monotonic() - started < 20:
            if select.select([master], [], [], .1)[0]:
                try:
                    output.extend(os.read(master, 65536))
                    if first_render is None and len(output) > 1000:
                        first_render = time.monotonic() - started
                except OSError:
                    break
            try:
                status = Path('/proc/%d/status' % child.pid).read_text()
                rss = max(rss, int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmRSS:'))))
            except (OSError, StopIteration):
                pass
            if remote_runtime:
                for process in Path('/proc').iterdir():
                    if not process.name.isdecimal():
                        continue
                    try:
                        if str((process / 'exe').resolve()).startswith(remote_runtime + '/'):
                            status = (process / 'status').read_text()
                            rss = max(rss, int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmRSS:'))))
                    except (OSError, StopIteration, ValueError):
                        pass
            if len(output) > 1000 and time.monotonic() > next_key:
                keys = (b':', b'page proxies\r', b'/', '本地'.encode(), b'\x1b', b'q')
                if phase == 2:
                    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 40, 120, 0, 0))
                    os.kill(child.pid, signal.SIGWINCH)
                if phase == 5 and during:
                    during()
                os.write(master, keys[phase])
                phase += 1
                next_key = time.monotonic() + .5
                if phase == len(keys):
                    child.wait(timeout=15)
                    break
            if child.poll() is not None:
                break
        if child.poll() is None or child.returncode != 0 or b'Traceback' in output or len(output) < 500:
            raise RuntimeError('terminal-ui-failed exit=%s phase=%d\n%s' %
                (child.poll(), phase, bytes(output[-1800:]).decode('utf-8', errors='replace')))
        if '节点'.encode() not in output:
            raise RuntimeError('terminal-unicode-render-failed')
        return {'ui_rss_kib': rss, 'ui_start_and_exit_seconds': round(time.monotonic() - started, 3),
                'ui_first_render_seconds': round(first_render, 3),
                'terminal_unicode_resize_search': phase == 6}
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
        os.close(master)


def worker(root, home, archive):
    root, home = Path(root), Path(home)
    wait = os.environ.get('MIHOMOCTL_PORTABLE_WAIT') == '1'
    ssh = json.loads(os.environ['MIHOMOCTL_PORTABLE_SSH']) if os.environ.get('MIHOMOCTL_PORTABLE_SSH') else None
    tools = home / 'tools'
    tools.mkdir(mode=0o700)
    for name in ('dirname', 'readlink'):
        (tools / name).symlink_to(shutil.which(name))
    env = {'HOME': str(home), 'PATH': str(tools), 'LANG': 'C.UTF-8',
           'XDG_CONFIG_HOME': str(home / 'config'), 'XDG_DATA_HOME': str(home / 'data'),
           'XDG_STATE_HOME': str(home / 'state'), 'XDG_CACHE_HOME': str(home / 'cache'),
           'XDG_RUNTIME_DIR': str(home / 'run'), 'MIHOMOCTL_NO_UPDATE_CHECK': '1'}
    os.environ.clear()
    os.environ.update(env)
    assert shutil.which('python') is None and shutil.which('python3') is None
    unpacked = home / 'unpacked'
    unpacked.mkdir(mode=0o700)
    run(['/usr/bin/tar', '--no-same-owner', '--use-compress-program=/usr/bin/gzip',
         '-xf', archive, '-C', unpacked], env, umask=0o002)
    entries = list(unpacked.iterdir())
    assert len(entries) == 1 and entries[0].is_dir()
    assert not entries[0].stat().st_mode & 0o022
    root = home / 'moved bundle'
    shutil.move(str(entries[0]), root)
    unpacked.rmdir()
    (home / 'run').mkdir(mode=0o700)
    startup = home / '.bashrc'
    startup.write_bytes(b'# keep this file unchanged\n')
    run([root / 'install.sh'], env)
    command = home / '.local/bin/mihomoctl'
    elapsed = []
    for _ in range(3):
        started = time.monotonic()
        run([command, 'version', '--json'], env)
        elapsed.append(time.monotonic() - started)
    run([command, '--help'], env)
    sys.path.insert(0, str((home / 'data/mihomoctl/install/current/lib').resolve()))
    from mihomoctl.app import Application
    from mihomoctl.portable import prepare_core
    from mihomoctl.controller.controller_service import ConsoleService
    from mihomoctl.installation import verify_installed, InstallPaths
    app = Application()
    core = prepare_core(app.scope)
    app.initialize(str(core))
    source = home / 'subscription.yaml'
    source.write_text('proxies: [{name: 本地 A, type: direct}, {name: Local B, type: direct}]\n')
    source.chmod(0o600)
    service = ConsoleService(app.load_manager().core.config, str(app.scope.core_home), app=app)
    try:
        plan = service.subscription_input(str(source), kind='file')
        service.subscription_save_and_start(plan['id'], plan['sha256'])
        service.choose('Proxy', 'Local B')
        app.lifecycle('restart')
        assert service.client().request('/proxies/Proxy')['now'] == 'Local B'
        from mihomoctl.controller.controller_config import read_config, endpoint
        from mihomoctl.controller.controller_api import Client
        _, data, _ = read_config(Path(app.load_manager().core.config))
        port, secret = endpoint(data)
        rejected = False
        try:
            Client(port, 'incorrect-token').request('/version')
        except Exception:
            rejected = True
        assert rejected
        def update_while_open():
            candidate = subprocess.run([command, 'update', root, '--allow-same-version'],
                env=env, capture_output=True, text=True, timeout=120)
            assert candidate.returncode != 0 and 'installation-console-open' in candidate.stderr
        terminal_command = command
        if ssh:
            remote = ['/usr/bin/env', *(key + '=' + value for key, value in env.items()), str(command)]
            terminal_command = ['/usr/bin/ssh', '-F', '/dev/null', '-tt', '-i', ssh['key'],
                '-p', str(ssh['port']), '-oBatchMode=yes', '-oStrictHostKeyChecking=no',
                '-oUserKnownHostsFile=/dev/null', '-oGlobalKnownHostsFile=/dev/null',
                ssh['user'] + '@127.0.0.1', shlex.join(remote)]
        metrics = terminal_probe(terminal_command, env, during=update_while_open,
            remote_runtime=str(command.resolve().parents[1] / 'runtime') if ssh else None)
        scope = app.scope
        record = verify_installed(scope)
        config = Path(app.load_manager().core.config)
        result = {'uid': os.geteuid(), 'controller_port': port, 'selected': 'Local B',
                  'core_sha256': hashlib.sha256(core.read_bytes()).hexdigest(),
                  'config': str(config), 'credentials': str(scope.credentials_dir),
                  'config_sha256': hashlib.sha256(config.read_bytes()).hexdigest(),
                  'version_start_seconds': round(sum(elapsed) / len(elapsed), 3),
                  'installed_bytes': sum(p.stat().st_size for name in ('data', 'config', 'state', 'cache', 'run')
                                         for p in (home / name).rglob('*') if p.is_file()),
                  'extraction_umask_0002': True,
                  'system_python_absent_from_path': True, 'authentication_rejected': rejected,
                  'active_ui_update_refused': True, 'ssh_transport': bool(ssh), **metrics}
        (home / 'ready.json').write_text(json.dumps(result))
        (home / 'ready.json').chmod(0o600)
        if wait:
            while not (home / 'finish').exists():
                time.sleep(.1)
        app.lifecycle('stop')
        # Update through the installed CLI, then check that only current remains.
        run([command, 'update', root, '--allow-same-version'], env)
        run([command, 'version', '--json'], env)
        paths = InstallPaths(scope)
        assert len(list(paths.generations.iterdir())) == 1
        assert not list(paths.backups_root.iterdir())
        assert not list(scope.backups_root.iterdir())
        assert not list(home.rglob('*.before-policy-*'))
        assert not list(home.rglob('pyvenv.cfg'))
        assert config.read_bytes() and hashlib.sha256(config.read_bytes()).hexdigest() == result['config_sha256']
        assert startup.read_bytes() == b'# keep this file unchanged\n'
        result['no_history'] = True
        (home / 'result.json').write_text(json.dumps(result))
    finally:
        # Never leave a test core behind, including after a failed assertion.
        try:
            run([command, 'stop'], env)
        except Exception:
            pass


def verify(bundle, report, real_users=False, require_isolation=False, ssh_user=None):
    if str(ROOT) not in sys.path:
        sys.path.append(str(ROOT))
    from mihomoctl.portable import source_tree, verify_bundle
    isolated = {name for _, name in socket.if_nameindex()} == {'lo'}
    if require_isolation and not isolated:
        raise RuntimeError('network-namespace-required')
    if real_users and os.geteuid() != 0:
        raise RuntimeError('real-users-verification-requires-disposable-root-namespace')
    if isolated and os.geteuid() == 0:
        subprocess.run(['/usr/sbin/ip', 'link', 'set', 'lo', 'up'], check=True)
    with tempfile.TemporaryDirectory(prefix='mihomoctl-portable-acceptance-') as temporary, source_tree(bundle) as source:
        base = Path(temporary)
        base.chmod(0o711)
        root = base / 'moved bundle'  # Proves launchers have no build-time prefix.
        shutil.copytree(source, root)
        delivered = base / 'delivered.tar.gz'
        shutil.copyfile(bundle, delivered)
        delivered.chmod(0o644)
        manifest = verify_bundle(root)
        # Root-owned immutable application files can be shared; every worker
        # installs into a separate private home using the actual delivered CLI.
        for path in (root, *root.rglob('*')):
            path.chmod(0o755 if path.is_dir() or path.stat().st_mode & 0o111 else 0o644)
        users = (65001, 65002) if real_users else (os.geteuid(),)
        sshd, ssh_config, mounted_home = None, None, None
        if ssh_user:
            import pwd
            account = pwd.getpwnam(ssh_user)
            if not real_users or account.pw_uid in (0, 65001):
                raise RuntimeError('ssh-test-requires-an-existing-unprivileged-user')
            if os.readlink('/proc/self/ns/mnt') == os.readlink('/proc/1/ns/mnt'):
                raise RuntimeError('ssh-test-requires-a-private-mount-namespace')
            # This /run is local to the disposable mount namespace.
            subprocess.run(['/usr/bin/mount', '--make-rprivate', '/'], check=True)
            subprocess.run(['/usr/bin/mount', '-t', 'tmpfs', 'tmpfs', '/run'], check=True)
            subprocess.run(['/usr/bin/mount', '-t', 'tmpfs', 'tmpfs', '/var/log'], check=True)
            Path('/run/sshd').mkdir(mode=0o755)
            key = base / 'ssh-key'
            host_key = base / 'host-key'
            for path in (key, host_key):
                subprocess.run(['/usr/bin/ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', path], check=True)
            os.chown(key, account.pw_uid, account.pw_gid)
            key.with_name(key.name + '.pub').chmod(0o644)
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                port = probe.getsockname()[1]
            configuration = base / 'sshd-config'
            configuration.write_text('ListenAddress 127.0.0.1\nPort %d\nHostKey %s\n'
                'PidFile %s\nAuthorizedKeysFile %s\nPasswordAuthentication no\n'
                'KbdInteractiveAuthentication no\nUsePAM yes\nPermitRootLogin no\n'
                'PermitUserRC no\nPrintMotd no\nPrintLastLog no\n'
                # /tmp is sticky and fails sshd's StrictModes ancestry rule.
                # The generated authorized key is root-owned under our 0711
                # root-owned temporary directory; workers cannot modify it.
                'StrictModes no\nAllowUsers %s\nLogLevel VERBOSE\n' %
                (port, host_key, base / 'sshd.pid', key.with_name(key.name + '.pub'), ssh_user))
            ssh_log = (base / 'sshd.log').open('w')
            sshd = subprocess.Popen(['/usr/sbin/sshd', '-D', '-e', '-f', configuration], stderr=ssh_log)
            ssh_log.close()
            users = (65001, account.pw_uid)
            ssh_config = {'user': ssh_user, 'key': str(key), 'port': port}
        children, homes = [], []
        script = base / 'verify.py'
        shutil.copyfile(Path(__file__), script)
        script.chmod(0o644)
        try:
            for index, uid in enumerate(users):
                home = base / ('user-%d' % index)
                home.mkdir(mode=0o700)
                homes.append(home)
                if real_users:
                    os.chown(home, uid, uid)
                if ssh_config and uid == account.pw_uid:
                    mounted_home = Path(account.pw_dir)
                    if mounted_home.parent != Path('/home') or not mounted_home.is_dir():
                        raise RuntimeError('ssh-test-requires-a-normal-existing-home-directory')
                    subprocess.run(['/usr/bin/mount', '--bind', home, mounted_home], check=True)
                environment = dict(os.environ, MIHOMOCTL_PORTABLE_WAIT='1')
                if ssh_config and uid == account.pw_uid:
                    environment['MIHOMOCTL_PORTABLE_SSH'] = json.dumps(ssh_config)
                credentials = {'user': uid, 'group': uid, 'extra_groups': []} if real_users else {}
                output = (base / ('worker-%d.log' % index)).open('w')
                child = subprocess.Popen([root / 'runtime/bin/python3', '-I', '-B', script,
                                          '--worker', root, home, delivered], env=environment,
                                         stdout=output, stderr=output, **credentials)
                output.close()
                children.append(child)
            deadline = time.monotonic() + 180
            while not all((home / 'ready.json').exists() for home in homes):
                if time.monotonic() >= deadline or any(child.poll() is not None for child in children):
                    logs = '\n'.join(p.read_text()[-3000:] for p in base.glob('worker-*.log'))
                    if sshd is not None:
                        logs += '\n' + (base / 'sshd.log').read_text()[-2500:]
                    raise RuntimeError('portable-worker-failed\n' + logs)
                time.sleep(.2)
            rows = [json.loads((home / 'ready.json').read_text()) for home in homes]
            if real_users:
                assert rows[0]['controller_port'] != rows[1]['controller_port']
                denied = subprocess.run([root / 'runtime/bin/python3', '-I', '-c',
                    'import sys; open(sys.argv[1]).read()', rows[0]['config']],
                    user=users[1], group=users[1], extra_groups=[], capture_output=True)
                assert denied.returncode != 0 and b'PermissionError' in denied.stderr
            for home in homes:
                (home / 'finish').touch()
            for index, child in enumerate(children):
                if child.wait(timeout=120) != 0:
                    raise RuntimeError('worker finalization failed\n' +
                                       (base / ('worker-%d.log' % index)).read_text()[-5000:])
            rows = [json.loads((home / 'result.json').read_text()) for home in homes]
            result = {'success': True, 'commit': manifest['commit'], 'version': manifest['version'],
                      'ubuntu': platform.freedesktop_os_release().get('VERSION_ID'),
                      'os': platform.freedesktop_os_release().get('ID'),
                      'publishable': manifest['publishable'], 'network_isolated': isolated,
                      'real_uids': real_users, 'users': rows, 'core_sha256': rows[0]['core_sha256'],
                      'bundle_sha256': hashlib.sha256(delivered.read_bytes()).hexdigest(),
                      'bundle_bytes': delivered.stat().st_size}
        finally:
            for home in homes:
                (home / 'finish').touch(exist_ok=True)
            for child in children:
                if child.poll() is None:
                    try:
                        child.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait()
            if sshd is not None:
                sshd.terminate()
                sshd.wait(timeout=10)
            if mounted_home is not None:
                subprocess.run(['/usr/bin/umount', mounted_home], check=True)
            # Readonly installed generations must be writable before tmp cleanup.
            for path in base.rglob('*'):
                if path.is_dir() and not path.is_symlink():
                    path.chmod(0o700)
        # A CI checkout, its input archive and report destination can all live
        # below the SSH account's home. The disposable bind mount hides that
        # home while workers run: use the staged archive for its identity and
        # publish evidence only after finally has unmounted the test home.
        if report:
            Path(report).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
        print(json.dumps(result, sort_keys=True))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path)
    parser.add_argument('--report', type=Path)
    parser.add_argument('--real-users', action='store_true')
    parser.add_argument('--require-isolation', action='store_true')
    parser.add_argument('--ssh-user', help='existing unprivileged account; requires unshare --mount --net as root')
    parser.add_argument('--worker', nargs=3)
    args = parser.parse_args()
    if args.worker:
        worker(*args.worker)
    else:
        if not args.bundle:
            parser.error('--bundle is required')
        if os.geteuid() == 0:
            # CI checkouts are runner-owned. Execute a root-owned private copy,
            # just as the existing privileged CI runner does.
            with tempfile.TemporaryDirectory(prefix='mihomoctl-portable-verifier-code-') as temporary:
                library = Path(temporary)
                shutil.copytree(ROOT / 'mihomoctl', library / 'mihomoctl',
                                ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
                for path in library.rglob('*'):
                    path.chmod(0o700 if path.is_dir() else 0o600)
                sys.path.insert(0, str(library))
                verify(args.bundle, args.report, args.real_users, args.require_isolation, args.ssh_user)
        else:
            verify(args.bundle, args.report, args.real_users, args.require_isolation, args.ssh_user)
