#!/usr/bin/env python3
"""Assemble a target-specific offline kit from reviewed local release assets.

This command never downloads dependencies. Prepare the wheelhouse separately
with pip download --only-binary=:all: --require-hashes -r requirements-lock.txt.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.release import build_release
from scripts.release.verify_artifact_install import load_artifacts

TARGETS = {
    "ubuntu22.04-x86_64-py310": ("22.04", (3, 10), "2.35"),
    "ubuntu24.04-x86_64-py312": ("24.04", (3, 12), "2.39"),
}


def digest(path):
    with Path(path).open("rb") as stream:
        value = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
        return value.hexdigest()


def locked_dependencies(text):
    from mihomoctl.release_artifacts import locked_dependencies as shared
    return shared(text)


def target_environment(target):
    from mihomoctl.release_artifacts import target_environment as shared
    return shared(target)


def checked_payload(artifacts, wheelhouse, target, worktree=False):
    from mihomoctl.release_artifacts import checked_payload as shared
    return shared(artifacts, wheelhouse, target, worktree)


def build(artifacts, wheelhouse, target, output, worktree=False):
    artifacts, wheelhouse, output = map(Path, (artifacts, wheelhouse, output))
    receipt, dependencies = checked_payload(artifacts, wheelhouse, target, worktree)
    version = receipt["version"]
    root = "mihomoctl-" + version + "-offline-" + target
    output.mkdir(parents=True, exist_ok=True)
    bundle = output / (root + ".tar.gz")
    sums = output / (bundle.name + ".sha256")
    if bundle.exists() or sums.exists() or bundle.is_symlink() or sums.is_symlink():
        raise ValueError("offline-output-already-exists")
    # The exact normal-release assets and their checksum/receipt stay together.
    payload = {"release/" + name: (artifacts / name).read_bytes()
               for name in (*sorted(receipt["sha256"]), "SHA256SUMS", "build-receipt.json")}
    for name, expected in receipt["sha256"].items():
        if hashlib.sha256(payload["release/" + name]).hexdigest() != expected:
            raise ValueError("release-changed-during-bundle-build")
    for item in dependencies:
        payload[item["file"]] = (wheelhouse / PurePosixPath(item["file"]).name).read_bytes()
        if hashlib.sha256(payload[item["file"]]).hexdigest() != item["sha256"]:
            raise ValueError("dependency-changed-during-bundle-build")
    payload["README.txt"] = (
        "mihomoctl offline control-plane kit\n"
        "Verify the outer digest against an independently trusted release record BEFORE running code.\n"
        "Safely extract into a new private directory, then run sha256sum --check --strict SHA256SUMS.\n"
        "Extract and review release/mihomoctl-%s.tar.gz; read INSTALL.md and docs/en/offline-install.md.\n"
        "Run bash install.sh --python /usr/bin/python3 --wheelhouse /ABSOLUTE/KIT/wheelhouse --dry-run,\n"
        "then repeat without --dry-run. Installation never downloads dependencies or starts services.\n"
        "Mihomo, OpenCode, Codex and Node are not included; prepare/install them yourself.\n"
        "The enclosed receipt/checksums alone do not independently authenticate the source.\n" % version
    ).encode()
    provenance = {"format": 1, "version": version, "commit": receipt["commit"], "target": target,
                  "source": receipt["source"], "publishable": receipt["publishable"],
                  "dependencies": dependencies,
                  "files": {name: hashlib.sha256(body).hexdigest() for name, body in sorted(payload.items())}}
    payload["bundle-manifest.json"] = (json.dumps(provenance, indent=2, sort_keys=True) + "\n").encode()
    payload["SHA256SUMS"] = "".join(hashlib.sha256(body).hexdigest() + "  " + name + "\n"
                                      for name, body in sorted(payload.items())).encode()
    epoch = receipt.get("source_epoch", 0)
    created_bundle = created_sums = False
    try:
        with bundle.open("xb") as raw:
            created_bundle = True
            with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
                with tarfile.open(fileobj=compressed, mode="w") as archive:
                    for name, body in sorted(payload.items()):
                        info = tarfile.TarInfo(root + "/" + name)
                        info.size, info.mtime, info.mode = len(body), epoch, 0o644
                        archive.addfile(info, io.BytesIO(body))
        with sums.open("x", encoding="utf-8") as stream:
            created_sums = True
            stream.write(digest(bundle) + "  " + bundle.name + "\n")
    except BaseException:
        if created_bundle:
            bundle.unlink(missing_ok=True)
        if created_sums:
            sums.unlink(missing_ok=True)
        raise
    return {"version": version, "commit": receipt["commit"], "target": target,
            "file": bundle.name, "sha256": digest(bundle), "publishable": receipt["publishable"]}


def main(argv=None):
    from mihomoctl.errors import MihomoctlError
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worktree", action="store_true", help="development only; never publishable")
    args = parser.parse_args(argv)
    previous = os.umask(0o077)
    try:
        result = build(args.artifacts, args.wheelhouse, args.target, args.output, args.worktree)
    except (ValueError, OSError, zipfile.BadZipFile, MihomoctlError) as error:
        parser.exit(1, "offline bundle blocked: " + str(error) + "\n")
    finally:
        os.umask(previous)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
