#!/usr/bin/env python3
"""Synchronize derived version stamps explicitly, or check without writing."""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from mihomoctl.release_identity import check, version_from_pyproject


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--sync', action='store_true')
    args = parser.parse_args()
    if args.sync:
        version = version_from_pyproject(ROOT)
        path = ROOT / 'mihomoctl/__init__.py'
        body, count = re.subn(r'^__version__ = [^\n]+$', "__version__ = %r" % version,
                             path.read_text(encoding='utf-8'), flags=re.M)
        if count != 1:
            parser.error('runtime-version-marker-missing-or-duplicate')
        path.write_text(body, encoding='utf-8')
        path = ROOT / 'release-manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['version'] = version
        path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        # Editorial version prose and Changelog are reviewed rather than rewritten.
    print('release identity: ' + check(ROOT, documents=not args.sync))


if __name__ == '__main__':
    main()
