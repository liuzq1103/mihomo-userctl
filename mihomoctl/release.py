"""Official release discovery. Acquisition never changes the active installation."""
import json
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
