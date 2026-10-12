#!/usr/bin/env python3
"""Require exact-commit artifacts and both Ubuntu acceptance reports before publishing."""
import argparse
import hashlib
import json
from pathlib import Path
import re


class GateError(ValueError):
    pass


def document(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise GateError("missing-or-invalid-evidence: " + path.name) from None
    if not isinstance(value, dict):
        raise GateError("invalid-evidence-object: " + path.name)
    return value


def verify(artifacts, evidence, commit):
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
    wheels = list(artifacts.glob("mihomoctl-" + version + "-*.whl"))
    if len(wheels) != 1:
        raise GateError("exactly-one-versioned-wheel-required")
    names = {"mihomoctl-" + version + ".tar.gz", "mihomoctl-" + version + ".zip", wheels[0].name}
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
    for ubuntu in ("22.04", "24.04"):
        folder = evidence / ("validation-ubuntu-" + ubuntu)
        installation = document(folder / "artifact-install.json")
        if (installation.get("commit") != commit or installation.get("publishable_acceptance") is not True
                or installation.get("success") is not True or installation.get("tests") != 3
                or installation.get("skipped") != 0):
            raise GateError("full-artifact-installation-incomplete: " + ubuntu)
        tested_hashes = installation.get("artifact_sha256")
        if not isinstance(tested_hashes, dict) or set(tested_hashes) != names:
            raise GateError("installed-artifact-inventory-mismatch: " + ubuntu)
        if any(not re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in tested_hashes.values()):
            raise GateError("installed-artifact-digest-invalid: " + ubuntu)
        for name in sorted(n for n in names if not n.endswith(".whl")):
            if tested_hashes[name] != hashes[name]:
                raise GateError("installed-source-artifact-differs: " + ubuntu)
        installed_artifact_sets.append(tested_hashes)
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
    return {"commit": commit, "version": version, "assets": sorted(names),
            "ubuntu": ["22.04", "24.04"], "verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args()
    try:
        result = verify(args.artifacts, args.evidence, args.commit)
    except GateError as error:
        print("release blocked: " + str(error))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
