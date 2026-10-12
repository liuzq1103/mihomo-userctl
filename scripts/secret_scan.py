#!/usr/bin/env python3
"""Scan reviewed Git files or release contents without printing matching data."""
import argparse
import io
from pathlib import Path
import re
import subprocess
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATTERN = re.compile(rb"(subscribe|subscription|token)[=/?][A-Za-z0-9_-]{20,}|127\.0\.0\.1:17891|/home/[A-Za-z0-9._-]+|C:\\Users\\|(^|[^0-9A-Za-z])" + b"liu" + b"zq" + rb"([^0-9A-Za-z]|$)")


def check(name, body):
    leaf = Path(name).name
    if leaf in ("client.env", "credentials.yaml", "proxy.env"):
        raise ValueError("active-secret-file-in-release")
    if PATTERN.search(body):
        raise ValueError("possible-secret-or-personal-path-in-reviewed-content")


def scan_file(path):
    body = path.read_bytes()
    if path.suffix in (".zip", ".whl"):
        with zipfile.ZipFile(io.BytesIO(body)) as package:
            if sum(i.file_size for i in package.infolist()) > 128 * 1024 * 1024:
                raise ValueError("scan-archive-too-large")
            for info in package.infolist():
                if not info.is_dir():
                    check(info.filename, package.read(info))
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(fileobj=io.BytesIO(body), mode="r:gz") as package:
            total = 0
            for info in package:
                total += info.size
                if total > 128 * 1024 * 1024:
                    raise ValueError("scan-archive-too-large")
                if info.isfile():
                    check(info.name, package.extractfile(info).read())
    else:
        check(path.name, body)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.directory:
        files = [p for p in args.directory.rglob("*") if p.is_file()
                 and "__pycache__" not in p.parts and ".git" not in p.parts]
    else:
        # Untracked private notes are not release inputs. Explicitly staged new
        # files and every committed file are checked.
        raw = subprocess.check_output(["git", "ls-files", "--cached", "-z"], cwd=ROOT)
        files = [ROOT / n.decode("utf-8") for n in raw.split(b"\0") if n]
    if not files:
        parser.error("empty-scan-inventory")
    try:
        for file in files:
            if file.is_symlink():
                raise ValueError("symlink-in-reviewed-content")
            if file.exists():
                scan_file(file)
    except (ValueError, OSError, zipfile.BadZipFile, tarfile.TarError) as error:
        print("secret scan failed: " + (str(error) if isinstance(error, ValueError) else "scan-unverified"))
        return 1
    print("secret scan: reviewed content passed configured patterns; not an exhaustive audit")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
