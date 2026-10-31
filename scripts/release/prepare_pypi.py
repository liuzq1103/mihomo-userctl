#!/usr/bin/env python3
"""Select the exact gated wheel/sdist; never rebuild in the publishing job."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from mihomoctl.release_identity import is_stable, sdist_name, wheel_name
from scripts.release.verify_release import verify


def prepare(download, output, commit, publishing=False):
    gate = json.loads((download / 'release-gate/release-gate.json').read_text())
    candidate = download / 'release-candidate-ubuntu-22.04'
    offline = output / 'offline'
    offline.mkdir(parents=True, mode=0o700)
    for path in download.glob('release-candidate-ubuntu-*/*-offline-*'):
        if path.is_symlink() or not path.is_file():
            raise ValueError('unsafe-offline-asset')
        shutil.copyfile(path, offline / path.name)
    checked = verify(candidate, download, commit, offline, candidate)
    if checked != gate:
        raise ValueError('pypi-gate-recheck-mismatch')
    version = gate['version']
    if publishing and not is_stable(version):
        raise ValueError('development-version-publication-forbidden')
    receipt = json.loads((candidate / 'build-receipt.json').read_text())
    if receipt.get('distribution') != 'mihomo-userctl':
        raise ValueError('pypi-distribution-mismatch')
    destination = output / 'python'
    destination.mkdir(mode=0o700)
    hashes = {}
    for name in (wheel_name(version, 'mihomo-userctl'), sdist_name(version, 'mihomo-userctl')):
        source = candidate / name
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        if source.is_symlink() or receipt['sha256'].get(name) != digest:
            raise ValueError('pypi-artifact-digest-mismatch')
        shutil.copyfile(source, destination / name)
        hashes[name] = digest
    report = {'commit': commit, 'version': version, 'stable': is_stable(version),
              'artifact_sha256': hashes, 'verified': True, 'stage': 'pre-publication-verification'}
    (output / 'pypi-verification.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--publishing', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.download, args.output, args.commit, args.publishing), sort_keys=True))


if __name__ == '__main__':
    main()
