"""Read and validate release identity without importing the application."""
from pathlib import Path
import json
import re

CURRENT_DISTRIBUTION = 'mihomo-userctl'
LEGACY_DISTRIBUTION = 'mihomoctl'
VERSION_PATTERN = r'\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?(?:\.dev\d+)?'


def version_order(text):
    """Supported PEP 440 subset, including development releases."""
    match = re.fullmatch(r'(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?(?:\.dev(\d+))?', str(text))
    if match is None:
        raise ValueError('unsupported-version-format')
    numbers = tuple(int(n) for n in match[1].split('.'))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    stage = {'a': 0, 'b': 1, 'rc': 2}.get(match[2], -1 if match[4] is not None else 3)
    return numbers, (stage, int(match[3] or 0), 0 if match[4] is not None else 1, int(match[4] or 0))


def distribution(document):
    name = document.get('distribution', LEGACY_DISTRIBUTION)
    if name not in (LEGACY_DISTRIBUTION, CURRENT_DISTRIBUTION):
        raise ValueError('unsupported-release-distribution')
    return name


def release_distribution(version):
    """The public asset naming transition starts with the 1.5 development line."""
    return CURRENT_DISTRIBUTION if version_order(version)[0] >= (1, 5) else LEGACY_DISTRIBUTION


def source_stem(version, name=None):
    return (name or release_distribution(version)) + '-' + version


def wheel_name(version, name=None):
    return (name or release_distribution(version)).replace('-', '_') + '-' + version + '-py3-none-any.whl'


def asset_names(version, name=None):
    stem = source_stem(version, name)
    names = {stem + '.tar.gz', stem + '.zip', wheel_name(version, name)}
    if (name or release_distribution(version)) == CURRENT_DISTRIBUTION:
        names.add(sdist_name(version, name))
    return names


def sdist_name(version, name=None):
    return (name or release_distribution(version)).replace('-', '_') + '-' + version + '.tar.gz'


def is_stable(version):
    return isinstance(version, str) and re.fullmatch(r'\d+\.\d+\.\d+', version) is not None


def version_from_pyproject(root):
    text = (Path(root) / 'pyproject.toml').read_text(encoding='utf-8')
    section = re.search(r'^\[project\]\s*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)
    matches = re.findall(r'^version\s*=\s*"(' + VERSION_PATTERN + r')"\s*$', section[1] if section else '', re.M)
    if len(matches) != 1:
        raise ValueError('project-version-missing-or-invalid')
    return matches[0]


def check(root, documents=True):
    root = Path(root)
    version = version_from_pyproject(root)
    manifest = json.loads((root / 'release-manifest.json').read_text(encoding='utf-8'))
    text = (root / 'mihomoctl/__init__.py').read_text(encoding='utf-8')
    versions = re.findall(r'^__version__\s*=\s*[\'"]([^\'"]+)[\'"]\s*$', text, re.M)
    if versions != [version] or manifest.get('version') != version:
        raise ValueError('release-version-mismatch')
    if documents:
        changelog = (root / 'CHANGELOG.md').read_text(encoding='utf-8')
        latest = re.search(r'^## \[([^\]]+)\]', changelog, re.M)
        if latest is None or latest[1] != version:
            raise ValueError('changelog-version-mismatch')
        for name in ('README.md', 'README.en.md', 'INSTALL.md'):
            body = (root / name).read_text(encoding='utf-8')
            markers = re.findall(r'<!-- stable-version: ([^ ]+) -->', body)
            artifacts = re.findall(r'mihomo(?:ctl|-userctl|_userctl)-(' + VERSION_PATTERN + r')', body)
            if (markers != [version] or (name != 'INSTALL.md' and '**' + version + '**' not in body)
                    or any(v != version for v in artifacts)):
                raise ValueError('document-version-mismatch: ' + name)
            if name == 'INSTALL.md' and '# Install mihomoctl ' + version not in body:
                raise ValueError('document-version-mismatch: ' + name)
    return version
