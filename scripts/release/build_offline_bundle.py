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
    """Read the deliberately small, hash-pinned dependency lock surface."""
    joined = " ".join(line.split("#", 1)[0].rstrip().removesuffix("\\")
                      for line in text.splitlines())
    tokens = joined.split()
    locked = {}
    current = None
    for token in tokens:
        requirement = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([0-9][A-Za-z0-9.]*)", token)
        pin = re.fullmatch(r"--hash=sha256:([a-f0-9]{64})", token)
        if requirement:
            name = re.sub(r"[-_.]+", "-", requirement[1]).lower()
            if name in locked:
                raise ValueError("duplicate-locked-dependency")
            current = {"version": requirement[2], "sha256": set()}
            locked[name] = current
        elif pin and current is not None:
            current["sha256"].add(pin[1])
        else:
            raise ValueError("unsupported-dependency-lock")
    if not locked or any(not value["sha256"] for value in locked.values()):
        raise ValueError("dependency-lock-requires-hashes")
    return locked


def target_environment(target):
    if target not in TARGETS:
        raise ValueError("unsupported-offline-target")
    _, version, glibc = TARGETS[target]
    return {"os": "linux", "version": [*version, 0], "implementation": "cpython",
            "machine": "x86_64", "libc": ["glibc", glibc]}


def checked_payload(artifacts, wheelhouse, target, worktree=False):
    from mihomoctl import installation
    receipt, _ = load_artifacts(artifacts, worktree)
    version = receipt["version"]
    source_name = "mihomoctl-" + version
    with zipfile.ZipFile(artifacts / (source_name + ".zip")) as archive:
        manifest = json.loads(archive.read(source_name + "/release-manifest.json"))
        lock = locked_dependencies(archive.read(source_name + "/requirements-lock.txt").decode("utf-8"))
    if manifest["version"] != version:
        raise ValueError("bundle-source-version-mismatch")
    for suffix in (".zip", ".tar.gz"):
        build_release.verify_source_inventory(artifacts / (source_name + suffix), manifest)
    project_wheel = artifacts / (source_name + "-py3-none-any.whl")
    build_release.verify_wheel_inventory(project_wheel, manifest)
    environment = target_environment(target)
    selected = installation.resolve_dependency_wheels(manifest["dependencies"], wheelhouse, environment)
    if set(lock) != {item["name"] for item in selected}:
        raise ValueError("wheelhouse-differs-from-dependency-lock")
    dependencies = []
    for item in selected:
        path = item["path"]
        if path.is_symlink() or not path.is_file():
            raise ValueError("unsafe-dependency-wheel")
        pin = lock[item["name"]]
        actual = digest(path)
        if pin["version"] != item["version"] or actual not in pin["sha256"]:
            raise ValueError("dependency-lock-digest-mismatch: " + path.name)
        dependencies.append({"name": item["name"], "version": item["version"],
                             "file": "wheelhouse/" + path.name, "sha256": actual})
    return receipt, dependencies


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
