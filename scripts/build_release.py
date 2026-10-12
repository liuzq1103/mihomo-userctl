#!/usr/bin/env python3
"""Build reviewed source archives, a wheel and checksums from one Git commit."""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
# Single source of truth for the release identity: the reviewed manifest that is
# shipped in the archive. Every artifact name below is derived from it, so a
# version bump never needs a second edit here.
ROOT_MANIFEST = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
VERSION = ROOT_MANIFEST["version"]


@contextlib.contextmanager
def private_creation_mask():
    """Keep builder-created staging paths private, including child build tools."""
    previous = os.umask(0o077)
    try:
        yield
    finally:
        os.umask(previous)


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT)


def reviewed_files(manifest):
    inventory = manifest.get("inventory", {})
    files = inventory.get("files")
    runtime = inventory.get("runtime_files")
    if (inventory.get("roots") != [] or not isinstance(files, list) or not files
            or not isinstance(runtime, list) or not runtime or len(set(files)) != len(files)
            or len(set(runtime)) != len(runtime) or not set(runtime) <= set(files)):
        raise ValueError("release-requires-exact-reviewed-inventory")
    for value in files:
        if not isinstance(value, str):
            raise ValueError("unsafe-reviewed-inventory-entry")
        path = PurePosixPath(value)
        if (path.is_absolute() or ".." in path.parts
                or "\\" in value or path.as_posix() != value):
            raise ValueError("unsafe-reviewed-inventory-entry")
    return sorted(files)


def verify_wheel_inventory(wheel, manifest):
    prefix = "mihomoctl-" + VERSION + ".dist-info/"
    with zipfile.ZipFile(wheel) as package:
        names = [i.filename for i in package.infolist() if not i.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate-wheel-members")
        payload = {name for name in names if not name.startswith(prefix)}
        if payload != set(manifest["inventory"]["runtime_files"]):
            raise ValueError("wheel-differs-from-reviewed-runtime-inventory")


@private_creation_mask()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--worktree", action="store_true", help="local development only; not publishable")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob("mihomoctl-*")):
        parser.error("output already contains release artifacts; choose a fresh directory")
    commit = git("rev-parse", "HEAD").decode().strip()
    epoch = int(git("show", "-s", "--format=%ct", "HEAD").decode().strip())
    with tempfile.TemporaryDirectory(prefix="mihomoctl-release-") as folder:
        source = Path(folder) / ("mihomoctl-" + VERSION)
        source.mkdir(mode=0o700)
        if args.worktree:
            manifest = json.loads((ROOT / "release-manifest.json").read_text(encoding="utf-8"))
            for name in reviewed_files(manifest):
                path = ROOT / name
                if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != ROOT.parent):
                    parser.error("symlink-in-reviewed-source")
                if not path.is_file():
                    parser.error("reviewed-source-file-missing: " + name)
                target = source / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
                target.chmod(0o700 if path.stat().st_mode & 0o111 else 0o600)
        else:
            archive = git("archive", "--format=tar", commit)
            with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as package:
                manifest = json.loads(package.extractfile("release-manifest.json").read())
                for name in reviewed_files(manifest):
                    entry = package.getmember(name)
                    if not entry.isfile():
                        parser.error("unsafe-source-archive-entry")
                    target = source / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(package.extractfile(entry).read())
                    # Git's archive umask is independent of the process umask;
                    # never carry writable archive permissions into trusted code.
                    target.chmod(0o700 if entry.mode & 0o111 else 0o600)
        manifest = json.loads((source / "release-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("version") != VERSION or manifest.get("update_protocol") != 2:
            parser.error("release-version-or-protocol-mismatch")
        subprocess.run([sys.executable, "-c",
                        "from pathlib import Path; from mihomoctl.installation import load_manifest, verify_inventory; "
                        "verify_inventory(Path('.'), load_manifest(Path('.')))"], cwd=source, check=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        subprocess.run([sys.executable, source / "scripts/secret_scan.py", "--directory", source], check=True)
        source_files = sorted(p for p in source.rglob("*") if p.is_file())
        tar_path = output / ("mihomoctl-" + VERSION + ".tar.gz")
        zip_path = output / ("mihomoctl-" + VERSION + ".zip")
        with tar_path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=epoch) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as package:
                for path in source_files:
                    info = tarfile.TarInfo(source.name + "/" + path.relative_to(source).as_posix())
                    data = path.read_bytes()
                    info.size, info.mtime = len(data), epoch
                    info.mode = 0o755 if path.suffix in (".sh", ".bash") or path.name == "mihomoctl" else 0o644
                    package.addfile(info, io.BytesIO(data))
        stamp = time.gmtime(max(epoch, 315532800))[:6]
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for path in source_files:
                info = zipfile.ZipInfo(source.name + "/" + path.relative_to(source).as_posix(), date_time=stamp)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if path.suffix in (".sh", ".bash") or path.name == "mihomoctl" else 0o100644) << 16
                package.writestr(info, path.read_bytes())
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(epoch))
        subprocess.run([sys.executable, "-m", "build", "--wheel", "--no-isolation", "--outdir", output, source],
                       check=True, env=env)
        wheels = list(output.glob("mihomoctl-*.whl"))
        if len(wheels) != 1:
            parser.error("exactly-one-wheel-required")
        verify_wheel_inventory(wheels[0], manifest)
        subprocess.run([sys.executable, source / "scripts/secret_scan.py", "--directory", output], check=True)
        digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tar_path, zip_path, wheels[0])}
        (output / "SHA256SUMS").write_text("".join(digests[n] + "  " + n + "\n" for n in sorted(digests)), encoding="utf-8")
        receipt = {"version": VERSION, "commit": commit, "source_epoch": epoch,
                   "source": "worktree" if args.worktree else "git-commit",
                   "publishable": not args.worktree, "sha256": digests}
        (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
