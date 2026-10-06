#!/usr/bin/env python3
"""Download a published release and invoke its existing control-layer installer."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tempfile
import urllib.request
from urllib.parse import urlsplit
import zipfile

REPO = "liuzq1103/mihomo-userctl"
API = "https://api.github.com/repos/" + REPO


class BootstrapError(Exception):
    pass


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        url = urlsplit(newurl)
        if url.scheme != "https" or url.hostname not in ("api.github.com", "codeload.github.com") or url.username or url.password:
            raise BootstrapError("non-official-redirect")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def get(url, limit=2 * 1024 * 1024):
    request = urllib.request.Request(url, headers={"User-Agent": "mihomo-userctl-bootstrap", "Accept": "application/vnd.github+json"})
    with urllib.request.build_opener(Redirect()).open(request, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise BootstrapError("download-too-large")
    return data


def resolve(tag=None):
    if tag is not None and not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", tag):
        raise BootstrapError("version-must-be-stable-tag")
    release = json.loads(get(API + ("/releases/tags/" + tag if tag else "/releases/latest")))
    actual = release.get("tag_name", "")
    if (not re.fullmatch(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", actual)
            or (tag and tag != actual) or release.get("draft") is not False
            or release.get("prerelease") is not False or not release.get("published_at")
            or type(release.get("id")) is not int):
        raise BootstrapError("published-stable-release-required")
    obj = json.loads(get(API + "/git/ref/tags/" + actual))["object"]
    for _ in range(8):
        sha = obj.get("sha", "")
        if not re.fullmatch(r"[0-9a-f]{40}", sha):
            break
        if obj.get("type") == "commit":
            return {"kind": "github-release-source", "repository": REPO, "tag": actual,
                    "commit": sha, "release_id": release["id"],
                    "archive_url": "https://codeload.github.com/" + REPO + "/zip/" + sha,
                    "official_digest": None,
                    "verification": "HTTPS-GitHub-tag-to-commit;no-independent-archive-digest-or-signature"}
        if obj.get("type") != "tag":
            break
        obj = json.loads(get(API + "/git/tags/" + sha))["object"]
    raise BootstrapError("invalid-tag-object")


def extract(archive, destination):
    with zipfile.ZipFile(archive) as package:
        entries = package.infolist()
        if not entries or len(entries) > 5000 or sum(e.file_size for e in entries) > 64 * 1024 * 1024:
            raise BootstrapError("archive-limit-exceeded")
        roots, seen = set(), set()
        for entry in entries:
            raw, mode = entry.filename, entry.external_attr >> 16
            path = PurePosixPath(raw)
            if (not path.parts or path.is_absolute() or ".." in path.parts or "\\" in raw or ":" in raw
                    or any(ord(c) < 32 for c in raw) or entry.flag_bits & 1
                    or stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR) or path in seen):
                raise BootstrapError("unsafe-release-archive")
            roots.add(path.parts[0]); seen.add(path)
        if len(roots) != 1:
            raise BootstrapError("ambiguous-release-root")
        for entry in entries:
            target = destination.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
            else:
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                target.write_bytes(package.read(entry))
                target.chmod(0o700 if entry.external_attr >> 16 & 0o111 else 0o600)
        return destination / roots.pop()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version")
    parser.add_argument("--port", type=int)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if sys.platform != "linux" or sys.version_info < (3, 8):
        raise BootstrapError("Linux-and-Python-3.8-required")
    if args.port is not None and not 1024 <= args.port <= 65535:
        raise BootstrapError("port-out-of-range")
    source = resolve(args.version)
    print("Release: " + source["tag"] + " @ " + source["commit"], flush=True)
    print("Install control layer only; Mihomo core, subscription and service setup follow the setup guide.\n"
          "No sudo, no global proxy, no automatic service start.\n"
          "Trust: HTTPS GitHub release/tag; local SHA256 is a record, not an independent signature.", flush=True)
    with tempfile.TemporaryDirectory(prefix="mihomo-userctl-bootstrap-") as folder:
        root = Path(folder)
        archive = root / "release.zip"
        body = get(source["archive_url"], 16 * 1024 * 1024)
        archive.write_bytes(body)
        source["archive_sha256"] = hashlib.sha256(body).hexdigest()
        checkout = extract(archive, root / "source")
        manifest = json.loads((checkout / "release-manifest.json").read_text())
        if manifest.get("version") != source["tag"][1:] or manifest.get("update_protocol") != 1:
            raise BootstrapError("release-manifest-mismatch")
        record = root / "source.json"
        record.write_text(json.dumps(source)); record.chmod(0o600)
        command = ["bash", str(checkout / "install.sh"), "--source-record", str(record)]
        existing = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo-userctl/current"
        port = args.port
        if port is None and not existing.is_symlink():
            suggestion = subprocess.run(["bash", str(checkout / "install.sh"), "--suggest-port"],
                                        capture_output=True, text=True, timeout=30, check=True).stdout.strip()
            if not suggestion.isdigit() or not 1024 <= int(suggestion) <= 65535:
                raise BootstrapError("invalid-port-suggestion")
            port = int(suggestion)
        if port is not None:
            print("Selected proxy port: " + str(port), flush=True)
            command.extend(("--port", str(port)))
        if args.dry_run:
            command.append("--dry-run")
        rc = subprocess.call(command)
        if rc == 0:
            print("Next: https://github.com/" + REPO + "/blob/" + source["tag"] + "/docs/zh-CN/setup.md")
        return rc


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (Exception, KeyboardInterrupt) as error:
        print("bootstrap: " + (str(error) if isinstance(error, BootstrapError) else "download-or-install-failed"), file=sys.stderr)
        sys.exit(2)
