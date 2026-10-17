#!/usr/bin/env python3
"""Validate a complete local offline kit and exercise it in a network namespace.

The adjacent .sha256 is a transport check; obtain the expected digest through
a trusted independent channel before running any program from a received kit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import socket
import sys
import tarfile
import tempfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release.build_offline_bundle import TARGETS, checked_payload, digest
from scripts.release.verify_artifact_install import MAX_BYTES, MAX_MEMBERS, VerificationError, verify_case


def load_bundle(path, target, worktree=False):
    from mihomoctl.release_artifacts import load_bundle as shared
    try:
        return shared(path, target, worktree)
    except ValueError as error:
        raise VerificationError(str(error)) from None


def verify(path, target, python, worktree=False):
    from mihomoctl.installation import interpreter_target
    environment = interpreter_target(python)
    release = platform.freedesktop_os_release()
    ubuntu, version, _ = TARGETS[target]
    if (release.get("ID") != "ubuntu" or release.get("VERSION_ID") != ubuntu
            or environment["machine"] != "x86_64" or tuple(environment["version"][:2]) != version
            or environment["implementation"] != "cpython"):
        raise VerificationError("offline-acceptance-target-mismatch")
    # A namespace with no external interfaces provides actual network denial,
    # unlike PIP_NO_INDEX, which only affects pip's package index.
    if sys.platform != "linux" or os.geteuid() == 0 or {name for _, name in socket.if_nameindex()} != {"lo"}:
        raise VerificationError("non-root-isolated-network-namespace-required")
    original_digest = digest(path)
    manifest, payload = load_bundle(path, target, worktree)
    cases = []
    with tempfile.TemporaryDirectory(prefix="mihomoctl-offline-acceptance-") as directory:
        base = Path(directory)
        base.chmod(0o700)
        for name, body in payload.items():
            destination = base / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(body)
            destination.chmod(0o600)
        receipt, dependencies = checked_payload(base / "release", base / "wheelhouse", target, worktree)
        if dependencies != manifest["dependencies"] or receipt["commit"] != manifest["commit"]:
            raise VerificationError("offline-bundle-dependency-provenance-mismatch")
        for kind in ("tar.gz", "zip", "wheel"):
            cases.append(verify_case(kind, base / "release", base / "wheelhouse", python, manifest["version"]))
    # Bind the report to the exact kit used, including its dependency payload.
    final_manifest, _ = load_bundle(path, target, worktree)
    if final_manifest != manifest or digest(path) != original_digest:
        raise VerificationError("offline-bundle-changed-during-acceptance")
    return {"success": True, "publishable_acceptance": manifest["publishable"] and not worktree,
            "commit": manifest["commit"], "version": manifest["version"], "target": target,
            "source_dirty": not manifest["publishable"], "network_isolated": True,
            "bundle_sha256": original_digest, "bundle_file": Path(path).name,
            "tests": len(cases), "skipped": 0, "failures": 0, "errors": 0, "cases": cases}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--python", type=Path, default=Path(sys.executable))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--worktree", action="store_true")
    args = parser.parse_args(argv)
    report = {"success": False, "publishable_acceptance": False, "tests": 0, "skipped": 0}
    try:
        report = verify(args.bundle.absolute(), args.target, args.python.absolute(), args.worktree)
    except Exception as error:
        report.update(errors=1, error=str(error) if isinstance(error, (VerificationError, ValueError)) else type(error).__name__)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.report)
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
