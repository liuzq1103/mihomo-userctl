"""Read and validate release identity without importing the application."""
from pathlib import Path
import json
import re


def version_from_pyproject(root):
    text = (Path(root) / 'pyproject.toml').read_text(encoding='utf-8')
    section = re.search(r'^\[project\]\s*\n(.*?)(?=^\[|\Z)', text, re.M | re.S)
    matches = re.findall(r'^version\s*=\s*"(\d+\.\d+\.\d+)"\s*$', section[1] if section else '', re.M)
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
            artifacts = re.findall(r'mihomoctl-(\d+\.\d+\.\d+)', body)
            if (markers != [version] or (name != 'INSTALL.md' and '**' + version + '**' not in body)
                    or any(v != version for v in artifacts)):
                raise ValueError('document-version-mismatch: ' + name)
            if name == 'INSTALL.md' and '# Install mihomoctl ' + version not in body:
                raise ValueError('document-version-mismatch: ' + name)
    return version
