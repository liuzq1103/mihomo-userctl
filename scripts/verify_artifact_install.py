#!/usr/bin/env python3
"""Verify all release formats through real, isolated, offline user installations.

Only fresh temporary HOME/XDG trees are modified. This does not replace the
separate privileged, systemd, multi-user, or real-core acceptance gates.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile


MAX_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20000


class VerificationError(ValueError):
    pass


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def regular_file(path):
    if path.is_symlink() or not path.is_file():
        raise VerificationError("missing-or-linked-file: " + path.name)
    return path


def load_artifacts(folder, worktree):
    receipt_path = regular_file(folder / "build-receipt.json")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if not isinstance(receipt, dict):
        raise VerificationError("invalid-build-receipt")
    commit = receipt.get("commit")
    version = receipt.get("version")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise VerificationError("full-build-commit-required")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise VerificationError("stable-build-version-required")
    source = receipt.get("source")
    publishable = receipt.get("publishable")
    if (source, publishable) not in (("git-commit", True), ("worktree", False)):
        raise VerificationError("inconsistent-build-source")
    if source == "worktree" and not worktree:
        raise VerificationError("worktree-build-requires-explicit-worktree-flag")
    names = {"mihomoctl-" + version + suffix for suffix in
             (".tar.gz", ".zip", "-py3-none-any.whl")}
    hashes = receipt.get("sha256")
    if not isinstance(hashes, dict) or set(hashes) != names:
        raise VerificationError("artifact-inventory-mismatch")
    for name, expected in hashes.items():
        path = regular_file(folder / name)
        if (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected)
                or digest(path) != expected):
            raise VerificationError("artifact-digest-mismatch: " + name)
    checksums = regular_file(folder / "SHA256SUMS").read_text(encoding="utf-8")
    if checksums != "".join(hashes[n] + "  " + n + "\n" for n in sorted(names)):
        raise VerificationError("checksum-inventory-mismatch")
    return receipt, digest(receipt_path)


def unpack(archive_path, target, root_name):
    """Extract bounded regular files, rejecting links and ambiguous paths."""
    target.mkdir(mode=0o700)
    seen = set()
    total = 0

    def member(name, size, directory, stream=None):
        nonlocal total
        path = PurePosixPath(name.rstrip("/"))
        if (not name or "\\" in name or ":" in name or path.is_absolute()
                or any(ord(c) < 32 or ord(c) == 127 for c in name)
                or any(p in ("", ".", "..") for p in name.rstrip("/").split("/"))
                or not path.parts or path.parts[0] != root_name or str(path) in seen):
            raise VerificationError("unsafe-or-duplicate-archive-member")
        seen.add(str(path))
        total += size
        if len(seen) > MAX_MEMBERS or size < 0 or total > MAX_BYTES:
            raise VerificationError("archive-size-limit")
        dest = target.joinpath(*path.parts)
        if directory:
            dest.mkdir(parents=True, exist_ok=True, mode=0o700)
            return
        dest.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        remaining = size
        with dest.open("xb") as output:
            while remaining:
                chunk = stream.read(min(1024 * 1024, remaining))
                if not chunk:
                    raise VerificationError("truncated-archive-member")
                output.write(chunk)
                remaining -= len(chunk)
            if stream.read(1):
                raise VerificationError("archive-member-size-mismatch")
        dest.chmod(0o600)

    if archive_path.suffix == ".zip":
        with zipfile.ZipFile(archive_path) as archive:
            for entry in archive.infolist():
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise VerificationError("archive-links-or-special-files-forbidden")
                with archive.open(entry) as stream:
                    member(entry.filename, entry.file_size, entry.is_dir(), stream)
    else:
        with tarfile.open(archive_path, "r:gz") as archive:
            for entry in archive:
                if not (entry.isfile() or entry.isdir()):
                    raise VerificationError("archive-links-or-special-files-forbidden")
                stream = archive.extractfile(entry) if entry.isfile() else None
                try:
                    member(entry.name, entry.size, entry.isdir(), stream)
                finally:
                    if stream is not None:
                        stream.close()
    source = target / root_name
    regular_file(source / "scripts" / "bootstrap.py")
    return source


def invoke(args, env, stage):
    result = subprocess.run([str(x) for x in args], env=env, text=True,
                            capture_output=True, timeout=120)
    if result.returncode:
        # Do not copy child diagnostics or environment values into public reports.
        raise VerificationError("command-failed: %s (exit %d)" % (stage, result.returncode))
    try:
        document = json.loads(result.stdout[result.stdout.index("{"):])
    except (ValueError, TypeError):
        raise VerificationError("invalid-command-json: " + stage) from None
    if not isinstance(document, dict):
        raise VerificationError("command-object-required: " + stage)
    return document


def version_check(launcher, env, version):
    doc = invoke([launcher, "--json", "version"], env, "version")
    if (doc.get("schema") != "mihomoctl/v1" or doc.get("overall") != "PASS"
            or doc.get("data", {}).get("mihomoctl") != version):
        raise VerificationError("installed-version-mismatch")


def verify_case(kind, artifacts, wheelhouse, python, version):
    with tempfile.TemporaryDirectory(prefix="mihomoctl-artifact-install-") as temporary:
        base = Path(temporary)
        base.chmod(0o700)
        home = base / "home"
        home.mkdir(mode=0o700)
        protected = {}
        for name in (".bashrc", ".zshrc", ".profile", ".bash_profile",
                     "config/mihomoctl/existing-config.yaml", "external-core"):
            path = home / name
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            content = ("existing file must survive: " + name + "\n").encode()
            path.write_bytes(content)
            protected[path] = content
        env = {"HOME": str(home), "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
               "PIP_NO_INDEX": "1"}
        for variable, dirname in (("XDG_CONFIG_HOME", "config"), ("XDG_DATA_HOME", "data"),
                                  ("XDG_STATE_HOME", "state"), ("XDG_CACHE_HOME", "cache"),
                                  ("XDG_RUNTIME_DIR", "runtime")):
            path = home / dirname
            path.mkdir(mode=0o700, exist_ok=True)
            env[variable] = str(path)
        root_name = "mihomoctl-" + version
        archive = artifacts / (root_name + (".zip" if kind == "zip" else ".tar.gz"))
        source = unpack(archive, base / "unpacked", root_name)
        bootstrap = source / "scripts" / "bootstrap.py"
        payload = archive
        if kind == "wheel":
            payload = base / "wheel-source"
            payload.mkdir(mode=0o700)
            wheel = artifacts / (root_name + "-py3-none-any.whl")
            shutil.copyfile(wheel, payload / wheel.name)
            shutil.copyfile(source / "release-manifest.json", payload / "release-manifest.json")
        first = invoke([python, "-I", bootstrap, "install", "--source", payload,
                        "--wheelhouse", wheelhouse, "--python", python], env, "install")
        launcher = Path(first["bin_link"])
        version_check(launcher, env, version)
        invoke([python, "-I", bootstrap, "verify"], env, "verify-install")
        update = invoke([launcher, "--json", "update", payload, "--wheelhouse", wheelhouse,
                         "--python", python, "--allow-same-version"], env, "update")
        if update.get("overall") != "PASS" or update.get("errors"):
            raise VerificationError("update-not-successful")
        updated = update["data"]
        if updated["generation"] == first["generation"]:
            raise VerificationError("update-did-not-switch-generation")
        recovery = Path(updated["backup"]) / "bootstrap.py"
        source.rename(source.with_name(source.name + "-retired"))
        invoke([python, "-I", recovery, "rollback", updated["backup"]], env, "rollback-update")
        version_check(launcher, env, version)
        installed = Path(first["install_root"]) / "current" / "lib" / "scripts" / "bootstrap.py"
        invoke([python, "-I", installed, "verify"], env, "verify-rollback")
        removed = invoke([python, "-I", installed, "uninstall"], env, "uninstall")
        if launcher.exists() or launcher.is_symlink():
            raise VerificationError("launcher-remains-after-uninstall")
        invoke([python, "-I", Path(removed["backup"]) / "bootstrap.py", "rollback",
                removed["backup"]], env, "restore-uninstalled")
        version_check(launcher, env, version)
        invoke([python, "-I", installed, "verify"], env, "verify-restored")
        for path, original in protected.items():
            if path.read_bytes() != original:
                raise VerificationError("protected-existing-file-changed")
        return {"kind": kind, "result": "PASS", "version": version,
                "source_removed_recovery": True, "protected_files_unchanged": True,
                "generation_switched": True, "uninstall_restored": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--python", default=Path(sys.executable), type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--worktree", action="store_true",
                        help="allow development artifacts; never produces publishable acceptance")
    args = parser.parse_args(argv)
    report = {"success": False, "publishable_acceptance": False, "tests": 0,
              "skipped": 0, "failures": 0, "errors": 0, "cases": [],
              "python": sys.version.split()[0], "os": sys.platform}
    try:
        receipt, receipt_digest = load_artifacts(args.artifacts, args.worktree)
        report.update({"commit": receipt["commit"], "source": receipt["source"],
                       "source_dirty": receipt["source"] != "git-commit",
                       "publishable": receipt["publishable"], "version": receipt["version"],
                       "build_receipt_sha256": receipt_digest, "artifact_sha256": receipt["sha256"]})
        if sys.platform != "linux" or os.geteuid() == 0:
            raise VerificationError("non-root-linux-user-required")
        if not args.wheelhouse.is_dir() or args.wheelhouse.is_symlink():
            raise VerificationError("local-wheelhouse-directory-required")
        python = args.python.absolute()
        if not python.is_file():
            raise VerificationError("python-interpreter-required")
        for kind in ("tar.gz", "zip", "wheel"):
            case = verify_case(kind, args.artifacts.absolute(), args.wheelhouse.absolute(),
                               python, receipt["version"])
            report["cases"].append(case)
            report["tests"] += 1
        # Check that none of the input assets changed during installation.
        final_receipt, final_digest = load_artifacts(args.artifacts, args.worktree)
        if final_receipt != receipt or final_digest != receipt_digest:
            raise VerificationError("build-receipt-changed-during-verification")
        report["success"] = True
        report["publishable_acceptance"] = receipt["publishable"] and not args.worktree
    except Exception as error:
        report["errors"] = 1
        report["error"] = str(error) if isinstance(error, VerificationError) else type(error).__name__
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(args.report))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
