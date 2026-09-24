#!/usr/bin/env python3
"""Install reviewed local Linux archives. No downloader or package-manager hooks."""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import sys
import tarfile
import tempfile

MAX_BYTES = 2 * 1024 ** 3
MAX_MEMBERS = 100000
TOOLS = {"mihomo", "node", "codex", "opencode"}
COMMANDS = {"mihomo": {"mihomo"}, "node": {"node", "npm", "npx"},
            "codex": {"codex"}, "opencode": {"opencode"}}


class OfflineError(Exception):
    pass


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise OfflineError("invalid relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or ".." in p.parts or not p.parts:
        raise OfflineError("unsafe relative path: " + value)
    return Path(*p.parts)


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load_packages(manifest, names, machine=None):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or data.get("format") != 1
            or not isinstance(data.get("packages"), list)
            or any(not isinstance(p, dict) for p in data["packages"])):
        raise OfflineError("unsupported manifest")
    machine = machine or platform.machine()
    arch = {"amd64": "x86_64", "aarch64": "arm64"}.get(machine, machine)
    selected = []
    for name in names:
        matches = [p for p in data["packages"]
                   if p.get("name") == name and p.get("arch") == arch]
        if len(matches) != 1:
            raise OfflineError("need exactly one manifest entry for " + name + "/" + arch)
        p = matches[0]
        if not re.fullmatch(r"[0-9a-f]{64}", p.get("sha256", "")):
            raise OfflineError("missing pinned SHA256: " + name)
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+", p.get("version", "")):
            raise OfflineError("invalid version: " + name)
        if p.get("archive") not in ("gzip", "tar"):
            raise OfflineError("unsupported archive: " + name)
        if not isinstance(p.get("commands"), dict) or set(p["commands"]) != COMMANDS[name]:
            raise OfflineError("invalid command mapping: " + name)
        relative(p["file"])
        for value in p["commands"].values():
            relative(value)
        selected.append(p)
    return selected


def package_path(bundle, package):
    source = bundle / relative(package["file"])
    if source.is_symlink() or not source.is_file():
        raise OfflineError("missing regular package: " + str(source))
    if bundle.resolve() not in source.resolve().parents:
        raise OfflineError("package escapes bundle directory")
    if source.stat().st_size > MAX_BYTES:
        raise OfflineError("package exceeds size limit")
    return source


def verify(path, package):
    if digest(path) != package["sha256"]:
        raise OfflineError("SHA256 mismatch: " + package["file"])


def copy_bounded(source, destination, remaining):
    count = 0
    with destination.open("xb") as output:
        while True:
            block = source.read(min(1024 * 1024, remaining - count + 1))
            if not block:
                break
            count += len(block)
            if count > remaining:
                raise OfflineError("expanded archive exceeds size limit")
            output.write(block)
    return count


def extract(archive, target, package):
    target.mkdir(mode=0o700)
    if package["archive"] == "gzip":
        if set(package["commands"]) != {"mihomo"}:
            raise OfflineError("single gzip is only supported for Mihomo")
        output = target / relative(package["commands"]["mihomo"])
        output.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(archive, "rb") as source:
            copy_bounded(source, output, MAX_BYTES)
        output.chmod(0o755)
    else:
        used, seen, links = 0, set(), []
        # Extract regular files first; never follow archive links while writing.
        with tarfile.open(archive, "r:*") as tf:
            for index, member in enumerate(tf):
                if index >= MAX_MEMBERS:
                    raise OfflineError("too many archive members")
                if member.name in (".", "./") and member.isdir():
                    continue
                rel = relative(member.name)
                if rel in seen:
                    raise OfflineError("duplicate archive path")
                seen.add(rel)
                output = target / rel
                if member.isdir():
                    output.mkdir(parents=True, exist_ok=True)
                elif member.isfile():
                    if member.size > MAX_BYTES - used:
                        raise OfflineError("expanded archive exceeds size limit")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    with tf.extractfile(member) as source:
                        used += copy_bounded(source, output, MAX_BYTES - used)
                    output.chmod(0o755 if member.mode & 0o111 else 0o644)
                elif member.issym():
                    links.append((output, member.linkname))
                else:
                    raise OfflineError("unsupported archive member (including hard links)")
        for output, link in links:
            if not link or "\\" in link or ":" in link or PurePosixPath(link).is_absolute():
                raise OfflineError("unsafe archive link")
            resolved = (output.parent / link).resolve()
            if target.resolve() not in resolved.parents or not resolved.is_file():
                raise OfflineError("archive link must point to an internal regular file")
            output.parent.mkdir(parents=True, exist_ok=True)
            output.symlink_to(link)
    for command, rel in package["commands"].items():
        executable = target / relative(rel)
        if not executable.is_file() or target.resolve() not in executable.resolve().parents:
            raise OfflineError("missing executable: " + command)
        if not executable.stat().st_mode & 0o111:
            raise OfflineError("archive executable bit missing: " + command)


def private_directory(path):
    """Reject redirected, foreign-owned or writable-by-others install paths."""
    if ".." in path.parts or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
        raise OfflineError("invalid installation path")
    for part in reversed([path] + list(path.parents)):
        if part.is_symlink():
            raise OfflineError("symlink in installation path: " + str(part))
        if part.exists():
            info = part.stat()
            if not stat.S_ISDIR(info.st_mode):
                raise OfflineError("not a directory: " + str(part))
            # System-owned ancestors are allowed; writable shared ancestors are not.
            if info.st_mode & 0o022 and not (info.st_uid == 0 and info.st_mode & stat.S_ISVTX):
                raise OfflineError("unsafe writable installation ancestor: " + str(part))
    if path.exists() and path.stat().st_uid != os.getuid():
        raise OfflineError("installation directory is not owned by current user")


def install(bundle, packages, home):
    home = home.absolute()
    bin_dir = home / ".local/bin"
    store = home / ".local/share/mihomo-userctl-offline"
    for path in (home, bin_dir, store):
        private_directory(path)
    commands = [name for p in packages for name in p["commands"]]
    for name in commands:
        if os.path.lexists(bin_dir / name):
            raise OfflineError("existing command preserved; review before replacing: " + str(bin_dir / name))
    store.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix="install-", dir=str(store)))
    created = []
    try:
        for package in packages:
            archive = stage / (package["name"] + ".archive")
            # Verify the private copy, not a shared file subsequently reopened.
            with package_path(bundle, package).open("rb") as source:
                copy_bounded(source, archive, MAX_BYTES)
            verify(archive, package)
            extract(archive, stage / package["name"], package)
            archive.unlink()
        receipt = {"format": 1, "packages": packages, "links": {}}
        for p in packages:
            for name, rel in p["commands"].items():
                receipt["links"][str(bin_dir / name)] = str(stage / p["name"] / rel)
        (stage / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
        bin_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        for link, target in receipt["links"].items():
            path = Path(link)
            # Exclusive creation also handles another installer winning the race.
            path.symlink_to(target)
            created.append((path, target))
        return stage / "receipt.json"
    except BaseException:
        for path, target in reversed(created):
            if path.is_symlink() and os.readlink(path) == target:
                path.unlink()
        shutil.rmtree(stage)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "install"))
    parser.add_argument("--bundle-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--packages", nargs="+", choices=sorted(TOOLS), required=True)
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux":
            raise OfflineError("run on the target Linux account")
        if len(set(args.packages)) != len(args.packages):
            raise OfflineError("duplicate package selection")
        packages = load_packages(args.manifest, args.packages)
        for p in packages:
            verify(package_path(args.bundle_dir, p), p)
            print("SHA256 OK: {} {} {}".format(p["name"], p["version"], p["arch"]))
        if args.action == "install":
            receipt = install(args.bundle_dir, packages, Path.home())
            print("Installed; receipt: " + str(receipt))
            print("Use PATH=$HOME/.local/bin:$PATH in this shell. Runtime checks remain required.")
        else:
            print("Archive bytes verified only; no extraction, runtime or upstream-signature validation.")
        return 0
    except (OfflineError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, EOFError) as exc:
        print("offline-install: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
