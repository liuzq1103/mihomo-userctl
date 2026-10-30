"""Pure release and offline-kit validation shared by runtime and CI.

These checks inspect bytes and metadata; they never execute downloaded code.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import zipfile
import runpy

# CI also loads this pure validator with runpy before normalizing a source tree.
_identity = runpy.run_path(str(Path(__file__).with_name('release_identity.py')))
distribution = _identity['distribution']
source_stem = _identity['source_stem']
wheel_name = _identity['wheel_name']
asset_names = _identity['asset_names']
sdist_name = _identity['sdist_name']


MAX_BYTES = 512 * 1024 * 1024
MAX_MEMBERS = 20000
TARGETS = {
    'ubuntu22.04-x86_64-py310': ('22.04', (3, 10), '2.35'),
    'ubuntu24.04-x86_64-py312': ('24.04', (3, 12), '2.39'),
}


class VerificationError(ValueError):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise VerificationError('duplicate-release-json-key')
        result[key] = value
    return result


def safe_member(name):
    parts = name.rstrip('/').split('/')
    if (not name or any(part in ('', '.', '..') for part in parts)
            or '\\' in name or ':' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise VerificationError('unsafe-release-archive-member')


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
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    if not isinstance(receipt, dict):
        raise VerificationError("invalid-build-receipt")
    commit = receipt.get("commit")
    version = receipt.get("version")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise VerificationError("full-build-commit-required")
    if not isinstance(version, str) or not re.fullmatch(_identity['VERSION_PATTERN'], version):
        raise VerificationError("build-version-invalid")
    source = receipt.get("source")
    publishable = receipt.get("publishable")
    if (source, publishable) not in (("git-commit", True), ("worktree", False)):
        raise VerificationError("inconsistent-build-source")
    if source == "worktree" and not worktree:
        raise VerificationError("worktree-build-requires-explicit-worktree-flag")
    names = asset_names(version, distribution(receipt))
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
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            raise ValueError("release-bytecode-refused")
    return sorted(files)


def verify_wheel_inventory(wheel, manifest):
    prefix = distribution(manifest).replace('-', '_') + '-' + manifest['version'] + '.dist-info/'
    with zipfile.ZipFile(wheel) as package:
        entries = package.infolist()
        for entry in entries:
            safe_member(entry.filename)
            if entry.flag_bits & 1:
                raise VerificationError('encrypted-release-archive-member')
        if len(entries) > MAX_MEMBERS or sum(entry.file_size for entry in entries) > MAX_BYTES:
            raise ValueError('wheel-size-limit')
        if any(stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR) for entry in entries):
            raise ValueError("unsafe-wheel-member")
        names = [i.filename for i in entries if not i.is_dir()]
        if len(names) != len(set(names)):
            raise ValueError("duplicate-wheel-members")
        payload = {name for name in names if not name.startswith(prefix)}
        if payload != set(manifest["inventory"]["runtime_files"]):
            raise ValueError("wheel-differs-from-reviewed-runtime-inventory")
        metadata_files = {prefix + name for name in (
            "METADATA", "WHEEL", "RECORD", "entry_points.txt", "top_level.txt", "licenses/LICENSE", "LICENSE")}
        if any(name.startswith(prefix) and name not in metadata_files for name in names):
            raise ValueError("wheel-differs-from-reviewed-metadata-inventory")
        from email.parser import BytesParser
        if prefix + 'METADATA' not in names:
            raise ValueError('wheel-metadata-missing')
        metadata = BytesParser().parsebytes(package.read(prefix + 'METADATA'))
        if metadata.get_all('Version') != [manifest['version']] or metadata.get_all('Name') != [distribution(manifest)]:
            raise ValueError('wheel-release-identity-mismatch')
        reject_bytecode(names)


def reject_bytecode(names):
    if any("__pycache__" in PurePosixPath(name).parts or name.endswith((".pyc", ".pyo")) for name in names):
        raise ValueError("release-bytecode-refused")


def verify_sdist_inventory(archive, manifest):
    """Standard sdist has an exact source inventory and bounded build metadata."""
    from email.parser import BytesParser
    name = distribution(manifest)
    root = name.replace('-', '_') + '-' + manifest['version'] + '/'
    metadata = {root + 'PKG-INFO', root + 'setup.cfg'}
    metadata.update(root + name.replace('-', '_') + '.egg-info/' + entry
                    for entry in ('PKG-INFO', 'SOURCES.txt', 'dependency_links.txt',
                                  'entry_points.txt', 'requires.txt', 'top_level.txt'))
    expected = {root + entry for entry in reviewed_files(manifest)}
    names = set()
    used = 0
    with tarfile.open(archive, 'r:gz') as package:
        for index, entry in enumerate(package):
            safe_member(entry.name)
            used += max(0, entry.size)
            if index >= MAX_MEMBERS or used > MAX_BYTES or not (entry.isfile() or entry.isdir()):
                raise VerificationError('unsafe-sdist-member')
            if entry.isdir():
                continue
            if entry.name in names or entry.name not in expected | metadata:
                raise VerificationError('sdist-differs-from-reviewed-inventory')
            names.add(entry.name)
        if not expected <= names or root + 'PKG-INFO' not in names:
            raise VerificationError('sdist-missing-reviewed-source')
        stream = package.extractfile(root + 'PKG-INFO')
        if stream is None:
            raise VerificationError('sdist-metadata-missing')
        headers = BytesParser().parsebytes(stream.read())
        if headers.get_all('Name') != [name] or headers.get_all('Version') != [manifest['version']]:
            raise VerificationError('sdist-release-identity-mismatch')
    reject_bytecode(names)


def verify_source_inventory(archive, manifest):
    root = source_stem(manifest['version'], distribution(manifest)) + '/'
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as package:
            entries = package.infolist()
            for entry in entries:
                safe_member(entry.filename)
                if entry.flag_bits & 1:
                    raise VerificationError('encrypted-release-archive-member')
            if len(entries) > MAX_MEMBERS or sum(entry.file_size for entry in entries) > MAX_BYTES:
                raise ValueError('source-archive-size-limit')
            if any(stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR) for entry in entries):
                raise ValueError("unsafe-source-archive-member")
            reject_bytecode([entry.filename for entry in entries])
            names = [entry.filename for entry in entries if not entry.is_dir()]
    else:
        with tarfile.open(archive, "r:gz") as package:
            entries = []
            used = 0
            for entry in package:
                safe_member(entry.name)
                used += max(entry.size, 0)
                if len(entries) >= MAX_MEMBERS or used > MAX_BYTES:
                    raise ValueError('source-archive-size-limit')
                entries.append(entry)
            if any(not entry.isfile() and not entry.isdir() for entry in entries):
                raise ValueError("unsafe-source-archive-member")
            reject_bytecode([entry.name for entry in entries])
            names = [entry.name for entry in entries if entry.isfile()]
    reject_bytecode(names)
    if len(names) != len(set(names)) or set(names) != {root + name for name in reviewed_files(manifest)}:
        raise ValueError("archive-differs-from-reviewed-source-inventory")


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
    source_name = source_stem(version, distribution(receipt))
    with zipfile.ZipFile(artifacts / (source_name + ".zip")) as archive:
        manifest = json.loads(archive.read(source_name + "/release-manifest.json"), object_pairs_hook=unique_object)
        lock = locked_dependencies(archive.read(source_name + "/requirements-lock.txt").decode("utf-8"))
    if manifest["version"] != version:
        raise ValueError("bundle-source-version-mismatch")
    for suffix in (".zip", ".tar.gz"):
        verify_source_inventory(artifacts / (source_name + suffix), manifest)
    project_wheel = artifacts / wheel_name(version, distribution(receipt))
    verify_wheel_inventory(project_wheel, manifest)
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


def load_bundle(path, target, worktree=False, *, max_bytes=MAX_BYTES):
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
            if member.size < 0 or used > max_bytes:
                raise VerificationError("offline-bundle-size-limit")
            body = archive.extractfile(member).read(member.size + 1)
            if len(body) != member.size:
                raise VerificationError("truncated-offline-bundle")
            payload[name] = body
    try:
        manifest = json.loads(payload["bundle-manifest.json"], object_pairs_hook=unique_object)
        version, commit = manifest["version"], manifest["commit"]
        if (manifest["format"] != 1 or manifest["target"] != target
                or not re.fullmatch(_identity['VERSION_PATTERN'], version)
                or not re.fullmatch(r"[a-f0-9]{40}", commit)
                or root != source_stem(version, distribution(manifest)) + "-offline-" + target
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
        receipt = json.loads(payload["release/build-receipt.json"], object_pairs_hook=unique_object)
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

