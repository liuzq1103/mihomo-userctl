#!/usr/bin/env python3
"""Require exact-commit artifacts and both Ubuntu acceptance reports before publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import re

if __package__ in (None, ""):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.verify_offline_bundle import load_bundle
from scripts.release.portable_policy import BASELINE, MAX_DOWNLOAD, MAX_EXPANDED, MAX_INSTALLED


class GateError(ValueError):
    pass

from mihomoctl.release_identity import source_stem, wheel_name, asset_names, distribution


def document(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateError("missing-or-invalid-evidence: " + path.name) from None
    if not isinstance(value, dict):
        raise GateError("invalid-evidence-object: " + path.name)
    return value


def verify(artifacts, evidence, commit, offline_artifacts=None, portable_artifacts=None):
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise GateError("expected-full-git-commit")
    receipt = document(artifacts / "build-receipt.json")
    if (receipt.get("commit") != commit or receipt.get("publishable") is not True
            or receipt.get("source") != "git-commit"):
        raise GateError("build-is-not-publishable-for-expected-commit")
    # The published version is whatever the exact-commit build actually produced;
    # the gate follows the receipt instead of a second hard-coded literal.
    version = receipt.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-.][0-9A-Za-z.]+)?", version):
        raise GateError("build-receipt-version-invalid")
    hashes = receipt.get("sha256")
    wheels = list(artifacts.glob(wheel_name(version, distribution(receipt))))
    if len(wheels) != 1:
        raise GateError("exactly-one-versioned-wheel-required")
    names = asset_names(version, distribution(receipt))
    if not isinstance(hashes, dict) or set(hashes) != names:
        raise GateError("release-asset-inventory-mismatch")
    for name, digest in hashes.items():
        path = artifacts / name
        if (path.is_symlink() or not path.is_file() or not re.fullmatch(r"[0-9a-f]{64}", str(digest))
                or hashlib.sha256(path.read_bytes()).hexdigest() != digest):
            raise GateError("release-asset-digest-mismatch: " + name)
    try:
        actual_sums = (artifacts / "SHA256SUMS").read_text(encoding="utf-8")
    except OSError:
        raise GateError("release-checksums-missing") from None
    expected_sums = "".join(hashes[n] + "  " + n + "\n" for n in sorted(names))
    if actual_sums != expected_sums:
        raise GateError("release-checksum-inventory-mismatch")
    core_digests = set()
    installed_artifact_sets = []
    offline_assets = []
    for ubuntu in ("22.04", "24.04"):
        folder = evidence / ("validation-ubuntu-" + ubuntu)
        acquisition = document(folder / 'release-acquisition.json')
        if (acquisition.get('commit') != commit or acquisition.get('source_dirty') is not False
                or acquisition.get('network_isolated') is not True
                or acquisition.get('success') is not True or acquisition.get('skipped') != 0
                or acquisition.get('failures') != 0 or acquisition.get('errors') != 0
                or type(acquisition.get('tests')) is not int or acquisition['tests'] < 26
                or any(acquisition.get('suites', {}).get(name, 0) < count for name, count in
                       (('test_v1_release.py', 14), ('test_v1_release_fetch.py', 12)))):
            raise GateError('release-acquisition-acceptance-incomplete: ' + ubuntu)
        installation = document(folder / "artifact-install.json")
        if (installation.get("commit") != commit or installation.get("publishable_acceptance") is not True
                or installation.get("success") is not True or installation.get("tests") != 4
                or installation.get("skipped") != 0):
            raise GateError("full-artifact-installation-incomplete: " + ubuntu)
        upgrade = installation.get('previous_upgrade', {})
        if (upgrade.get('result') != 'PASS' or upgrade.get('version') != version
                or not re.fullmatch(r'1\.0\.\d+', upgrade.get('previous_version', ''))
                or upgrade.get('no_history') is not True
                or upgrade.get('protected_files_unchanged') is not True):
            raise GateError('previous-version-upgrade-incomplete: ' + ubuntu)
        tested_hashes = installation.get("artifact_sha256")
        if not isinstance(tested_hashes, dict) or set(tested_hashes) != names:
            raise GateError("installed-artifact-inventory-mismatch: " + ubuntu)
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in tested_hashes.values()):
            raise GateError("installed-artifact-digest-invalid: " + ubuntu)
        for name in sorted(n for n in names if not n.endswith(".whl")):
            if tested_hashes[name] != hashes[name]:
                raise GateError("installed-source-artifact-differs: " + ubuntu)
        installed_artifact_sets.append(tested_hashes)
        if distribution(receipt) == 'mihomo-userctl':
            python_install = document(folder / 'python-install.json')
            users = python_install.get('users', [])
            required_cases = {'uv-tool', 'pipx', 'pip-user', 'wheel', 'sdist', 'source', 'editable', 'index', 'tui-extra'}
            if (python_install.get('commit') != commit or python_install.get('version') != version
                    or python_install.get('success') is not True or python_install.get('network_isolated') is not True
                    or python_install.get('source_dirty') is not False or python_install.get('ubuntu') != ubuntu
                    or python_install.get('artifact_sha256') != hashes or len(users) != 2
                    or len({row.get('uid') for row in users}) != 2
                    or any(row.get('success') is not True or row.get('protected_files_unchanged') is not True
                           or row.get('external_update_refused') is not True or set(row.get('cases', [])) != required_cases
                           or ubuntu == '24.04' and row.get('pep668') != 'refused'
                           for row in users)):
                raise GateError('python-install-acceptance-incomplete: ' + ubuntu)
        target = "ubuntu" + ubuntu + "-x86_64-py" + ("310" if ubuntu == "22.04" else "312")
        bundle_name = source_stem(version) + "-offline-" + target + ".tar.gz"
        bundle_path = (offline_artifacts or artifacts) / bundle_name
        try:
            bundle, _ = load_bundle(bundle_path, target)
        except (ValueError, OSError) as error:
            raise GateError("offline-bundle-invalid: " + target + ": " + str(error)) from None
        offline = document(folder / "offline-bundle-install.json")
        if (bundle["commit"] != commit or bundle["version"] != version
                or offline.get("commit") != commit or offline.get("version") != version
                or offline.get("target") != target or offline.get("bundle_file") != bundle_name
                or offline.get("bundle_sha256") != hashlib.sha256(bundle_path.read_bytes()).hexdigest()
                or offline.get("publishable_acceptance") is not True
                or offline.get("success") is not True or offline.get("source_dirty") is not False
                or offline.get("network_isolated") is not True or offline.get("tests") != 3
                or offline.get("skipped") != 0 or offline.get("errors") != 0 or offline.get("failures") != 0):
            raise GateError("offline-bundle-acceptance-incomplete: " + target)
        if any(bundle["files"].get("release/" + name) != value for name, value in tested_hashes.items()):
            raise GateError("offline-bundle-release-assets-differ: " + target)
        offline_assets.extend([bundle_name, bundle_name + ".sha256"])
        for suite in ("unit", "real-core", "privileged"):
            report = document(folder / (suite + ".json"))
            if (report.get("commit") != commit or report.get("source_dirty") is not False
                    or report.get("os") != "ubuntu" or report.get("ubuntu") != ubuntu
                    or report.get("success") is not True
                    or report.get("failures") != 0 or report.get("errors") != 0
                    or type(report.get("tests")) is not int or report["tests"] <= 0):
                raise GateError("acceptance-not-passed-for-commit: " + ubuntu + "/" + suite)
            if suite != "unit":
                minimum = 8 if suite == "real-core" else 6
                if report.get("skipped") != 0 or report["tests"] < minimum:
                    raise GateError("mandatory-acceptance-incomplete: " + ubuntu + "/" + suite)
                digest = report.get("core_sha256", "")
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise GateError("core-identity-evidence-missing")
                core_digests.add(digest)
            if suite == "real-core":
                groups = report.get("suites", {})
                if any(type(groups.get(name)) is not int or groups[name] < minimum
                       for name, minimum in (("test_real_core.py", 3), ("test_v1_runtime_real.py", 6),
                                             ("test_v1_ux.py", 1))):
                    raise GateError("required-real-core-suite-missing")
            if suite == "privileged" and any(report.get(key) is not True
                                             for key in ("real_uids", "systemd", "tun")):
                raise GateError("mandatory-platform-evidence-missing")
    if hashes not in installed_artifact_sets:
        raise GateError("selected-release-assets-were-not-installed")
    if len(core_digests) != 1:
        raise GateError("tested-core-differs-between-acceptance-environments")
    portable_assets = set()
    if portable_artifacts is not None:
        name = source_stem(version) + '-portable-linux-x86_64.tar.gz'
        archive = portable_artifacts / name
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if archive.stat().st_size > MAX_DOWNLOAD:
            raise GateError('portable-download-budget-exceeded')
        if (portable_artifacts / (name + '.sha256')).read_text().strip() != digest + '  ' + name:
            raise GateError('portable-checksum-mismatch')
        for ubuntu in ('22.04', '24.04'):
            report = document(evidence / ('validation-ubuntu-' + ubuntu) / 'portable-acceptance.json')
            if (type(report.get('bundle_bytes')) is not int or report['bundle_bytes'] != archive.stat().st_size
                    or type(report.get('expanded_bytes')) is not int or not 0 < report['expanded_bytes'] <= MAX_EXPANDED
                    or report.get('baseline') != BASELINE):
                raise GateError('portable-size-evidence-invalid: ' + ubuntu)
            for row in report.get('users', []):
                upgrade = row.get('previous_upgrade', {})
                if (type(row.get('installed_bytes')) is not int or not 0 < row['installed_bytes'] <= MAX_INSTALLED
                        or upgrade.get('previous_version') != BASELINE['version']
                        or upgrade.get('previous_commit') != BASELINE['commit']
                        or upgrade.get('previous_bundle_sha256') != BASELINE['sha256']
                        or upgrade.get('version') != version
                        or any(upgrade.get(key) is not True for key in ('success', 'core_identity_unchanged',
                            'core_digest_unchanged', 'authentication_preserved', 'selection_preserved',
                            'protected_files_unchanged', 'no_history'))):
                    raise GateError('portable-previous-upgrade-incomplete: ' + ubuntu)
            users = report.get('users', [])
            if (report.get('success') is not True or report.get('network_isolated') is not True
                    or report.get('os') != 'ubuntu' or report.get('ubuntu') != ubuntu
                    or report.get('real_uids') is not True or report.get('publishable') is not True
                    or report.get('commit') != commit or report.get('version') != version
                    or report.get('bundle_sha256') != digest or not isinstance(users, list) or len(users) != 2
                    or any(not isinstance(row, dict) for row in users)
                    or any(type(row.get('uid')) is not int or row['uid'] <= 0 for row in users)
                    or len({row['uid'] for row in users}) != 2
                    or len({row.get('controller_port') for row in users}) != 2
                    or any(row.get('core_sha256') not in core_digests for row in users)
                    or not any(row.get('ssh_transport') is True for row in users)
                    or any(row.get('no_history') is not True or row.get('authentication_rejected') is not True
                           or row.get('system_python_absent_from_path') is not True
                           or row.get('active_ui_update_refused') is not True
                           or row.get('terminal_unicode_resize_search') is not True
                           or row.get('extraction_umask_0002') is not True
                           or row.get('ui_rss_kib', 0) <= 0 for row in report['users'])):
                raise GateError('portable-acceptance-incomplete: ' + ubuntu)
        portable_assets = {name, name + '.sha256'}
    return {"commit": commit, "version": version,
            "assets": sorted(names | set(offline_assets) | portable_assets | {"SHA256SUMS", "build-receipt.json"}),
            "ubuntu": ["22.04", "24.04"], "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--offline-artifacts", type=Path,
                        help="both target kits and .sha256 sidecars (default: --artifacts)")
    parser.add_argument('--portable-artifacts', type=Path,
                        help='complete portable bundle and checksum (default: --artifacts)')
    args = parser.parse_args()
    try:
        result = verify(args.artifacts, args.evidence, args.commit, args.offline_artifacts,
                        args.portable_artifacts or args.artifacts)
    except GateError as error:
        print("release blocked: " + str(error))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
