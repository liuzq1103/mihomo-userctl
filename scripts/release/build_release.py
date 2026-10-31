#!/usr/bin/env python3
"""Build reviewed source archives, a wheel and checksums from one Git commit."""
import argparse
import contextlib
import gzip
import hashlib
import io
import json
import os
import re
import runpy
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[2]
_identity = runpy.run_path(str(ROOT / 'mihomoctl/release_identity.py'))
source_stem = _identity['source_stem']
wheel_name = _identity['wheel_name']

def version_from_pyproject(root):
    # Do not import the runtime from an unnormalized worktree. The complete
    # identity check runs inside the private staged source below.
    project = (root / 'pyproject.toml').read_text(encoding='utf-8')
    section = re.search(r'^\[project\]\s*\n(.*?)(?=^\[|\Z)', project, re.M | re.S)
    versions = re.findall(r'^version\s*=\s*"(\d+\.\d+\.\d+(?:\.dev\d+)?)"\s*$', section[1] if section else '', re.M)
    if len(versions) != 1:
        raise ValueError('project-version-missing-or-invalid')
    return versions[0]


VERSION = version_from_pyproject(ROOT)


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
    shared = runpy.run_path(str(ROOT / 'mihomoctl/release_artifacts.py'))['reviewed_files']
    return shared(manifest)


def verify_wheel_inventory(wheel, manifest):
    shared = runpy.run_path(str(ROOT / 'mihomoctl/release_artifacts.py'))['verify_wheel_inventory']
    return shared(wheel, dict(manifest, version=manifest.get('version', VERSION)))


def reject_bytecode(names):
    shared = runpy.run_path(str(ROOT / 'mihomoctl/release_artifacts.py'))['reject_bytecode']
    return shared(names)


def verify_source_inventory(archive, manifest):
    shared = runpy.run_path(str(ROOT / 'mihomoctl/release_artifacts.py'))['verify_source_inventory']
    return shared(archive, manifest)


def normalize_sdist(path, epoch):
    """Keep the standard sdist reproducible across both Ubuntu builders."""
    with tarfile.open(path, 'r:gz') as package:
        entries = []
        for entry in package:
            if entry.isdir():
                continue
            if not entry.isfile():
                raise ValueError('unsafe-sdist-member')
            stream = package.extractfile(entry)
            if stream is None:
                raise ValueError('sdist-member-unreadable')
            entries.append((entry.name, stream.read()))
    with path.open('wb') as raw, gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=epoch) as compressed:
        with tarfile.open(fileobj=compressed, mode='w', format=tarfile.PAX_FORMAT) as package:
            for name, content in sorted(entries):
                entry = tarfile.TarInfo(name)
                entry.size, entry.mtime = len(content), epoch
                entry.mode = 0o755 if name.endswith(('.sh', '.bash')) else 0o644
                package.addfile(entry, io.BytesIO(content))


@private_creation_mask()
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    parser.add_argument("--worktree", action="store_true", help="local development only; not publishable")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if any(output.glob("*mihomo*")):
        parser.error("output already contains release artifacts; choose a fresh directory")
    commit = git("rev-parse", "HEAD").decode().strip()
    epoch = int(git("show", "-s", "--format=%ct", "HEAD").decode().strip())
    if args.worktree:
        version = version_from_pyproject(ROOT)
    else:
        # Artifact names must follow the selected commit, never dirty metadata.
        project = git("show", commit + ":pyproject.toml").decode()
        section = re.search(r'^\[project\]\s*\n(.*?)(?=^\[|\Z)', project, re.M | re.S)
        versions = re.findall(r'^version\s*=\s*"(\d+\.\d+\.\d+(?:\.dev\d+)?)"\s*$', section[1] if section else '', re.M)
        if len(versions) != 1:
            parser.error("project-version-missing-or-invalid")
        version = versions[0]
    with tempfile.TemporaryDirectory(prefix="mihomoctl-release-") as folder:
        selected_project = (ROOT / 'pyproject.toml').read_text(encoding='utf-8') if args.worktree else project
        distribution_name = re.search(r'^name\s*=\s*"([^"]+)"', selected_project, re.M)[1]
        source = Path(folder) / source_stem(version, distribution_name)
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
        if manifest.get("version") != version or manifest.get("update_protocol") != 2:
            parser.error("release-version-or-protocol-mismatch")
        subprocess.run([sys.executable, "-c",
                        "from pathlib import Path; from mihomoctl.installation import load_manifest, verify_inventory, cross_check_pyproject; "
                        "from mihomoctl.release_identity import check; check(Path('.')); "
                        "m = load_manifest(Path('.')); cross_check_pyproject(Path('.'), m); verify_inventory(Path('.'), m)"], cwd=source, check=True,
                       env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        subprocess.run([sys.executable, source / "scripts/ci/secret_scan.py", "--directory", source], check=True)
        source_files = sorted(p for p in source.rglob("*") if p.is_file())
        tar_path = output / (source_stem(version, distribution_name) + ".tar.gz")
        zip_path = output / (source_stem(version, distribution_name) + ".zip")
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
        wheels = list(output.glob(distribution_name.replace('-', '_') + '-*.whl'))
        if len(wheels) != 1:
            parser.error("exactly-one-wheel-required")
        verify_wheel_inventory(wheels[0], manifest)
        verify_source_inventory(tar_path, manifest)
        verify_source_inventory(zip_path, manifest)
        subprocess.run([sys.executable, source / "scripts/ci/secret_scan.py", "--directory", output], check=True)
        sdists = []
        if distribution_name == 'mihomo-userctl':
            subprocess.run([sys.executable, '-m', 'build', '--sdist', '--no-isolation', '--outdir', output, source], check=True, env=env)
            sdist = output / _identity['sdist_name'](version, distribution_name)
            runpy.run_path(str(ROOT / 'mihomoctl/release_artifacts.py'))['verify_sdist_inventory'](sdist, manifest)
            normalize_sdist(sdist, epoch)
            sdists.append(sdist)
        digests = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (tar_path, zip_path, wheels[0], *sdists)}
        (output / "SHA256SUMS").write_text("".join(digests[n] + "  " + n + "\n" for n in sorted(digests)), encoding="utf-8")
        receipt = {"version": version, "commit": commit, "source_epoch": epoch,
                   "source": "worktree" if args.worktree else "git-commit",
                   "publishable": not args.worktree, "distribution": distribution_name, "sha256": digests}
        (output / "build-receipt.json").write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
