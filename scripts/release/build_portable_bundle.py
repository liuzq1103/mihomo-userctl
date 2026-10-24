#!/usr/bin/env python3
"""Build a complete relocatable bundle from reviewed artifacts and pinned inputs.

This builder is offline: download the pinned runtime, core and dependency wheels
before invoking it. No interpreter or pip is required on the destination server.
"""
import argparse
import base64
import csv
from email.parser import Parser
import gzip
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from mihomoctl.portable import verify_bundle, MAX_BYTES, MAX_FILES
from mihomoctl.release_artifacts import load_artifacts, safe_member, verify_wheel_inventory
from scripts.release.trim_portable_runtime import trim
from scripts.release.portable_policy import MAX_DOWNLOAD, MAX_EXPANDED

LAUNCHER = '''#!/bin/sh
set -eu
entry=$0
while [ -L "$entry" ]; do
  parent=$(CDPATH= cd -- "$(dirname -- "$entry")" && pwd -P)
  target=$(readlink -- "$entry")
  case $target in /*) entry=$target ;; *) entry=$parent/$target ;; esac
done
root=$(CDPATH= cd -- "$(dirname -- "$entry")/.." && pwd -P)
exec "$root/runtime/bin/python3" -I -B -c 'import sys; sys.path.insert(0, sys.argv.pop(1)); from mihomoctl.cli import main; sys.exit(main())' "$root/lib" "$@"
'''
ROOT_LAUNCHER = '''#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
exec "$root/bin/mihomoctl" "$@"
'''
INSTALLER = ROOT_LAUNCHER.replace('"$@"', '_bundle-install "$@"')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def extract_runtime(archive, destination):
    """Resolve only internal links, then materialize ordinary immutable files."""
    with tempfile.TemporaryDirectory(prefix='mihomoctl-python-') as temporary:
        raw = Path(temporary)
        with tarfile.open(archive, 'r:gz') as package:
            entries, total = {}, 0
            for member in package:
                safe_member(member.name)
                total += member.size
                if (len(entries) >= MAX_FILES or total > MAX_BYTES or member.name in entries
                        or not member.name.startswith('python/')):
                    raise ValueError('unsafe-runtime-archive')
                entries[member.name] = member
            for member in entries.values():
                target = raw / member.name
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with package.extractfile(member) as src, target.open('xb') as dst:
                        shutil.copyfileobj(src, dst)
                    target.chmod(0o755 if member.mode & 0o111 else 0o644)
                elif not member.issym():
                    raise ValueError('unsupported-runtime-archive-member')
            for member in entries.values():
                if not member.issym():
                    continue
                target = raw / member.name
                if Path(member.linkname).is_absolute():
                    raise ValueError('unsafe-runtime-link')
                resolved = (target.parent / member.linkname).resolve()
                if raw.resolve() not in resolved.parents:
                    raise ValueError('unsafe-runtime-link')
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(member.linkname)
        for path in (raw / 'python').rglob('*'):
            if path.is_symlink() and (not path.exists() or (raw / 'python').resolve() not in path.resolve().parents):
                raise ValueError('unsafe-runtime-link')
        shutil.copytree(raw / 'python', destination, symlinks=False)


def build(artifacts, runtime, core, wheelhouse, output, *, worktree=False):
    if sys.platform != 'linux':
        raise ValueError('build-on-linux-required')
    artifacts, runtime, core, wheelhouse, output = map(Path, (artifacts, runtime, core, wheelhouse, output))
    receipt, _ = load_artifacts(artifacts, worktree)
    runtime_pin = json.loads((ROOT / 'scripts/release/portable-runtime.json').read_text())
    core_pin = json.loads((ROOT / 'mihomoctl/mihomo-digests.json').read_text())['pins'][0]
    if digest(runtime) != runtime_pin['sha256'] or digest(core) != core_pin['sha256']:
        raise ValueError('portable-input-digest-mismatch')
    version, epoch = receipt['version'], receipt['source_epoch']
    name = 'mihomoctl-' + version + '-portable-linux-x86_64'
    output.mkdir(parents=True, exist_ok=True)
    archive = output / (name + '.tar.gz')
    if archive.exists() or archive.with_name(archive.name + '.sha256').exists():
        raise ValueError('portable-output-exists')
    with tempfile.TemporaryDirectory(prefix='mihomoctl-portable-') as temporary:
        root = Path(temporary) / name
        root.mkdir(mode=0o700)
        extract_runtime(runtime, root / 'runtime')
        python = root / 'runtime/bin/python3'
        # pip is a build tool only. Dependency resolution is strictly offline.
        subprocess.run([python, '-I', '-B', '-m', 'ensurepip', '--upgrade'], check=True,
                       stdout=subprocess.DEVNULL)
        subprocess.run([python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-compile',
                        '--only-binary=:all:', '--require-hashes', '--find-links', wheelhouse.absolute(),
                        '--target', root / 'lib', '-r', ROOT / 'scripts/textual-requirements.txt'], check=True)
        with tarfile.open(artifacts / ('mihomoctl-' + version + '.tar.gz'), 'r:gz') as package:
            manifest = json.load(package.extractfile('mihomoctl-' + version + '/release-manifest.json'))
        wheel = artifacts / ('mihomoctl-' + version + '-py3-none-any.whl')
        verify_wheel_inventory(wheel, manifest)
        with zipfile.ZipFile(wheel) as package:
            for entry in package.infolist():
                safe_member(entry.filename)
                if not entry.is_dir():
                    target = root / 'lib' / entry.filename
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(package.read(entry))
        # Build-time console-script shebangs contain the temporary prefix.
        # None are part of our public interface; remove them and normalize
        # RECORD so two builders produce identical payloads.
        shutil.rmtree(root / 'lib/bin', ignore_errors=True)
        for path in (root / 'lib').glob('pip*'):
            if path.name == 'pip' or path.name.startswith('pip-') and path.name.endswith('.dist-info'):
                shutil.rmtree(path)
        runtime_packages = root / 'runtime/lib/python3.12/site-packages'
        for path in runtime_packages.glob('pip*'):
            if path.is_dir():
                shutil.rmtree(path)
        for path in (root / 'runtime/bin').glob('pip*'):
            path.unlink()
        pruning = trim(root / 'runtime', scan_root=root)
        (root / 'runtime-trim.json').write_text(json.dumps(pruning, indent=2, sort_keys=True) + '\n')
        for record in (root / 'lib').glob('*.dist-info/RECORD'):
            rows = []
            with record.open(newline='') as stream:
                for row in csv.reader(stream):
                    record_name = row[0]
                    path = root / 'lib' / record_name
                    if '..' in Path(record_name).parts or not path.is_file():
                        continue
                    if path == record:
                        rows.append([record_name, '', ''])
                    else:
                        value = base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).rstrip(b'=').decode()
                        rows.append([record_name, 'sha256=' + value, str(path.stat().st_size)])
            with record.open('w', newline='') as stream:
                csv.writer(stream, lineterminator='\n').writerows(sorted(rows))
        (root / 'bin').mkdir()
        (root / 'core').mkdir()
        for relative, content in (('bin/mihomoctl', LAUNCHER), ('mihomoctl', ROOT_LAUNCHER), ('install.sh', INSTALLER)):
            (root / relative).write_text(content, encoding='utf-8')
            (root / relative).chmod(0o755)
        shutil.copyfile(core, root / 'core/mihomo.gz')
        shutil.copyfile(ROOT / 'assets/licenses/mihomo-LICENSE.txt', root / 'core/LICENSE')
        (root / 'core/SOURCE.txt').write_text(
            'Mihomo ' + core_pin['version'] + '\nCorresponding upstream source:\n'
            'https://github.com/MetaCubeX/mihomo/tree/' + core_pin['version'] + '\n'
            'https://github.com/MetaCubeX/mihomo/archive/refs/tags/' + core_pin['version'] + '.tar.gz\n'
            'The core binary is unmodified and its original compressed SHA256 is recorded in pin.json.\n')
        (root / 'core/pin.json').write_text(json.dumps(core_pin, indent=2) + '\n')
        shutil.copyfile(ROOT / 'LICENSE', root / 'LICENSE')
        licenses = {'components': [], 'files': {}}
        for metadata in sorted((root / 'lib').glob('*.dist-info/METADATA')):
            information = Parser().parsestr(metadata.read_text(encoding='utf-8'))
            licenses['components'].append({
                'name': information['Name'], 'version': information['Version'],
                'license': information['License-Expression'] or information['License'],
                'metadata': metadata.relative_to(root).as_posix()})
        licenses['components'].extend([
            {'name': 'CPython standalone runtime', 'version': runtime_pin['name'],
             'source': runtime_pin['url']},
            {'name': 'Mihomo', 'version': core_pin['version'], 'source': 'core/SOURCE.txt'}])
        for path in sorted(root.rglob('*')):
            if path.is_file() and any(word in path.name.lower() for word in ('license', 'copying', 'notice')):
                licenses['files'][path.relative_to(root).as_posix()] = digest(path)
        (root / 'licenses.json').write_text(json.dumps(licenses, indent=2, sort_keys=True) + '\n')
        (root / 'README.txt').write_text(
            'mihomoctl complete SSH bundle\nVerify the outer checksum through a trusted release record.\n'
            './mihomoctl opens the terminal UI. ./install.sh installs for this user.\n'
            'Python, Textual and the pinned Mihomo core are included. No venv or pip is needed.\n'
            'The private runtime omits development aliases, headers, ensurepip and IDLE.\n'
            'Subscription URLs require reachable HTTPS endpoints. No historical backups are retained.\n'
            'Use ./mihomoctl tui --engine plain for a basic terminal.\n', encoding='utf-8')
        for cache in root.rglob('__pycache__'):
            shutil.rmtree(cache)
        files = {}
        for path in sorted(root.rglob('*')):
            if path.is_file():
                mode = 0o755 if path.stat().st_mode & 0o111 else 0o644
                path.chmod(mode)
                files[path.relative_to(root).as_posix()] = {'sha256': digest(path), 'mode': mode}
        document = {'format': 1, 'kind': 'portable', 'version': version, 'target': 'linux-x86_64',
                    'commit': receipt['commit'], 'publishable': receipt['publishable'],
                    'runtime': runtime_pin, 'core': core_pin, 'files': files}
        (root / 'bundle-manifest.json').write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
        verify_bundle(root)
        if sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) > MAX_EXPANDED:
            raise ValueError('portable-expanded-budget-exceeded')
        subprocess.run([python, '-I', '-B', '-c',
                        'import os, sys, ssl, subprocess, encodings, ctypes, asyncio, multiprocessing, _curses, _tkinter; '
                        'context = ssl.create_default_context(); paths = ssl.get_default_verify_paths(); '
                        'assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname; '
                        'assert (paths.cafile and os.path.isfile(paths.cafile)) or '
                        '(paths.capath and os.path.isdir(paths.capath)); '
                        'subprocess.run([sys.executable, "-I", "-B", "-c", "import ssl, encodings"], check=True, timeout=30); '
                        'child = multiprocessing.get_context("spawn").Process(target=os.getpid); '
                        'child.start(); child.join(30); assert child.exitcode == 0'], check=True)
        subprocess.run([root / 'mihomoctl', 'version', '--json'], check=True)
        temporary_archive = output / ('.' + name + '.partial')
        with temporary_archive.open('xb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch) as gz:
            with tarfile.open(fileobj=gz, mode='w') as package:
                for path in [root, *sorted(root.rglob('*'))]:
                    if path.is_dir() or path.is_file():
                        relative = name if path == root else name + '/' + path.relative_to(root).as_posix()
                        info = package.gettarinfo(path, relative)
                        if path.is_dir():
                            # Explicit directory modes keep tar extraction safe
                            # even with a shared server's common umask 0002.
                            info.mode = 0o755
                        info.uid = info.gid = 0
                        info.uname = info.gname = ''
                        info.mtime = epoch
                        if path.is_dir():
                            package.addfile(info)
                        else:
                            with path.open('rb') as source:
                                package.addfile(info, source)
        if temporary_archive.stat().st_size > MAX_DOWNLOAD:
            temporary_archive.unlink()
            raise ValueError('portable-download-budget-exceeded')
        os.link(temporary_archive, archive)
        temporary_archive.unlink()
    checksum = digest(archive)
    archive.with_name(archive.name + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
    return {'file': archive.name, 'sha256': checksum, 'version': version, 'commit': receipt['commit'],
            'publishable': receipt['publishable'], 'bytes': archive.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('artifacts', 'runtime', 'core', 'wheelhouse', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--worktree', action='store_true')
    args = vars(parser.parse_args())
    os.umask(0o077)
    print(json.dumps(build(**args), sort_keys=True))


if __name__ == '__main__':
    main()
