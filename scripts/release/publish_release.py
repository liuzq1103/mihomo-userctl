#!/usr/bin/env python3
"""Deliver existing gated CI assets, with resumable draft and download verification."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.release.portable_policy import BASELINE, file_digest
from scripts.release.verify_release import verify

from mihomoctl.release_identity import source_stem, wheel_name, asset_names, distribution


def command(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True,
                            encoding='utf-8', check=True, timeout=600)
    return result.stdout


def api(repo, endpoint):
    return json.loads(command('gh', 'api', '--header', 'Cache-Control: no-cache',
                              'repos/' + repo + '/' + endpoint))


def create_draft(repo, tag, commit, notes):
    # The list endpoint may briefly omit a just-created draft. Retain the
    # creation response (including its numeric ID), rather than rediscover it.
    with tempfile.TemporaryDirectory(prefix='mihomoctl-draft-request-') as temporary:
        body = Path(temporary) / 'request.json'
        body.write_text(json.dumps({'tag_name': tag, 'target_commitish': commit,
                        'name': 'mihomoctl ' + tag, 'body': notes,
                        'draft': True, 'prerelease': False}), encoding='utf-8')
        return json.loads(command('gh', 'api', '--method', 'POST',
                                  'repos/' + repo + '/releases', '--input', body))


def validate_run(repo, run_id, commit):
    if not str(run_id).isdecimal() or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('invalid-run-identity')
    row = api(repo, 'actions/runs/' + str(run_id))
    if (row['repository']['full_name'] != repo or row['head_branch'] != 'main'
            or row['head_sha'] != commit or row['event'] != 'push'
            or row['status'] != 'completed' or row['conclusion'] != 'success'
            or row['path'] != '.github/workflows/test.yml'):
        raise ValueError('successful-main-test-run-required')


def find_release(repo, tag):
    found = []
    page = 1
    while True:
        rows = api(repo, 'releases?per_page=100&page=' + str(page))
        found.extend(row for row in rows if row['tag_name'] == tag)
        if len(rows) < 100:
            break
        page += 1
    if len(found) > 1:
        raise ValueError('multiple-release-records')
    return api(repo, 'releases/' + str(found[0]['id'])) if found else None


def check_existing_tag(repo, tag, commit, *, required=False):
    # Paginated matching refs handles a missing draft tag without hiding API errors.
    refs = json.loads(command('gh', 'api', '--paginate', '--slurp',
                             '--header', 'Cache-Control: no-cache',
                             'repos/' + repo + '/git/matching-refs/tags/' + tag))
    exact = [row for page in refs for row in page if row['ref'] == 'refs/tags/' + tag]
    if len(exact) > 1:
        raise ValueError('duplicate-tag')
    if required and not exact:
        raise ValueError('published-tag-missing')
    if exact:
        obj = exact[0]['object']
        for _ in range(8):
            if obj['type'] == 'commit':
                break
            if obj['type'] != 'tag':
                raise ValueError('invalid-tag-object')
            obj = api(repo, 'git/tags/' + obj['sha'])['object']
        if obj['type'] != 'commit' or obj['sha'] != commit:
            raise ValueError('existing-tag-commit-mismatch')


def assemble(download, output, commit, run_id, repo):
    c22, c24 = [download / ('release-candidate-ubuntu-' + osname) for osname in ('22.04', '24.04')]
    gate = json.loads((download / 'release-gate/release-gate.json').read_text())
    version = gate['version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version) or gate.get('commit') != commit or gate.get('verified') is not True:
        raise ValueError('gate-identity-mismatch')
    receipts = [json.loads((folder / 'build-receipt.json').read_text()) for folder in (c22, c24)]
    if any(receipts[0].get(k) != receipts[1].get(k) for k in ('commit', 'version', 'source_epoch', 'source', 'publishable')):
        raise ValueError('secondary-build-identity-mismatch')
    second = json.loads((download / 'validation-ubuntu-24.04/artifact-install.json').read_text())
    if receipts[1]['sha256'] != second.get('artifact_sha256'):
        raise ValueError('secondary-build-report-mismatch')
    portable_sum = source_stem(version) + '-portable-linux-x86_64.tar.gz.sha256'
    if (c22 / portable_sum).read_bytes() != (c24 / portable_sum).read_bytes():
        raise ValueError('secondary-portable-checksum-mismatch')
    assets = output / 'assets'
    assets.mkdir(parents=True, mode=0o700)
    for name in gate['assets']:
        if Path(name).name != name:
            raise ValueError('unsafe-asset-name')
        source = (c24 if '-offline-ubuntu24.04-' in name else c22) / name
        if not source.is_file() or source.is_symlink():
            raise ValueError('unsafe-or-missing-asset: ' + name)
        shutil.copyfile(source, assets / name)
    checked = verify(c22, download, commit, assets, c22)
    if checked != gate:
        raise ValueError('rechecked-gate-differs')
    shutil.copyfile(download / 'release-gate/release-gate.json', assets / 'release-gate.json')
    reports = {ubuntu: {p.stem: json.loads(p.read_text())
                       for p in (download / ('validation-ubuntu-' + ubuntu)).glob('*.json')}
               for ubuntu in ('22.04', '24.04')}
    expected = {'unit', 'real-core', 'privileged', 'artifact-install', 'offline-bundle-install',
                'release-acquisition', 'portable-acceptance'}
    if receipts[0].get('distribution') == 'mihomo-userctl':
        expected.add('python-install')
    for rows in reports.values():
        if set(rows) != expected or any(row.get('commit') != commit or row.get('success') is not True for row in rows.values()):
            raise ValueError('evidence-inventory-or-identity-mismatch')
    evidence = {'format': 1, 'version': version, 'commit': commit, 'reports': reports,
                'workflow_run': 'https://github.com/' + repo + '/actions/runs/' + str(run_id)}
    (assets / 'validation-evidence.json').write_text(json.dumps(evidence, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    notes = (ROOT / ('docs/release-' + version + '.md')).read_text(encoding='utf-8')
    def link(match):
        label, target = match.groups()
        if re.match(r'[A-Za-z][A-Za-z0-9+.-]*:', target) or target.startswith('#'):
            return match.group(0)
        local = (ROOT / 'docs' / target).resolve().relative_to(ROOT).as_posix()
        return '[' + label + '](https://github.com/' + repo + '/blob/v' + version + '/' + local + ')'
    notes = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, notes)
    notes += '\nValidated commit: `' + commit + '`. [CI run](' + evidence['workflow_run'] + ').\n\n'
    notes += '| Target | Download bytes | Expanded logical bytes | Installed logical bytes |\n| --- | ---: | ---: | ---: |\n'
    notes += '| v1.4.0 baseline | {bundle_bytes} | {expanded_bytes} | {installed_bytes} |\n'.format(**BASELINE)
    for ubuntu, rows in reports.items():
        portable = rows['portable-acceptance']
        notes += '| Ubuntu ' + ubuntu + ' | ' + str(portable['bundle_bytes']) + ' | ' + str(portable['expanded_bytes']) + ' | ' + str(max(row['installed_bytes'] for row in portable['users'])) + ' |\n'
    notes += '\nFull reports include both UIDs, real SSH, live-core 1.4.0 upgrades, observed 50ms disk peaks and physical allocation. Installation budgets exclude upgrade peaks.\n'
    (output / 'release-notes.md').write_text(notes, encoding='utf-8')
    inventory = {p.name: {'sha256': file_digest(p), 'bytes': p.stat().st_size} for p in sorted(assets.iterdir())}
    if set(inventory) != set(gate['assets']) | {'release-gate.json', 'validation-evidence.json'}:
        raise ValueError('publication-inventory-mismatch')
    (output / 'asset-inventory.json').write_text(json.dumps(inventory, indent=2, sort_keys=True) + '\n')
    return version, inventory


def download_verify(repo, tag, destination, inventory):
    destination.mkdir(mode=0o700)
    command('gh', 'release', 'download', tag, '--repo', repo, '--dir', destination)
    if {p.name for p in destination.iterdir()} != set(inventory):
        raise ValueError('downloaded-inventory-mismatch')
    for name, expected in inventory.items():
        path = destination / name
        if path.stat().st_size != expected['bytes'] or file_digest(path) != expected['sha256']:
            raise ValueError('downloaded-asset-mismatch: ' + name)


def deliver(repo, commit, version, output, inventory, publish):
    tag = 'v' + version
    check_existing_tag(repo, tag, commit)
    record = find_release(repo, tag)
    if record is None:
        record = create_draft(repo, tag, commit, (output / 'release-notes.md').read_text(encoding='utf-8'))
    if record['target_commitish'] != commit or record['prerelease'] is not False:
        raise ValueError('release-identity-mismatch')
    if not record['draft']:
        check_existing_tag(repo, tag, commit, required=True)
    notes = (output / 'release-notes.md').read_text(encoding='utf-8')
    title = 'mihomoctl ' + tag
    if (record.get('body') or '').rstrip() != notes.rstrip() or record.get('name') != title:
        if not record['draft']:
            raise ValueError('refuse-to-change-public-notes')
        command('gh', 'release', 'edit', tag, '--repo', repo, '--title', title, '--notes-file', output / 'release-notes.md')
        record = find_release(repo, tag)
        if (record.get('body') or '').rstrip() != notes.rstrip() or record.get('name') != title:
            raise ValueError('draft-notes-verification-failed')
    for asset in record['assets']:
        name = asset['name']
        if name not in inventory or asset.get('digest') != 'sha256:' + inventory[name]['sha256'] or asset['size'] != inventory[name]['bytes']:
            raise ValueError('existing-asset-mismatch')
    missing = set(inventory) - {row['name'] for row in record['assets']}
    if missing:
        if not record['draft']:
            raise ValueError('refuse-to-change-public-assets')
        command('gh', 'release', 'upload', tag, '--repo', repo,
                *[output / 'assets' / name for name in sorted(missing)])
    download_verify(repo, tag, output / 'draft-download', inventory)
    if publish:
        check_existing_tag(repo, tag, commit)
        if record['draft']:
            command('gh', 'release', 'edit', tag, '--repo', repo, '--draft=false', '--latest')
        record = find_release(repo, tag)
        check_existing_tag(repo, tag, commit, required=True)
        if record['draft'] or api(repo, 'releases/latest')['tag_name'] != tag:
            raise ValueError('public-release-not-latest')
        download_verify(repo, tag, output / 'published-download', inventory)
    return {'success': True, 'published': not record['draft'], 'tag': tag, 'commit': commit, 'url': record['html_url'],
            'downloaded_hashes_match': True}


def smoke_published(output, version):
    from mihomoctl.portable import source_tree
    archive = output / 'published-download' / (source_stem(version) + '-portable-linux-x86_64.tar.gz')
    previous = output / 'previous' / BASELINE['name']
    if file_digest(previous) != BASELINE['sha256']:
        raise ValueError('public-upgrade-baseline-mismatch')
    with tempfile.TemporaryDirectory(prefix='mihomoctl-public-upgrade-') as temporary, source_tree(archive) as bundle, source_tree(previous) as old:
        home = Path(temporary)
        env = dict(os.environ, HOME=str(home), MIHOMOCTL_NO_UPDATE_CHECK='1')
        tools = home / 'tools'
        tools.mkdir(mode=0o700)
        for name in ('dirname', 'readlink'):
            (tools / name).symlink_to('/usr/bin/' + name)
        env['PATH'] = str(tools)
        for key in ('CONFIG', 'DATA', 'STATE', 'CACHE', 'RUNTIME'):
            directory = home / key.lower()
            directory.mkdir(mode=0o700)
            env['XDG_' + key + ('_DIR' if key == 'RUNTIME' else '_HOME')] = str(directory)
        def run(*args):
            return subprocess.run(list(map(str, args)), env=env, check=True, capture_output=True, text=True, timeout=600).stdout
        discovery = json.loads(run(bundle / 'mihomoctl', 'release', 'check', '--json'))
        run(bundle / 'mihomoctl', 'release', 'fetch', '--version', 'v' + version, '--target', 'linux-x86_64', '--output-dir', home / 'acquired', '--json')
        acquisition = json.loads((home / 'acquired/acquisition.json').read_text())
        if acquisition['version'] != version or file_digest(home / 'acquired' / acquisition['source']) != file_digest(archive):
            raise ValueError('public-acquisition-mismatch')
        run(old / 'install.sh')
        launcher = home / '.local/bin/mihomoctl'
        run(launcher, 'update', '--latest', '--json')
        if json.loads(run(launcher, 'version', '--json'))['data']['mihomoctl'] != version:
            raise ValueError('public-latest-upgrade-failed')
        result = {'success': True, 'version': version, 'discovery': discovery,
                  'previous_version': BASELINE['version'], 'public_fetch_verified': True,
                  'public_update_latest_verified': True, 'host_python_absent_from_path': True}
        (output / 'delivered-smoke.json').write_text(json.dumps(result, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    repo = os.environ.get('GITHUB_REPOSITORY', 'liuzq1103/mihomo-userctl')
    commit = command('git', 'rev-parse', 'HEAD').strip()
    validate_run(repo, args.run_id, commit)
    if file_digest(args.output / 'previous' / BASELINE['name']) != BASELINE['sha256']:
        raise ValueError('publication-upgrade-baseline-mismatch')
    version, inventory = assemble(args.artifacts, args.output, commit, args.run_id, repo)
    result = deliver(repo, commit, version, args.output, inventory, args.publish)
    (args.output / 'publication-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    if args.publish:
        smoke_published(args.output, version)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
