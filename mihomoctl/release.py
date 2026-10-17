"""Official release discovery. Acquisition never changes the active installation."""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import __version__
from .errors import MihomoctlError

REPOSITORY = 'liuzq1103/mihomo-userctl'
API = 'https://api.github.com/repos/' + REPOSITORY
WEB = 'https://github.com/' + REPOSITORY
HOSTS = {'api.github.com', 'github.com', 'objects.githubusercontent.com',
         'release-assets.githubusercontent.com'}
MAX_METADATA = 2 * 1024 * 1024
MAX_RELEASE_BYTES = 64 * 1024 * 1024
MAX_KIT_EXPANDED_BYTES = 128 * 1024 * 1024


class ReleaseError(MihomoctlError):
    code = 'release-unverified'


def version_key(version):
    if not isinstance(version, str) or not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ReleaseError('release-version-invalid')
    return tuple(int(part) for part in version.split('.'))


def validate_url(value):
    try:
        url = urlsplit(value)
        valid = (url.scheme == 'https' and url.hostname in HOSTS and
                 not url.username and not url.password and url.port in (None, 443)
                 and not url.fragment and not any(ord(c) < 33 or ord(c) == 127 for c in value))
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise ReleaseError('release-url-refused')


def transfer(url, destination, limit, timeout):
    """Bound DNS, TLS and streaming in a killable isolated process."""
    validate_url(url)
    if timeout <= 0:
        raise ReleaseError('release-network-unavailable')
    worker = Path(__file__).with_name('release_network.py')
    try:
        result = subprocess.run([sys.executable, '-I', '-B', str(worker), url,
                                 str(destination), str(limit)], stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise ReleaseError('release-network-unavailable') from None
    if result.returncode:
        raise ReleaseError('release-network-unavailable')


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError):
        raise ReleaseError('release-metadata-invalid') from None


def metadata(version=None, timeout=30):
    endpoint = '/releases/latest'
    if version is not None:
        if not isinstance(version, str) or not version.startswith('v'):
            raise ReleaseError('release-version-invalid')
        version_key(version[1:])
        endpoint = '/releases/tags/' + version
    with tempfile.TemporaryDirectory(prefix='mihomoctl-release-meta-') as directory:
        path = Path(directory) / 'metadata.json'
        transfer(API + endpoint, path, MAX_METADATA, timeout)
        data = read_json(path)
    if not isinstance(data, dict):
        raise ReleaseError('release-metadata-invalid')
    tag = data.get('tag_name')
    if (not isinstance(tag, str) or not tag.startswith('v') or data.get('draft') is not False
            or data.get('prerelease') is not False or (version is not None and tag != version)):
        raise ReleaseError('release-not-stable')
    version_key(tag[1:])
    return data


def observation(data, current_version=__version__):
    version = data['tag_name'][1:]
    return {'current_version': current_version, 'observed_version': version,
            'newer_available': version_key(version) > version_key(current_version),
            'checked_at': int(time.time()), 'release_url': WEB + '/releases/tag/v' + version}


def check(timeout=30):
    return observation(metadata(timeout=timeout))


def check_text(data):
    message = ('Newer release observed: ' + data['observed_version'] if data['newer_available']
               else 'No higher version observed in this check')
    return message + '\n' + data['release_url'] + '\nchecked_at=' + str(data['checked_at'])


def _api_json(endpoint, deadline):
    with tempfile.TemporaryDirectory(prefix='mihomoctl-release-api-') as directory:
        path = Path(directory) / 'body'
        transfer(API + endpoint, path, MAX_METADATA, min(30, deadline - time.monotonic()))
        return read_json(path)


def tag_commit(tag, deadline):
    data = _api_json('/git/ref/tags/' + tag, deadline)
    for _ in range(6):
        obj = data.get('object') if isinstance(data, dict) else None
        if not isinstance(obj, dict) or not re.fullmatch(r'[a-f0-9]{40}', str(obj.get('sha'))):
            raise ReleaseError('release-tag-invalid')
        if obj.get('type') == 'commit':
            return obj['sha']
        if obj.get('type') != 'tag':
            break
        data = _api_json('/git/tags/' + obj['sha'], deadline)
    raise ReleaseError('release-tag-invalid')


def _assets(data):
    result = {}
    if not isinstance(data.get('assets'), list):
        raise ReleaseError('release-assets-invalid')
    for row in data['assets']:
        if not isinstance(row, dict) or not isinstance(row.get('name'), str) or row['name'] in result:
            raise ReleaseError('release-assets-invalid')
        result[row['name']] = row
    return result


def _asset(data, assets, name, directory, deadline, limit):
    row = assets.get(name)
    expected_url = WEB + '/releases/download/' + data['tag_name'] + '/' + name
    if (not row or row.get('browser_download_url') != expected_url or row.get('state') != 'uploaded'
            or type(row.get('size')) is not int or not 0 < row['size'] <= limit):
        raise ReleaseError('release-asset-missing-or-invalid', name)
    path = directory / name
    transfer(expected_url, path, limit, min(60, deadline - time.monotonic()))
    if path.stat().st_size != row['size']:
        raise ReleaseError('release-asset-size-mismatch', name)
    from .release_artifacts import digest
    expected = row.get('digest')
    if expected is not None and expected != 'sha256:' + digest(path):
        raise ReleaseError('release-asset-digest-mismatch', name)
    row['_digest_verified'] = expected is not None
    return path


def _validate_release(directory, version):
    from . import installation
    from .release_artifacts import load_artifacts, verify_source_inventory, verify_wheel_inventory
    receipt, _ = load_artifacts(directory, False)
    if receipt['version'] != version:
        raise ReleaseError('release-version-mismatch')
    source = directory / ('mihomoctl-' + version + '.tar.gz')
    with tempfile.TemporaryDirectory(prefix='mihomoctl-release-validate-') as temporary:
        root = installation.extract_archive(source, Path(temporary))
        manifest = installation.load_manifest(root)
        installation.verify_inventory(root, manifest)
        installation.cross_check_pyproject(root, manifest)
        if manifest['version'] != version:
            raise ReleaseError('release-version-mismatch')
        for suffix in ('.tar.gz', '.zip'):
            verify_source_inventory(directory / ('mihomoctl-' + version + suffix), manifest)
        from zipfile import ZipFile
        with ZipFile(directory / ('mihomoctl-' + version + '.zip')) as package:
            for relative in manifest['inventory']['files']:
                if package.read('mihomoctl-' + version + '/' + relative) != (root / relative).read_bytes():
                    raise ReleaseError('release-source-formats-disagree')
        wheel = directory / ('mihomoctl-' + version + '-py3-none-any.whl')
        verify_wheel_inventory(wheel, manifest)
        # Complete wheel metadata/RECORD checks without executing any payload.
        info = installation.parse_wheel_filename(wheel)
        with ZipFile(wheel) as package:
            installation._wheel_limits(package)
            installation._read_wheel_metadata(package, info)
            installation._verify_record(package, info)
            for relative in manifest['inventory']['runtime_files']:
                if package.read(relative) != (root / relative).read_bytes():
                    raise ReleaseError('release-wheel-source-disagree')
    return receipt


def _publish(stage, destination):
    """Atomic directory publication with a kernel-enforced no-overwrite rule."""
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise ReleaseError('release-atomic-publication-unavailable')
    rename.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
        error = ctypes.get_errno()
        code = 'release-output-exists' if error in (errno.EEXIST, errno.ENOTEMPTY) else 'release-publication-failed'
        raise ReleaseError(code)


def fetch(scope, output_dir, version=None, target=None, *, selected=None, timeout=300):
    import tarfile
    import zipfile
    try:
        return _fetch(scope, output_dir, version, target, selected=selected, timeout=timeout)
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile, EOFError, KeyError, TypeError) as error:
        detail = str(error).split(':', 1)[0]
        detail = detail if re.fullmatch(r'[a-z][a-z0-9-]{1,79}', detail) else None
        raise ReleaseError('release-artifact-invalid', detail) from None


def _fetch(scope, output_dir, version=None, target=None, *, selected=None, timeout=300):
    """Acquire a complete verified release in a new private directory."""
    from .release_artifacts import TARGETS, load_bundle, checked_payload
    from .trust import require_private_dir, require_trusted_dir, _check_ancestors
    scope.require_mutation()
    if target is not None and target not in TARGETS:
        raise ReleaseError('release-target-unsupported')
    destination = Path(output_dir).expanduser().absolute()
    if not destination.parent.exists() and not destination.parent.is_symlink():
        require_private_dir(destination.parent, create=True)
    else:
        _check_ancestors(destination.parent, 'release-output-untrusted', {0, os.geteuid()})
        require_trusted_dir(destination.parent)
    if destination.exists() or destination.is_symlink():
        raise ReleaseError('release-output-exists')
    deadline = time.monotonic() + timeout
    data = selected if selected is not None else metadata(version, min(30, timeout))
    tag = data['tag_name']
    selected_version = tag[1:]
    version_key(selected_version)
    commit = tag_commit(tag, deadline)
    assets = _assets(data)
    with tempfile.TemporaryDirectory(prefix='.mihomoctl-fetch-', dir=destination.parent) as temporary:
        stage = Path(temporary) / 'payload'
        stage.mkdir(mode=0o700)
        gate_path = _asset(data, assets, 'release-gate.json', stage, deadline, MAX_METADATA)
        if target:
            name = 'mihomoctl-' + selected_version + '-offline-' + target + '.tar.gz'
            bundle = _asset(data, assets, name, stage, deadline, MAX_RELEASE_BYTES)
            _asset(data, assets, name + '.sha256', stage, deadline, 1024)
            manifest, payload = load_bundle(bundle, target, max_bytes=MAX_KIT_EXPANDED_BYTES)
            if manifest['commit'] != commit or manifest['version'] != selected_version:
                raise ReleaseError('release-bundle-identity-mismatch')
            kit = stage / 'kit'
            kit.mkdir(mode=0o700)
            for relative, body in payload.items():
                path = kit / relative
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                path.write_bytes(body)
                path.chmod(0o600)
            folder = kit / 'release'
            receipt, dependencies = checked_payload(folder, kit / 'wheelhouse', target)
            if dependencies != manifest['dependencies']:
                raise ReleaseError('release-bundle-dependencies-mismatch')
            wheelhouse = 'kit/wheelhouse'
        else:
            folder = stage / 'release'
            folder.mkdir(mode=0o700)
            names = ['mihomoctl-' + selected_version + suffix for suffix in
                     ('.tar.gz', '.zip', '-py3-none-any.whl')]
            for name in names + ['SHA256SUMS', 'build-receipt.json']:
                _asset(data, assets, name, folder, deadline,
                       MAX_METADATA if name in ('SHA256SUMS', 'build-receipt.json') else MAX_RELEASE_BYTES)
            wheelhouse = None
        receipt = _validate_release(folder, selected_version)
        gate = read_json(gate_path)
        required = set(receipt['sha256']) | {'SHA256SUMS', 'build-receipt.json'}
        if target:
            required |= {name, name + '.sha256'}
        if (receipt['commit'] != commit or not isinstance(gate, dict) or gate.get('verified') is not True
                or gate.get('commit') != commit or gate.get('version') != selected_version
                or not isinstance(gate.get('assets'), list)
                or any(not isinstance(asset, str) for asset in gate['assets'])
                or len(gate['assets']) != len(set(gate['assets'])) or not required <= set(gate['assets'])
                or gate.get('ubuntu') != ['22.04', '24.04']):
            raise ReleaseError('release-gate-mismatch')
        source = (folder / ('mihomoctl-' + selected_version + '.tar.gz')).relative_to(stage).as_posix()
        record = {'version': selected_version, 'commit': commit, 'source': source,
                  'wheelhouse': wheelhouse, 'target': target, 'release_url': WEB + '/releases/tag/' + tag,
                  'github_digest_checks': {name: row['_digest_verified'] for name, row in assets.items()
                                           if '_digest_verified' in row}}
        record_path = stage / 'acquisition.json'
        record_path.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
        record_path.chmod(0o600)
        # Paths in the transport record stay relative when moved to another machine.
        _publish(stage, destination)
    return dict(record, output_dir=str(destination), source=str(destination / source),
                wheelhouse=str(destination / wheelhouse) if wheelhouse else None)


def matching_target(python):
    import platform
    from .installation import interpreter_target
    from .release_artifacts import TARGETS
    environment = interpreter_target(python)
    try:
        system = platform.freedesktop_os_release()
    except OSError:
        return None
    for target, (ubuntu, version, _glibc) in TARGETS.items():
        if (system.get('ID') == 'ubuntu' and system.get('VERSION_ID') == ubuntu
                and environment['machine'] == 'x86_64' and environment['implementation'] == 'cpython'
                and tuple(environment['version'][:2]) == version):
            return target
    return None


def update_latest(scope, **options):
    """Acquisition followed by the unchanged offline transactional updater."""
    from . import installation
    from .trust import require_private_dir
    scope.require_mutation()
    record = installation.current_record(scope)
    current = installation.verify_installed(scope)['version'] if record else __version__
    selected = metadata()
    observed = observation(selected, current)
    if not observed['newer_available']:
        return dict(observed, changed=False)
    python = installation.resolve_python(options.get('python'), system=scope.system)
    target = None if options.get('wheelhouse') else matching_target(python)
    # Acquisition is temporary; a successful update backup is self-contained.
    staging = scope.cache_root / 'release-acquisition'
    require_private_dir(staging, create=True)
    with tempfile.TemporaryDirectory(prefix='update-', dir=staging) as temporary:
        acquired = fetch(scope, Path(temporary) / 'release', target=target, selected=selected)
        arguments = dict(options)
        arguments['python'] = str(python)
        arguments['wheelhouse'] = options.get('wheelhouse') or acquired['wheelhouse']
        result = installation.update(scope, Path(acquired['source']), **arguments)
    return dict(result, acquisition={'version': acquired['version'], 'commit': acquired['commit'],
                                    'target': target, 'release_url': acquired['release_url']},
                changed=not options.get('dry_run', False))
