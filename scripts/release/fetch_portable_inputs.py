#!/usr/bin/env python3
"""Download build inputs pinned in the repository; never run on installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def download(pin, repository, tag, directory):
    name = pin.get('name') or pin['asset']
    if Path(name).name != name:
        raise ValueError('invalid-input-name')
    destination = directory / name
    if destination.is_file() and hashlib.sha256(destination.read_bytes()).hexdigest() == pin['sha256']:
        return destination
    headers = {'User-Agent': 'mihomoctl-pinned-build-inputs'}
    request = urllib.request.Request('https://api.github.com/repos/' + repository + '/releases/tags/' + tag,
                                     headers=headers)
    with urllib.request.urlopen(request, timeout=40) as response:
        release = json.load(response)
    asset = next(row for row in release['assets'] if row['name'] == name)
    request = urllib.request.Request(asset['url'], headers=dict(headers, Accept='application/octet-stream'))
    for attempt in range(3):
        try:
            with tempfile.NamedTemporaryFile(dir=directory, delete=False) as output:
                temporary = Path(output.name)
                digest, size = hashlib.sha256(), 0
                with urllib.request.urlopen(request, timeout=60) as response:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > 256 * 1024 * 1024:
                            raise ValueError('build-input-too-large')
                        digest.update(chunk)
                        output.write(chunk)
            if digest.hexdigest() != pin['sha256']:
                raise ValueError('build-input-digest-mismatch')
            os.replace(temporary, destination)
            print('verified:', name)
            return destination
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
        finally:
            if 'temporary' in locals():
                temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    args.output.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime = json.loads((ROOT / 'scripts/release/portable-runtime.json').read_text())
    core = json.loads((ROOT / 'mihomoctl/mihomo-digests.json').read_text())['pins'][0]
    download(runtime, 'astral-sh/python-build-standalone', runtime['release'], args.output)
    download(core, 'MetaCubeX/mihomo', core['version'], args.output)
