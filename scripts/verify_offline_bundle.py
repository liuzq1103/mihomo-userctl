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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_offline_bundle import TARGETS, checked_payload, digest
from scripts.verify_artifact_install import MAX_BYTES, MAX_MEMBERS, VerificationError, verify_case


def load_bundle(path, target, worktree=False):
    """Read bounded regular files and verify every byte before extracting code."""
    path = Path(path)
    if target not in TARGETS or path.is_symlink() or not path.is_file():
        raise VerificationError("offline-bundle-missing-or-invalid-target")
    expected = digest(path) + "  " + path.name + "\n"
    sidecar = path.with_name(path.name + ".sha256")
    if sidecar.is_symlink() or not sidecar.is_file() or sidecar.read_text(encoding="utf-8") != expected:
        raise VerificationError("offline-bundle-checksum-missing-or-mismatched")
    payload = {}
    root = None
    used = 0
    with tarfile.open(path, "r:gz") as archive:
        for index, member in enumerate(archive):
            parts = member.name.split("/")
            if (index >= MAX_MEMBERS or not member.isfile() or len(parts) < 2
                    or any(p in ("", ".", "..") for p in parts)
                    or "\\" in member.name or ":" in member.name
                    or any(ord(c) < 32 or ord(c) == 127 for c in member.name)):
                raise VerificationError("unsafe-offline-bundle-member")
            if root is None:
                root = parts[0]
            name = "/".join(parts[1:])
            if parts[0] != root or name in payload:
                raise VerificationError("duplicate-or-ambiguous-offline-bundle-member")
            used += member.size
            if member.size < 0 or used > MAX_BYTES:
                raise VerificationError("offline-bundle-size-limit")
            body = archive.extractfile(member).read(member.size + 1)
            if len(body) != member.size:
                raise VerificationError("truncated-offline-bundle")
            payload[name] = body
    try:
        manifest = json.loads(payload["bundle-manifest.json"])
        version, commit = manifest["version"], manifest["commit"]
        if (manifest["format"] != 1 or manifest["target"] != target
                or not re.fullmatch(r"\d+\.\d+\.\d+", version)
                or not re.fullmatch(r"[a-f0-9]{40}", commit)
                or root != "mihomoctl-" + version + "-offline-" + target
                or path.name != root + ".tar.gz"):
            raise ValueError()
        if (manifest["source"], manifest["publishable"]) not in (
                ("git-commit", True), ("worktree", False)) or (not manifest["publishable"] and not worktree):
            raise ValueError()
        files = manifest["files"]
        if not isinstance(files, dict) or set(files) != set(payload) - {"SHA256SUMS", "bundle-manifest.json"}:
            raise ValueError()
        if any(hashlib.sha256(payload[name]).hexdigest() != value for name, value in files.items()):
            raise ValueError()
        sums = "".join(hashlib.sha256(body).hexdigest() + "  " + name + "\n"
                       for name, body in sorted(payload.items()) if name != "SHA256SUMS").encode()
        if payload["SHA256SUMS"] != sums:
            raise ValueError()
        receipt = json.loads(payload["release/build-receipt.json"])
        if any(receipt[key] != manifest[key] for key in ("version", "commit", "source", "publishable")):
            raise ValueError()
        if any(hashlib.sha256(payload["release/" + name]).hexdigest() != value
               for name, value in receipt["sha256"].items()):
            raise ValueError()
        release_sums = "".join(receipt["sha256"][name] + "  " + name + "\n"
                               for name in sorted(receipt["sha256"])).encode()
        if payload["release/SHA256SUMS"] != release_sums:
            raise ValueError()
        dependencies = manifest["dependencies"]
        dependency_files = {entry["file"] for entry in dependencies}
        if len(dependency_files) != len(dependencies) or any(
                not entry["file"].startswith("wheelhouse/")
                or len(PurePosixPath(entry["file"]).parts) != 2
                or not entry["file"].endswith(".whl")
                or files[entry["file"]] != entry["sha256"] for entry in dependencies):
            raise ValueError()
        required = {"release/" + name for name in receipt["sha256"]} | {
            "release/SHA256SUMS", "release/build-receipt.json", "README.txt"} | dependency_files
        if set(files) != required:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise VerificationError("offline-bundle-manifest-or-internal-checksum-mismatch") from None
    return manifest, payload


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
