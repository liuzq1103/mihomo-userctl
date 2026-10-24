"""Conservative, fail-closed pruning of the pinned materialized CPython tree."""
from pathlib import Path
import re
import shutil
import subprocess

from scripts.release.portable_policy import file_digest

ALIASES = {'bin/python': 'bin/python3', 'bin/python3.12': 'bin/python3',
           'lib/libpython3.12.so': 'lib/libpython3.12.so.1.0'}
TOOLS = ('2to3', '2to3-3.12', 'idle3', 'idle3.12', 'pydoc3', 'pydoc3.12',
         'python3-config', 'python3.12-config')
DIRECTORIES = ('include', 'lib/python3.12/ensurepip', 'lib/python3.12/idlelib')


def trim(runtime, *, scan_root=None):
    runtime = Path(runtime)
    removed = {}
    for alias, canonical in ALIASES.items():
        if (not (runtime / alias).is_file() or not (runtime / canonical).is_file()
                or file_digest(runtime / alias) != file_digest(runtime / canonical)):
            raise ValueError('runtime-alias-layout-mismatch: ' + alias)
    for name in (*('bin/' + name for name in TOOLS), *DIRECTORIES):
        if not (runtime / name).exists():
            raise ValueError('runtime-prune-layout-mismatch: ' + name)
    # The retained SONAME is deliberate. Do not remove shared libpython or
    # general standard-library components based on the interpreter alone.
    for path in sorted(Path(scan_root or runtime).rglob('*')):
        if path.is_symlink():
            raise ValueError('materialized-runtime-required')
        if not path.is_file():
            continue
        with path.open('rb') as stream:
            elf = stream.read(4) == b'\x7fELF'
        if elf:
            result = subprocess.run(['readelf', '-dW', str(path)], check=True,
                                    capture_output=True, text=True)
            needed = re.findall(r'\(NEEDED\).*?\[([^\]]+)\]', result.stdout)
            if any(Path(name).name == 'libpython3.12.so' for name in needed):
                raise ValueError('removed-runtime-library-required: ' + str(path))
    paths = [runtime / name for name in ALIASES]
    paths.extend(runtime / 'bin' / name for name in TOOLS)
    paths.extend(runtime / name for name in DIRECTORIES)
    for path in paths:
        files = sorted(path.rglob('*')) if path.is_dir() else [path]
        for item in files:
            if item.is_file():
                if any(word in item.name.lower() for word in ('license', 'copying', 'notice')):
                    raise ValueError('pruned-license-requires-review: ' + str(item))
                removed[item.relative_to(runtime).as_posix()] = {
                    'sha256': file_digest(item), 'bytes': item.stat().st_size}
    for path in paths:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
    for path in (runtime / 'bin').iterdir():
        if path.is_file():
            with path.open('rb') as stream:
                body = stream.read(16384)
            if body.startswith(b'#!') and b'python3.12' in body:
                raise ValueError('dangling-runtime-wrapper: ' + path.name)
    return {'format': 1, 'removed': removed,
            'removed_logical_bytes': sum(row['bytes'] for row in removed.values()),
            'retained_shared_libpython': True}
