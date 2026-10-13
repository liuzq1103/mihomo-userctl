"""V1 installation engine (protocol 2).

Owns the mihomoctl CLI installation lifecycle: offline wheel/source
packaging into immutable generations, atomic pointer switching, locking,
private permissions, safe path checks and self-contained backup rollback.

Hard product rules (architecture-v1 / ADR 0002):

- Installation, update and uninstallation never write shell startup files
  (``.bashrc``/``.zshrc``/``profile``), never start or stop services or
  third-party daemons, and never require a proxy or any network access.
- Default scope is ``user``.  System writes require an explicit
  ``Scope(system=True)`` *and* euid 0; root never loads user-writable code
  (interpreter and generation trees must be root-owned and not
  group/other-writable).
- An existing Mihomo core is never adopted, replaced or removed by the
  installer; cores live under the scope data root and are untouched here.
- Old protocol (format/update_protocol 1) sources are refused before any
  write, with migration guidance.

Layout (per scope):

    User: <data_root>/install/generations/<uuid32>/{lib/, bin/mihomoctl, record.json}
    System: /usr/local/lib/mihomoctl/generations/<uuid32>/ (root-owned readable code)
    <data_root>/install/current -> generations/<uuid32>   (atomic symlink switch)
    <data_root>/install-pending.json                       (transaction marker)
    <state_root>/install-backups/<kind>-<time>-<uid8>/     (self-contained)
    <bin_dir>/mihomoctl -> <install_root>/current/bin/mihomoctl

Public API for the CLI (update/rollback commands): :func:`install`,
:func:`uninstall`, :func:`rollback`, :func:`verify_installed`,
:func:`current_record`, :func:`installation_status`,
:func:`prune_generations`, :func:`load_manifest`.
"""

import base64
import csv
import io
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

from . import locks
from .errors import MihomoctlError, PermissionScopeError
from .scope import Scope
from .trust import (require_executable_file, require_private_dir, require_private_file,
                    require_trusted_dir)

PROTOCOL = 2
PROJECT_NAME = "mihomoctl"
CONSOLE_SCRIPT = "mihomoctl"
ENTRY_POINT = "mihomoctl.cli:main"
REQUIRES_PYTHON = ">=3.10"

GENERATION_RE = re.compile(r"[a-f0-9]{32}$")
VERSION_RE = re.compile(r"\d+(\.\d+)*((a|b|rc)\d+)?$")
MANIFEST_KEYS = frozenset({"format", "version", "update_protocol", "validation_profile",
                           "requires_python", "console_script", "entry_point", "dependencies",
                           "packages", "inventory"})
INVENTORY_KEYS = frozenset({"roots", "files", "runtime_files", "comment"})
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*$")

MAX_ARCHIVE_MEMBERS = 20000
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
SMOKE_TIMEOUT = 60
WHEEL_DIR_FILES = re.compile(r"(\.whl|SHA256SUMS|build-receipt\.json|release-manifest\.json)$")

# Local working-tree noise that never enters a release and is ignored when
# validating a source tree.  Everything else outside the manifest inventory
# is refused.  paseo.json is local agent-tooling configuration, untracked.
IGNORED_SOURCE_ENTRIES = frozenset({".git", "__pycache__", ".pytest_cache", ".mypy_cache",
                                    ".ruff_cache", "dist", "build", ".venv", "node_modules",
                                    ".egg-info", ".idea", ".vscode", "paseo.json"})
PRIVATE_BASENAMES = frozenset({"credentials.yaml", "client.env", "proxy.env", ".env", "secrets.json"})
PRIVATE_NAME_PARTS = ("MainServer",)


class InstallationError(MihomoctlError):
    code = "installation-failed"


class OldProtocolError(InstallationError):
    code = "old-protocol-refused"


class InstallationDriftError(InstallationError):
    code = "installation-drift"


class InventoryError(InstallationError):
    code = "source-not-reviewed"


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------


def digest_bytes(data):
    return hashlib.sha256(data).hexdigest()


def digest_file(path):
    sha = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest()


def sync_dir(path):
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def normalize_name(name):
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_version(text):
    """PEP 440 subset: N(.N)* with optional a/b/rc pre-release."""
    text = str(text).strip()
    match = re.fullmatch(r"(\d+(?:\.\d+)*)((?:a|b|rc)\d+)?", text)
    if not match:
        raise InstallationError("unsupported-version-format", str(text))
    numbers = tuple(int(n) for n in match[1].split("."))
    while len(numbers) > 1 and numbers[-1] == 0:
        numbers = numbers[:-1]
    pre = re.fullmatch(r"(a|b|rc)(\d+)", match[2] or "")
    return (numbers, ({"a": 0, "b": 1, "rc": 2}[pre[1]], int(pre[2])) if pre else (3, 0))


def _specifier_satisfied(spec, version_key):
    for constraint in [c.strip() for c in spec.split(",") if c.strip()]:
        match = re.fullmatch(r"(===|==|!=|>=|<=|>|<|~=)\s*(\S+)", constraint)
        if not match:
            raise InstallationError("unsupported-version-specifier", constraint)
        op, raw = match[1], match[2]
        other = parse_version(raw)
        if op in ("==", "==="):
            ok = version_key == other
        elif op == "!=":
            ok = version_key != other
        elif op == ">=":
            ok = version_key >= other
        elif op == "<=":
            ok = version_key <= other
        elif op == ">":
            ok = version_key > other
        elif op == "<":
            ok = version_key < other
        else:  # ~=: same release family, at least this version
            family = other[0][:-1] if len(other[0]) > 1 else other[0]
            ok = version_key[0][:len(family)] == family and version_key >= other
        if not ok:
            return False
    return True


def parse_requirement(text):
    """Split 'Name[extras] specifier ; marker' into (name, spec, marker).

    Marker-only requirements whose marker mentions ``extra`` are optional
    extras and are skipped by the caller; any other marker fails closed
    because this installer never evaluates environment markers."""
    text = text.strip()
    marker = None
    if ";" in text:
        text, _, marker = text.partition(";")
        marker = marker.strip()
    match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]*)(\[[^\]]*\])?\s*(.*)", text.strip())
    if not match:
        raise InstallationError("unsupported-requirement", text)
    return normalize_name(match[1]), match[3].strip(), marker


# ---------------------------------------------------------------------------
# manifest (protocol gate — must run before any active-path write)
# ---------------------------------------------------------------------------


def load_manifest(directory):
    """Strictly validate ``release-manifest.json`` under ``directory``.

    Raises :class:`OldProtocolError` for protocol-1 manifests so callers
    refuse before performing any write."""
    path = Path(directory) / "release-manifest.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_json_object)
    except FileNotFoundError:
        raise InstallationError("release-manifest-missing",
                                str(path), "use a complete reviewed release tree") from None
    except (OSError, ValueError) as exc:
        raise InstallationError("release-manifest-unreadable", str(exc)) from None
    if not isinstance(raw, dict):
        raise InstallationError("release-manifest-invalid", "not an object")
    if raw.get("update_protocol") == 1 or raw.get("format") == 1:
        raise OldProtocolError(
            "update-protocol-1-no-longer-supported",
            "the source predates installation protocol 2",
            "no files were changed; obtain a protocol-2 release and follow the "
            "V1 migration guide (mihomoctl migrate --dry-run)")
    if raw.get("update_protocol") != PROTOCOL or raw.get("format") != PROTOCOL:
        raise OldProtocolError("unsupported-installation-protocol",
                               repr(raw.get("update_protocol")), "no files were changed")
    unknown = set(raw) - MANIFEST_KEYS
    missing = (MANIFEST_KEYS - set(raw)) | ({"inventory"} - set(raw))
    if unknown or missing:
        raise InstallationError("release-manifest-invalid",
                                "unexpected keys: %s; missing: %s" % (sorted(unknown), sorted(missing)))
    if not isinstance(raw["version"], str) or not VERSION_RE.fullmatch(raw["version"]):
        raise InstallationError("release-manifest-invalid", "bad version %r" % raw["version"])
    if (raw["validation_profile"] != "installation-v2"
            or raw["console_script"] != CONSOLE_SCRIPT
            or raw["requires_python"] != REQUIRES_PYTHON
            or not isinstance(raw["dependencies"], list)
            or not isinstance(raw["packages"], list)
            or not raw["packages"]
            or any(not isinstance(p, str) or not IDENTIFIER_RE.fullmatch(p) for p in raw["packages"])):
        raise InstallationError("release-manifest-invalid", "field values disagree with protocol 2")
    if raw["entry_point"] != ENTRY_POINT:
        raise InstallationError("entry-point-disagrees-with-manifest", "release-manifest.json")
    for requirement in raw["dependencies"]:
        if not isinstance(requirement, str):
            raise InstallationError("release-manifest-invalid", "dependencies must be requirement strings")
        parse_requirement(requirement)
    inventory = raw["inventory"]
    if (not isinstance(inventory, dict) or set(inventory) - INVENTORY_KEYS
            or {"roots", "files"} - set(inventory)):
        raise InstallationError("release-manifest-invalid", "bad inventory section")
    if any(not isinstance(inventory.get(key), list) or any(not isinstance(v, str) for v in inventory[key]) for key in ("roots", "files", "runtime_files")):
        raise InstallationError("release-manifest-invalid", "inventory values must be string lists")
    if any(len(inventory[key]) != len(set(inventory[key])) for key in ("files", "runtime_files")):
        raise InstallationError("release-manifest-invalid", "duplicate inventory entries")
    if inventory["roots"]:
        raise InstallationError("release-manifest-invalid", "directory-prefix inventory is forbidden")
    if not isinstance(inventory.get("runtime_files"), list) or not set(inventory["runtime_files"]) <= set(inventory["files"]):
        raise InstallationError("release-manifest-invalid", "runtime_files must be explicit source files")
    for entry in inventory["files"] + inventory["runtime_files"]:
        pure = PurePosixPath(entry)
        if (not entry or pure.as_posix() != entry or pure.is_absolute() or ".." in pure.parts
                or "\\" in entry or ":" in entry or any(ord(c) < 32 for c in entry)):
            raise InstallationError("release-manifest-invalid", "bad inventory entry %r" % entry)
    if PROJECT_NAME not in raw["packages"]:
        raise InstallationError("release-manifest-invalid", "mihomoctl package missing from packages")
    return raw


def _unique_json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _private_segment(relative):
    parts = PurePosixPath(relative).parts
    return any(segment in PRIVATE_BASENAMES or any(p in segment for p in PRIVATE_NAME_PARTS)
               for segment in parts)


def verify_inventory(source_root, manifest, kind="source-tree"):
    """Every payload file must be covered by the precise manifest inventory."""
    files = set(manifest["inventory"]["files"])
    seen = set()
    for dirpath, dirnames, filenames in os.walk(source_root):
        parts = Path(dirpath).relative_to(source_root).parts
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_SOURCE_ENTRIES and not d.endswith(".egg-info"))
        for name in dirnames + filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                raise InventoryError("source-symlink-refused", path.relative_to(source_root).as_posix())
        for name in sorted(filenames):
            relative = Path(*parts, name).as_posix() if parts else name
            if name.endswith((".pyc", ".pyo")) or name in IGNORED_SOURCE_ENTRIES:
                continue
            if _private_segment(relative):
                raise InventoryError("unreviewed-private-content-refused", relative)
            if kind == "wheel-dir":
                if parts or not WHEEL_DIR_FILES.search(name):
                    raise InventoryError("source-file-not-in-reviewed-inventory", relative)
            elif relative not in files:
                raise InventoryError("source-file-not-in-reviewed-inventory", relative)
            seen.add(relative)
    if kind != "wheel-dir" and files - seen:
        raise InventoryError("reviewed-source-files-missing", sorted(files - seen)[:3])


# ---------------------------------------------------------------------------
# pyproject subset reader (strict; the file is part of the reviewed release)
# ---------------------------------------------------------------------------


def parse_pyproject(path):
    """Read the small pyproject.toml surface the installer needs.

    Supports ``key = value`` and ``key = ["a", "b"]`` arrays (possibly
    spread over continuation lines) inside ``[project]``, ``[project.scripts]``
    and ``[tool.setuptools]``.  Anything else fails closed."""
    result = {}
    section = None
    current_key = None
    pending_items = None
    for lineno, raw in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("["):
            if pending_items is not None:
                raise InstallationError("pyproject-unsupported-syntax", "unterminated array before line %d" % lineno)
            if not re.fullmatch(r"\[[A-Za-z0-9._-]+\]", stripped):
                raise InstallationError("pyproject-unsupported-syntax", "line %d" % lineno)
            section, current_key = stripped[1:-1], None
            continue
        if section not in ("project", "project.scripts", "tool.setuptools"):
            continue
        if pending_items is not None:
            chunk, closed, pending_items = _array_chunk(stripped, pending_items)
            if closed:
                result[(section, current_key)] = pending_items
                pending_items = None
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)\s*=\s*(.*)", stripped)
        if not match:
            raise InstallationError("pyproject-unsupported-syntax", "line %d" % lineno)
        current_key, value = match[1], match[2].strip()
        if (section, current_key) in result:
            raise InstallationError("pyproject-duplicate-key", "%s.%s" % (section, current_key))
        if value.startswith("["):
            chunk, closed, items = _array_chunk(value, [])
            if closed:
                result[(section, current_key)] = items
                pending_items = None
            else:
                pending_items = items
        elif value.startswith(('"', "'")) and value.endswith(value[0]) and len(value) >= 2:
            result[(section, current_key)] = value[1:-1]
        elif current_key not in ("name", "version", "requires-python", "dependencies", "packages", "mihomoctl"):
            continue
        else:
            raise InstallationError("pyproject-unsupported-syntax", "line %d" % lineno)
    if pending_items is not None:
        raise InstallationError("pyproject-unsupported-syntax", "unterminated array at end of file")
    return result


def _array_chunk(text, items):
    head, separator, tail = text.partition("]")
    body = head if separator else text
    for quoted in re.findall(r'"([^"]*)"|\'([^\']*)\'', body):
        items.append(quoted[0] or quoted[1])
    return body, bool(separator), items


def cross_check_pyproject(source_root, manifest):
    values = parse_pyproject(Path(source_root) / "pyproject.toml")
    if values.get(("project", "version")) != manifest["version"]:
        raise InstallationError("source-version-markers-disagree", "pyproject.toml")
    for name, marker in (("mihomoctl/__init__.py", "__version__"),):
        try:
            text = (Path(source_root) / name).read_text(encoding="utf-8")
        except OSError:
            raise InstallationError("source-version-marker-missing", name) from None
        assignments = re.findall(r"^\s*" + marker + r"\s*=([^\n]*)$", text, re.M)
        if len(assignments) != 1 or not re.fullmatch(
                r"\s*(['\"])" + re.escape(manifest["version"]) + r"\1\s*", assignments[0]):
            raise InstallationError("source-version-markers-disagree", name)
    if values.get(("project.scripts", CONSOLE_SCRIPT)) != manifest["entry_point"]:
        raise InstallationError("entry-point-disagrees-with-manifest", "pyproject.toml")
    dependencies = values.get(("project", "dependencies"))
    if dependencies is not None and dependencies != manifest["dependencies"]:
        raise InstallationError("source-dependencies-disagree-with-manifest", "pyproject.toml")
    requires_python = values.get(("project", "requires-python"))
    if requires_python is not None and requires_python != manifest["requires_python"]:
        raise InstallationError("source-python-version-disagrees-with-manifest", "pyproject.toml")
    declared = values.get(("tool.setuptools", "packages"))
    if declared is not None:
        # pyproject lists setuptools packages (including sub-packages); the
        # manifest lists the top-level roots that get copied into a generation.
        if {p.split(".")[0] for p in declared} != set(manifest["packages"]):
            raise InstallationError("pyproject-packages-disagree-with-manifest",
                                    "%s != %s" % (sorted({p.split(".")[0] for p in declared}),
                                                  sorted(manifest["packages"])))


# ---------------------------------------------------------------------------
# wheel support
# ---------------------------------------------------------------------------

WHEEL_NAME_RE = re.compile(
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)-(?P<version>\d[^-]*)"
    r"(?:-(?P<build>\d[^-]*))?-(?P<py>[^-]+)-(?P<abi>[^-]+)-(?P<plat>[^-]+)\.whl$")


def parse_wheel_filename(path):
    match = WHEEL_NAME_RE.fullmatch(Path(path).name)
    if not match:
        raise InstallationError("invalid-wheel-filename", Path(path).name)
    info = match.groupdict()
    parse_version(info["version"])
    return {"name": normalize_name(info["name"]), "version": info["version"],
            "py": info["py"], "abi": info["abi"], "plat": info["plat"], "path": Path(path)}


def wheel_compatible_here(info, target=None):
    target = target or {"version": list(sys.version_info[:3]), "machine": platform.machine(),
                        "libc": platform.libc_ver(), "implementation": sys.implementation.name}
    version = tuple(target["version"][:2])
    minor = "%d%d" % version
    machine = target["machine"]
    for py in info["py"].split("."):
        abi = info["abi"]
        ok_py = (py in ("py3", "py%d%d" % version) and abi == "none") or (
            target["implementation"] == "cpython" and (
                (py == "cp" + minor and abi in ("none", "abi3", "cp" + minor)) or (
                    re.fullmatch(r"cp3\d+", py) and (3, int(py[3:])) <= version and abi == "abi3")))
        for plat in info["plat"].split("."):
            ok_plat = plat in ("any", "linux_" + machine)
            if target["libc"][0] == "glibc":
                match = re.fullmatch(r"manylinux_(\d+)_(\d+)_" + re.escape(machine), plat)
                minimum = None
                if match:
                    minimum = tuple(map(int, match.groups()))
                elif plat.endswith("_" + machine):
                    minimum = {"manylinux1": (2, 5), "manylinux2010": (2, 12),
                               "manylinux2014": (2, 17)}.get(plat.removesuffix("_" + machine))
                if minimum:
                    try:
                        ok_plat = tuple(map(int, target["libc"][1].split(".")[:2])) >= minimum
                    except ValueError:
                        ok_plat = False
            if ok_py and ok_plat:
                return True
    return False


def _safe_member(name):
    pure = PurePosixPath(name)
    if (not name or pure.is_absolute() or ".." in pure.parts or "\\" in name or ":" in name
            or name.startswith("/") or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        raise InstallationError("unsafe-archive-member", name)
    return pure.parts


def _dist_prefix(info):
    return "%s-%s.dist-info/" % (info["name"].replace("-", "_"), info["version"])


def _wheel_limits(zf):
    members = zf.infolist()
    if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
        raise InstallationError("wheel-exceeds-size-limits", "bounded wheel archive required")
    names = [m.filename for m in members]
    if len(names) != len(set(names)):
        raise InstallationError("duplicate-archive-path", "duplicate wheel member")
    for member in members:
        _safe_member(member.filename)
        if "__pycache__" in PurePosixPath(member.filename).parts or member.filename.endswith((".pyc", ".pyo")):
            raise InstallationError("release-bytecode-refused", member.filename)
        if stat.S_IFMT(member.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise InstallationError("unsafe-archive-member", member.filename)
        if member.filename.endswith(("/METADATA", "/WHEEL", "/RECORD")) and member.file_size > 4 * 1024 * 1024:
            raise InstallationError("wheel-metadata-size-limit", "metadata too large")


def _read_wheel_metadata(zf, info):
    _wheel_limits(zf)
    prefixes = {n.split("/", 1)[0] + "/" for n in zf.namelist() if n.endswith(".dist-info/METADATA")}
    valid = [p for p in prefixes if normalize_name(p[:-1].removesuffix(".dist-info").rsplit("-", 1)[0]) == info["name"] and p.endswith("-" + info["version"] + ".dist-info/")]
    if len(valid) != 1:
        raise InstallationError("wheel-metadata-missing", Path(info["path"]).name)
    prefix = valid[0]
    try:
        metadata = zf.read(prefix + "METADATA").decode("utf-8")
        wheel_md = zf.read(prefix + "WHEEL").decode("utf-8")
    except KeyError:
        raise InstallationError("wheel-metadata-missing", Path(info["path"]).name) from None
    headers = {}
    requires = []
    for line in metadata.splitlines():
        if not line.strip():
            break
        if line.partition(":")[0].lower() == "requires-dist":
            requires.append(line.partition(":")[2].strip())
            continue
        if ":" in line and not line.startswith((" ", "\t")):
            key, _, value = line.partition(":")
            headers.setdefault(key.strip().lower(), value.strip())
    if not re.search(r"^Wheel-Version:\s*1\.", wheel_md, re.M):
        raise InstallationError("unsupported-wheel-version", Path(info["path"]).name)
    def expanded_tag(value):
        parts = value.split("-")
        if len(parts) != 3 or any(not re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", p) for p in parts):
            raise InstallationError("wheel-tag-invalid", Path(info["path"]).name)
        return {"-".join((py, abi, plat)) for py in parts[0].split(".")
                for abi in parts[1].split(".") for plat in parts[2].split(".")}
    filename_tags = expanded_tag("-".join(info[key] for key in ("py", "abi", "plat")))
    metadata_tags = set()
    for value in re.findall(r"^Tag:\s*([^\n]+)$", wheel_md, re.M):
        metadata_tags.update(expanded_tag(value.strip()))
    if metadata_tags != filename_tags:
        raise InstallationError("wheel-tags-disagree-with-filename", Path(info["path"]).name)
    return {"name": headers.get("name", ""), "version": headers.get("version", ""),
            "requires_python": headers.get("requires-python", ""),
            "requires": [r for r in requires if r], "prefix": prefix}


def _verify_record(zf, info):
    prefixes = {n.split("/", 1)[0] + "/" for n in zf.namelist() if n.endswith(".dist-info/METADATA")}
    valid = [p for p in prefixes if normalize_name(p[:-1].removesuffix(".dist-info").rsplit("-", 1)[0]) == info["name"] and p.endswith("-" + info["version"] + ".dist-info/")]
    if len(valid) != 1:
        raise InstallationError("wheel-metadata-missing", Path(info["path"]).name)
    prefix = valid[0]
    try:
        record = zf.read(prefix + "RECORD").decode("utf-8")
    except KeyError:
        raise InstallationError("wheel-record-missing", Path(info["path"]).name) from None
    expected = {}
    for parts in csv.reader(io.StringIO(record)):
        if not parts:
            continue
        if not parts or not parts[0]:
            continue
        entry_hash = parts[1] if len(parts) > 1 else ""
        if entry_hash.startswith("sha256="):
            expected[parts[0]] = entry_hash[len("sha256="):]
    members = {name for name in zf.namelist() if not name.endswith("/")}
    listed = set(expected) | {prefix + "RECORD"}
    if members - listed:
        raise InstallationError("wheel-contents-not-covered-by-record",
                                "%s: %s" % (Path(info["path"]).name, sorted(members - listed)[:3]))
    for name, want in expected.items():
        if name not in members:
            raise InstallationError("wheel-record-entry-missing", name)
        actual = base64.urlsafe_b64encode(hashlib.sha256(zf.read(name)).digest()).rstrip(b"=").decode()
        if actual != want:
            raise InstallationError("wheel-record-digest-mismatch", name)


def _mkdir_owned_parents(path, mode):
    """Create each missing component with an explicit safe mode.

    pathlib's parents=True applies mode only to the leaf; an inherited umask
    of 002 must not make intermediate code or recovery directories writable.
    Existing directories are validated, never repaired or silently chmodded.
    """
    from .trust import _check_ancestors
    path = Path(path)
    _check_ancestors(path, "installation-failed", {0, os.geteuid()})
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    require_trusted_dir(cursor)
    for component in reversed(missing):
        component.mkdir(mode=mode)
    require_trusted_dir(path)


def unpack_wheel(path, lib_dir, *, allowed_top_levels=None):
    """Safely unpack one wheel into ``lib_dir`` with bounded sizes."""
    info = parse_wheel_filename(path)
    with zipfile.ZipFile(path) as zf:
        _wheel_limits(zf)
        if zf.testzip() is not None:
            raise InstallationError("wheel-corrupt", Path(path).name)
        _verify_record(zf, info)
        members = [m for m in zf.infolist() if not m.filename.endswith("/")]
        if len(members) > MAX_ARCHIVE_MEMBERS or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
            raise InstallationError("wheel-exceeds-size-limits", Path(path).name)
        tops = set()
        for member in members:
            parts = _safe_member(member.filename)
            if stat.S_ISLNK((member.external_attr >> 16) & 0xFFFF):
                raise InstallationError("wheel-symlink-member-refused", member.filename)
            tops.add(parts[0])
            target = Path(lib_dir, *parts)
            try:
                _mkdir_owned_parents(target.parent, 0o755)
                with open(target, "xb") as output:
                    output.write(zf.read(member))
            except FileExistsError:
                raise InstallationError("duplicate-archive-path", member.filename) from None
            os.chmod(target, 0o644)
        if allowed_top_levels is not None:
            allowed = set(allowed_top_levels) | {_dist_prefix(info).rstrip("/")}
            extra = tops - allowed - {t for t in tops if t.endswith(".dist-info")}
            if extra:
                raise InventoryError("wheel-top-levels-not-in-manifest", sorted(extra))
        sync_dir(lib_dir)
    return info


def resolve_dependency_wheels(requirements, wheelhouse, target=None):
    """Pick wheels from ``wheelhouse`` satisfying the closed requirement set."""
    if not Path(wheelhouse).is_dir():
        raise InstallationError("wheelhouse-missing", str(wheelhouse))
    available = {}
    for path in sorted(Path(wheelhouse).glob("*.whl")):
        info = parse_wheel_filename(path)
        available.setdefault(info["name"], []).append(info)
    chosen_wheels = []
    queue = list(requirements)
    seen = {}
    while queue:
        text = queue.pop(0)
        name, spec, marker = parse_requirement(text)
        if marker is not None:
            if "extra" in marker:
                continue  # optional extra, never installed implicitly
            raise InstallationError("unsupported-environment-marker", text)
        if name in seen:
            if not _specifier_satisfied(spec, parse_version(seen[name]["version"])):
                raise InstallationError("dependency-constraint-conflict", name)
            continue
        candidates = [i for i in available.get(name, []) if wheel_compatible_here(i, target)]
        chosen = None
        for candidate in sorted(candidates, key=lambda i: parse_version(i["version"]), reverse=True):
            if _specifier_satisfied(spec, parse_version(candidate["version"])):
                chosen = candidate
                break
        if chosen is None:
            raise InstallationError(
                "dependency-wheel-missing", "%s%s in %s" % (name, spec, wheelhouse),
                "add the wheel to --wheelhouse or install the dependency system-wide")
        seen[name] = chosen
        chosen_wheels.append(chosen)
        with zipfile.ZipFile(chosen["path"]) as zf:
            meta = _read_wheel_metadata(zf, chosen)
            _verify_record(zf, chosen)
            if normalize_name(meta["name"]) != name or meta["version"] != chosen["version"]:
                raise InstallationError("wheel-metadata-disagrees-with-filename", chosen["path"].name)
            version = target["version"] if target else sys.version_info[:3]
            if meta["requires_python"] and not _specifier_satisfied(
                    meta["requires_python"], parse_version(".".join(map(str, version)))):
                raise InstallationError("wheel-requires-python-unsatisfied", chosen["path"].name)
        queue.extend(meta["requires"])
    return chosen_wheels


# ---------------------------------------------------------------------------
# source resolution (source tree / release archive / wheel directory)
# ---------------------------------------------------------------------------


def extract_archive(path, staging):
    """Safely extract a release tar.gz/zip; return the single root directory."""
    path = Path(path)
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    root_names = set()
    used = 0

    def checked(name):
        parts = _safe_member(name)
        if "__pycache__" in parts or name.endswith((".pyc", ".pyo")):
            raise InstallationError("release-bytecode-refused", name)
        root_names.add(parts[0])
        return parts

    if path.name.endswith(".zip"):
        with zipfile.ZipFile(path) as zf:
            members = zf.infolist()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS \
                    or sum(m.file_size for m in members) > MAX_ARCHIVE_BYTES:
                raise InstallationError("archive-limit-exceeded", path.name)
            for member in members:
                if member.flag_bits & 1:
                    raise InstallationError("encrypted-archive-refused", path.name)
                parts = checked(member.filename)
                mode = member.external_attr >> 16
                if stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise InstallationError("unsafe-archive-member", member.filename)
                target = staging.joinpath(*parts)
                try:
                    if member.filename.endswith("/") or stat.S_IFMT(mode) == stat.S_IFDIR:
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                        with open(target, "xb") as output:
                            output.write(zf.read(member))
                        os.chmod(target, 0o700 if mode & 0o111 else 0o600)
                except FileExistsError:
                    raise InstallationError("duplicate-archive-path", member.filename) from None
    elif path.name.endswith((".tar.gz", ".tgz")):
        with tarfile.open(path, "r:gz") as tf:
            for index, member in enumerate(tf):
                if index >= MAX_ARCHIVE_MEMBERS:
                    raise InstallationError("archive-limit-exceeded", path.name)
                if not (member.isfile() or member.isdir()):
                    raise InstallationError("unsafe-archive-member", member.name)
                used += max(member.size, 0)
                if used > MAX_ARCHIVE_BYTES:
                    raise InstallationError("archive-limit-exceeded", path.name)
                parts = checked(member.name)
                target = staging.joinpath(*parts)
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True, mode=0o700)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    try:
                        with open(target, "xb") as output:
                            shutil.copyfileobj(tf.extractfile(member), output, 1024 * 1024)
                    except FileExistsError:
                        raise InstallationError("duplicate-archive-path", member.name) from None
                    os.chmod(target, 0o700 if member.mode & 0o111 else 0o600)
    else:
        raise InstallationError("unsupported-archive", path.name)
    if len(root_names) != 1:
        raise InstallationError("ambiguous-release-root", sorted(root_names))
    return staging / root_names.pop()


class ResolvedSource:
    """A validated payload source.  Keep alive while copying payloads."""

    def __init__(self, root, manifest, kind, wheels=(), restorer=None, temp=None):
        self.root = Path(root)
        self.manifest = manifest
        self.kind = kind
        self.wheels = list(wheels)
        self.restorer = restorer  # scripts/bootstrap.py for self-contained backups
        self._temp = temp

    def close(self):
        if self._temp is not None:
            self._temp.cleanup()
            self._temp = None


def resolve_source(path, manifest_path=None):
    """Locate and validate a source.  The protocol gate runs before any
    active-path write; archives are extracted into a private temp directory."""
    path = Path(path)
    temp = None
    if path.is_file() and path.name.endswith((".zip", ".tar.gz", ".tgz")):
        temp = tempfile.TemporaryDirectory(prefix="mihomoctl-source-")
        root = extract_archive(path, Path(temp.name))
    elif path.is_file() and path.name.endswith(".whl"):
        root = path.parent
    elif path.is_dir():
        root = path
    else:
        raise InstallationError("source-not-found", str(path))
    manifest_file = Path(manifest_path).parent if manifest_path else root
    manifest = load_manifest(manifest_file)
    wheels = sorted(root.glob("*.whl"))
    kind = "wheel-dir" if wheels else "source-tree"
    restorer = root / "scripts" / "bootstrap.py"
    return ResolvedSource(root, manifest, kind, wheels,
                          restorer if restorer.is_file() else None, temp)


# ---------------------------------------------------------------------------
# paths, records, verification
# ---------------------------------------------------------------------------


def _require_install_dir(path, scope, create=False, code="installation-failed"):
    if not scope.system:
        return require_private_dir(path, create=create, code=code)
    from .trust import _check_ancestors
    _check_ancestors(Path(path), code, {0})
    if create:
        Path(path).mkdir(mode=0o755, parents=True, exist_ok=True)
    info = Path(path).lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise InstallationError(code, "system code directory must be root-owned and not writable by other accounts")
    return info


class InstallPaths:
    def __init__(self, scope):
        self.scope = scope
        self.install_root = Path("/usr/local/lib/mihomoctl") if scope.system else Path(scope.data_root) / "install"
        self.generations = self.install_root / "generations"
        self.pending = self.install_root / ".private" / "install-pending.json" if scope.system else Path(scope.data_root) / "install-pending.json"
        self.backups_root = Path(scope.state_root) / "install-backups"
        if scope.system:
            self.bin_dir = Path("/usr/local/bin")
        else:
            self.bin_dir = Path.home() / ".local" / "bin"
        self.bin_link = self.bin_dir / CONSOLE_SCRIPT


def _generation_dir(paths, name):
    if not GENERATION_RE.fullmatch(name or ""):
        raise InstallationDriftError("invalid-generation-name", name)
    return paths.generations / name


def current_target(paths):
    pointer = paths.install_root / "current"
    if not pointer.is_symlink():
        return None
    target = os.readlink(pointer)
    if not re.fullmatch(r"generations/[a-f0-9]{32}", target):
        raise InstallationDriftError("invalid-generation-pointer", target)
    return target


def current_record(scope):
    """Record dict for the active generation, or None when not installed.

    Metadata only; full verification is :func:`verify_installed`."""
    paths = InstallPaths(scope)
    target = current_target(paths)
    if target is None:
        return None
    generation = _generation_dir(paths, target.split("/", 1)[1])
    try:
        require_private_file(generation / "record.json", code="installation-drift")
        return json.loads((generation / "record.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise InstallationDriftError("generation-record-missing", str(generation)) from None


def _walk_generation(generation):
    for path in sorted(generation.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        if path.is_file() and path.suffix in (".pyc", ".pyo"):
            continue
        yield path


def verify_generation(record, paths):
    generation = _generation_dir(paths, record["generation"])
    require_trusted_dir(generation)
    _enforce_generation_ownership(generation, paths.scope)
    actual = {path.relative_to(generation).as_posix(): digest_file(path)
              for path in _walk_generation(generation)
              if path.is_file() and path.name != "record.json"}
    recorded = record["file_digests"]
    if set(actual) != set(recorded):
        raise InstallationDriftError(
            "installation-file-set-changed",
            "missing: %s; extra: %s" % (sorted(set(recorded) - set(actual))[:3],
                                        sorted(set(actual) - set(recorded))[:3]))
    for name, want in recorded.items():
        if actual[name] != want:
            raise InstallationDriftError("installed-code-modified", name,
                                         "review local customizations or rollback")


def verify_installed(scope):
    """Full verification of the active installation; returns the record."""
    paths = InstallPaths(scope)
    _require_install_dir(paths.install_root, scope, code="installation-drift")
    target = current_target(paths)
    if target is None:
        raise InstallationError("not-installed", str(paths.install_root))
    record = current_record(scope)
    if (not isinstance(record, dict) or record.get("schema") != 1
            or record.get("protocol") != PROTOCOL
            or record.get("scope") != scope.name
            or record.get("generation") != target.split("/", 1)[1]
            or record.get("install_root") != str(paths.install_root)):
        raise InstallationDriftError("record-does-not-match-this-installation", "record.json")
    verify_generation(record, paths)
    expected = str(paths.install_root / "current" / "bin" / CONSOLE_SCRIPT)
    if paths.bin_link.is_symlink():
        if os.readlink(paths.bin_link) != expected:
            raise InstallationDriftError("launcher-link-drifted", str(paths.bin_link))
    else:
        raise InstallationDriftError("launcher-link-missing", str(paths.bin_link))
    return record


def installation_status(scope):
    """Coarse status for CLI rendering; never raises on drift."""
    paths = InstallPaths(scope)
    status = {"scope": scope.name, "installed": False, "version": None,
              "generation": None, "bin_link": str(paths.bin_link), "problems": []}
    try:
        record = current_record(scope)
    except MihomoctlError as error:
        status["problems"].append(error.render())
        return status
    if record is None:
        return status
    status.update(installed=True, version=record.get("version"),
                  generation=record.get("generation"), python=record.get("python"))
    try:
        verify_installed(scope)
    except MihomoctlError as error:
        status["problems"].append(error.render())
    return status


# ---------------------------------------------------------------------------
# interpreter and smoke test
# ---------------------------------------------------------------------------


def _require_interpreter(candidate, system):
    """Python distributions use trusted symlinks; validate link and target."""
    from .trust import _check_ancestors
    owners = {0} if system else {0, os.geteuid()}
    _check_ancestors(candidate, "installation-failed", owners)
    info = candidate.lstat()
    if info.st_uid not in owners:
        raise InstallationError("python-interpreter-untrusted", str(candidate))
    require_executable_file(candidate.resolve(strict=True), code="installation-failed", as_root=system)
    venv = candidate.parent.parent
    if (venv / "pyvenv.cfg").is_file():
        for entry in [venv, *venv.rglob("*")]:
            metadata = entry.lstat()
            if metadata.st_uid not in owners or (not stat.S_ISLNK(metadata.st_mode) and metadata.st_mode & 0o022):
                raise InstallationError("python-environment-untrusted", "the interpreter environment must not be writable by another account")
            if entry.is_symlink():
                resolved = entry.resolve(strict=True)
                _check_ancestors(resolved, "installation-failed", owners)
                target = resolved.stat()
                if target.st_uid not in owners or target.st_mode & 0o022:
                    raise InstallationError("python-environment-untrusted", "untrusted interpreter symlink target")


def resolve_python(explicit=None, system=False):
    """Pick the interpreter for the installed launcher.

    Order: explicit, then /usr/bin/python3, then the running interpreter.
    Always validated for 3.10+, absoluteness and trust (as-root ancestors
    for system scope so root never loads user-writable interpreter code)."""
    candidates = [Path(explicit)] if explicit else []
    candidates += [Path("/usr/bin/python3"), Path(sys.executable)]
    failure = None
    for index, candidate in enumerate(candidates):
        last = index == len(candidates) - 1
        try:
            if not candidate.is_absolute() or not candidate.is_file() \
                    or not os.access(str(candidate), os.X_OK):
                raise InstallationError("python-interpreter-unusable", str(candidate))
            _require_interpreter(candidate, system)
            probe = subprocess.run(
                [str(candidate), "-I", "-c",
                 "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"],
                capture_output=True, timeout=30)
            if probe.returncode != 0:
                raise InstallationError("python-interpreter-unusable",
                                        "%s is older than 3.10" % candidate)
            _require_interpreter(candidate, system)
            return candidate
        except (MihomoctlError, OSError, subprocess.SubprocessError) as exc:
            failure = failure or exc
            if explicit and candidate == Path(explicit):
                raise InstallationError("python-interpreter-unusable", str(candidate),
                                        "provide a Python >= 3.10 interpreter with --python")
            if last:
                break
    raise InstallationError("python-interpreter-unusable", str(failure),
                            "install Python >= 3.10 (e.g. /usr/bin/python3)")


_IMPORT_ALIASES = {"pyyaml": "yaml"}


def interpreter_target(python):
    code = ("import json,sys,platform; print(json.dumps(dict(version=list(sys.version_info[:3]), "
            "machine=platform.machine(), libc=platform.libc_ver(), "
            "implementation=sys.implementation.name, os=sys.platform)))")
    probe = subprocess.run([str(python), "-I", "-B", "-c", code], capture_output=True,
                           text=True, timeout=SMOKE_TIMEOUT,
                           env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    try:
        target = json.loads(probe.stdout)
        if probe.returncode or target["os"] != "linux" or tuple(target["version"][:2]) < (3, 10):
            raise ValueError()
        return target
    except (ValueError, KeyError, TypeError):
        raise InstallationError("unsupported-target-interpreter", "Linux Python 3.10+ is required") from None


def check_dependencies(python, lib_dir, requirements):
    """Check the distributions and modules actually visible to the target Python."""
    requests = []
    for requirement in requirements:
        name, spec, marker = parse_requirement(requirement)
        if marker is not None:
            if "extra" in marker:
                continue
            raise InstallationError("unsupported-environment-marker", requirement)
        requests.append((name, spec, _IMPORT_ALIASES.get(name, name.replace("-", "_"))))
    code = '''import sys,json,importlib,importlib.metadata
sys.path.insert(0, sys.argv[1])
result = []
for name, spec, module_name in json.loads(sys.argv[2]):
    try:
        module = importlib.import_module(module_name)
        installed = importlib.metadata.version(name)
        module_version = getattr(module, '__version__', getattr(module, 'VERSION', installed))
        result.append(dict(name=name, version=installed, module_version=str(module_version)))
    except (ImportError, importlib.metadata.PackageNotFoundError):
        result.append(dict(name=name, missing=True))
print(json.dumps(result))
'''
    probe = subprocess.run([str(python), "-I", "-B", "-c", code, str(lib_dir), json.dumps(requests)],
                           capture_output=True, text=True, timeout=SMOKE_TIMEOUT,
                           env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
    try:
        found = json.loads(probe.stdout)
        if probe.returncode or not isinstance(found, list) or len(found) != len(requests):
            raise ValueError()
    except ValueError:
        raise InstallationError("dependency-probe-failed", "target dependency import failed",
                                "prepare a compatible local wheelhouse; no network fallback") from None
    for (name, spec, _), item in zip(requests, found):
        if item.get("missing"):
            raise InstallationError("dependency-missing", name,
                                    "provide a local --wheelhouse; no network fallback")
        version = parse_version(item["version"])
        if not _specifier_satisfied(spec, version):
            raise InstallationError("dependency-version-unsatisfied", "%s%s; found %s" % (name, spec, item["version"]),
                                    "import success does not satisfy the declared version; provide a local --wheelhouse")
        if parse_version(item["module_version"]) != version:
            raise InstallationError("dependency-module-version-disagrees", name,
                                    "the imported module differs from its distribution metadata")


def smoke_test(python, lib_dir, manifest):
    """Import the entry module and packaged modules from the staged lib.

    Runs with a stripped environment (no CLASH_*/PYTHON* influence), never
    touches the network, and for system scope only runs after the tree is
    confirmed root-owned (root never loads user-writable code)."""
    check_dependencies(python, lib_dir, manifest["dependencies"])
    entry_module, _, entry_attr = manifest["entry_point"].partition(":")
    statements = ["import sys, importlib", "sys.path.insert(0, sys.argv[1])", "import mihomoctl"]
    for package in manifest["packages"]:
        if package != PROJECT_NAME:
            statements.append("importlib.import_module(%r)" % package)
    statements.append("importlib.import_module(%r)" % entry_module)
    for requirement in manifest["dependencies"]:
        name, _, marker = parse_requirement(requirement)
        if marker is not None and "extra" in marker:
            continue
        statements.append("importlib.import_module(%r)" % _IMPORT_ALIASES.get(name, name))
    statements.append("module = importlib.import_module(%r)" % entry_module)
    statements.append("assert callable(getattr(module, %r)), 'entry point not callable'" % entry_attr)
    code = "; ".join(statements) + "; print('SMOKE-OK')"
    probe = subprocess.run([str(python), "-I", "-B", "-c", code, str(lib_dir)], capture_output=True,
                           text=True, env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"},
                           timeout=SMOKE_TIMEOUT)
    if probe.returncode != 0 or "SMOKE-OK" not in probe.stdout:
        detail = (probe.stderr or probe.stdout or "").strip().splitlines()
        raise InstallationError("installation-smoke-test-failed",
                                detail[-1] if detail else "no output",
                                "check that the wheelhouse provides the declared dependencies "
                                "(e.g. PyYAML) or install them system-wide")


# ---------------------------------------------------------------------------
# payload staging (source tree or wheels -> lib/)
# ---------------------------------------------------------------------------


def _require_source_trust(path, system=False):
    from .trust import _check_ancestors
    owners = {0} if system else {0, os.geteuid()}
    _check_ancestors(path.absolute(), "installation-failed", owners)
    entries = [path] + (list(path.rglob("*")) if path.is_dir() else [])
    for entry in entries:
        if any(p in IGNORED_SOURCE_ENTRIES or p.endswith(".egg-info") for p in entry.relative_to(path).parts):
            continue
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid not in owners or info.st_mode & 0o022:
            raise InstallationError("untrusted-installation-source", "source must be owned by the acting account and not group/other writable")


def _copy_source_packages(source_root, lib_dir, manifest):
    for relative in manifest["inventory"]["runtime_files"]:
        source = Path(source_root) / relative
        if source.is_symlink() or not source.is_file():
            raise InventoryError("runtime-source-missing-or-unsafe", relative)
        destination = Path(lib_dir) / relative
        _mkdir_owned_parents(destination.parent, 0o755)
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o644)
    init_text = (lib_dir / PROJECT_NAME / "__init__.py").read_text(encoding="utf-8")
    marker = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
    if marker is None or marker[1] != manifest["version"]:
        raise InstallationError("source-version-markers-disagree", "mihomoctl/__init__.py")


def _stage_wheels(source, lib_dir, wheelhouse, manifest, target=None):
    main_candidates = [w for w in source.wheels
                       if parse_wheel_filename(w)["name"] == PROJECT_NAME]
    if len(main_candidates) != 1:
        raise InstallationError("wheel-source-needs-exactly-one-main-wheel",
                                sorted(w.name for w in main_candidates))
    main_path = main_candidates[0]
    main_info = parse_wheel_filename(main_path)
    if main_info["version"] != manifest["version"]:
        raise InstallationError("wheel-version-disagrees-with-manifest", main_path.name)
    if not wheel_compatible_here(main_info, target):
        raise InstallationError("wheel-incompatible-with-this-interpreter", main_path.name)
    with zipfile.ZipFile(main_path) as zf:
        meta = _read_wheel_metadata(zf, main_info)
        if normalize_name(meta["name"]) != PROJECT_NAME or meta["version"] != manifest["version"]:
            raise InstallationError("wheel-metadata-disagrees-with-filename", main_path.name)
        if meta["requires_python"] and not _specifier_satisfied(
                meta["requires_python"], parse_version(".".join(map(str, target["version"] if target else sys.version_info[:3])))):
            raise InstallationError("wheel-requires-python-unsatisfied", main_path.name)
        entry = zf.read(meta["prefix"] + "entry_points.txt").decode("utf-8")
        init_text = zf.read(PROJECT_NAME + "/__init__.py").decode("utf-8")
    match = re.search(r"^\[console_scripts\]\s*$([\s\S]*?)(?:^\[|\Z)", entry, re.M)
    scripts = dict(re.findall(r"^(\S+)\s*=\s*(\S+)\s*$", match.group(1), re.M)) if match else {}
    if scripts.get(CONSOLE_SCRIPT) != manifest["entry_point"]:
        raise InstallationError("entry-point-disagrees-with-manifest", main_path.name)
    marker = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', init_text)
    if marker is None or marker[1] != manifest["version"]:
        raise InstallationError("source-version-markers-disagree", "wheel mihomoctl/__init__.py")

    with zipfile.ZipFile(main_path) as zf:
        _verify_record(zf, main_info)
        payload = {n for n in zf.namelist() if not n.endswith("/") and not n.startswith(meta["prefix"])}
        if payload != set(manifest["inventory"]["runtime_files"]):
            raise InventoryError("wheel-runtime-inventory-mismatch", "wheel modules differ from reviewed manifest")
    unpack_wheel(main_path, lib_dir, allowed_top_levels=set(manifest["packages"]))
    requirements = meta["requires"]
    base = [r for r in requirements if parse_requirement(r)[2] is None]
    if sorted(parse_requirement(r) for r in base) != sorted(parse_requirement(r) for r in manifest["dependencies"]):
        raise InstallationError("wheel-dependencies-disagree-with-manifest", main_path.name)
    if wheelhouse is not None:
        for chosen in resolve_dependency_wheels(requirements, wheelhouse, target):
            unpack_wheel(chosen["path"], lib_dir)


def stage_payload(source, lib_dir, wheelhouse, interpreter):
    target = interpreter_target(interpreter)
    if source.kind == "source-tree":
        _copy_source_packages(source.root, lib_dir, source.manifest)
        if wheelhouse and source.manifest["dependencies"]:
            for chosen in resolve_dependency_wheels(source.manifest["dependencies"], wheelhouse, target):
                unpack_wheel(chosen["path"], lib_dir)
    else:
        _stage_wheels(source, lib_dir, wheelhouse, source.manifest, target)


def _entry_stub(python, lib_dir, manifest):
    module, _, attr = manifest["entry_point"].partition(":")
    return ("#!%s -I\nimport sys\nsys.dont_write_bytecode = True\nsys.path.insert(0, %r)\nfrom %s import %s\nsys.exit(%s())\n"
            % (python, str(lib_dir), module, attr, attr))


def _enforce_generation_ownership(generation, scope):
    """Trusted-code permissions; for system scope root must own everything."""
    expected_uid = 0 if scope.system else os.geteuid()
    for path in [generation, *generation.rglob("*")]:
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise InstallationError("generation-symlink-refused", str(path))
        if info.st_uid != expected_uid:
            raise InstallationError(
                "generation-ownership-invalid" if scope.system else "generation-not-user-owned",
                "%s (uid %d, want %d)" % (path, info.st_uid, expected_uid))
        if stat.S_IMODE(info.st_mode) & 0o022:
            raise InstallationError("generation-not-group-other-writable", str(path))


def _make_readonly(generation):
    for path in [generation, *generation.rglob("*")]:
        if path.name == "record.json":
            os.chmod(path, 0o600)
        elif path.is_dir():
            os.chmod(path, 0o555)
        else:
            os.chmod(path, 0o444)
    os.chmod(generation / "bin" / CONSOLE_SCRIPT, 0o555)


def _rmtree_rw(path):
    # Readonly generations need writable containing directories for unlink.
    # Never chmod through a symlink (current points into a generation).
    for dirpath, dirs, files in os.walk(path, followlinks=False):
        os.chmod(dirpath, 0o700)
        dirs[:] = [d for d in dirs if not (Path(dirpath) / d).is_symlink()]
    shutil.rmtree(path)


def _clear_pycache(generation):
    for cache in generation.rglob("__pycache__"):
        _rmtree_rw(cache)


# ---------------------------------------------------------------------------
# transaction primitives
# ---------------------------------------------------------------------------


def _write_private_json(path, data):
    path = Path(path)
    require_private_dir(path.parent, create=True, code="installation-failed")
    payload = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode("utf-8")
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    sync_dir(path.parent)


def _read_private_json(path):
    require_private_file(path, code="installation-failed")
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _switch_current(paths, target_or_none):
    pointer = paths.install_root / "current"
    if target_or_none is None:
        pointer.unlink(missing_ok=True)
    else:
        temporary = paths.install_root / (".current-" + uuid.uuid4().hex)
        os.symlink(target_or_none, temporary)
        os.replace(temporary, pointer)
    sync_dir(paths.install_root)


def _pending_backup(paths):
    if paths.pending.exists():
        try:
            pending = _read_private_json(paths.pending)
        except MihomoctlError:
            pending = {"backup": "unreadable"}
        raise InstallationError(
            "interrupted-installation-rollback-required",
            "pending operation references backup %s" % pending.get("backup"),
            "run: ./install.sh --rollback '%s' (or scripts/bootstrap.py rollback)"
            % pending.get("backup"))


def _backup_dir(paths, kind):
    require_private_dir(paths.backups_root, create=True, code="installation-failed")
    directory = paths.backups_root / ("%s-%s-%s" % (kind, time.strftime("%Y%m%d-%H%M%S"),
                                                    uuid.uuid4().hex[:8]))
    directory.mkdir(mode=0o700)
    return directory


def _old_installation_conflict(scope, paths):
    """A 0.9.x installation must be migrated first; we never touch it."""
    if scope.system:
        return None
    legacy_root = Path.home() / ".local" / "share" / "mihomo-userctl"
    if (legacy_root / "current").exists() or (legacy_root / "common.bash").exists():
        return ("a 0.9.x installation exists at %s" % legacy_root,
                "preserve the legacy installation and use the explicit V1 migration workflow; "
                "do not invoke the old shell-modifying uninstaller")
    return None


# ---------------------------------------------------------------------------
# public operations
# ---------------------------------------------------------------------------


def install(scope, source, *, wheelhouse=None, manifest_path=None, python=None,
            dry_run=False, allow_same_version=False, allow_downgrade=False,
            lock=True, smoke=True):
    """Install (or update to) a reviewed protocol-2 source.

    ``source`` may be a source tree, a release .tar.gz/.zip archive or a
    directory containing the mihomoctl wheel (dependencies resolved from
    ``wheelhouse`` when given).  Never writes shell startup files, never
    starts services, never requires network or a proxy, and never touches
    an existing Mihomo core."""
    scope.require_mutation()
    if scope.system and os.geteuid() != 0:
        raise PermissionScopeError("scope-violation", "system installation requires root and --system")
    paths = InstallPaths(scope)
    source_obj = None
    try:
        _require_source_trust(Path(source), system=scope.system)
        if wheelhouse:
            _require_source_trust(Path(wheelhouse), system=scope.system)
        # ---- pre-write validation (protocol gate first) ----
        source_obj = resolve_source(source, manifest_path)
        verify_inventory(source_obj.root, source_obj.manifest, source_obj.kind)
        if source_obj.kind == "source-tree":
            cross_check_pyproject(source_obj.root, source_obj.manifest)
        interpreter = resolve_python(python, system=scope.system)
        # Stage only in an ephemeral private directory. Both dry-run and install
        # validate the complete payload before creating any installation paths.
        with tempfile.TemporaryDirectory(prefix="mihomoctl-preflight-") as temporary:
            lib = Path(temporary) / "lib"
            lib.mkdir(mode=0o700)
            stage_payload(source_obj, lib, wheelhouse, interpreter)
            check_dependencies(interpreter, lib, source_obj.manifest["dependencies"])
        conflict = _old_installation_conflict(scope, paths)
        if conflict:
            raise InstallationError("legacy-installation-present", conflict[0], conflict[1])
        expected_link = str(paths.install_root / "current" / "bin" / CONSOLE_SCRIPT)
        from .trust import _check_ancestors
        _check_ancestors(paths.bin_link, "installation-target-untrusted",
                         {0} if scope.system else {0, os.geteuid()})
        if paths.bin_link.is_symlink() and os.readlink(paths.bin_link) != expected_link:
            raise InstallationError("launcher-path-occupied", "refusing to replace a foreign launcher symlink")
        if paths.bin_link.exists() and not paths.bin_link.is_symlink():
            raise InstallationError("launcher-path-occupied",
                                    "%s exists and is not a mihomoctl link" % paths.bin_link,
                                    "review and remove it, then retry")
        _pending_backup(paths)

        record = None
        if (paths.install_root / "current").is_symlink():
            record = verify_installed(scope)  # refuse updates over a drifted installation
            current = parse_version(record["version"])
            new = parse_version(source_obj.manifest["version"])
            if current == new and not allow_same_version:
                raise InstallationError("same-version-already-installed", record["version"],
                                        "pass --allow-same-version to reinstall")
            if new < current and not allow_downgrade:
                raise InstallationError("downgrade-refused",
                                        "%s -> %s" % (record["version"], source_obj.manifest["version"]),
                                        "pass --allow-downgrade to force")

        if dry_run:
            return {"dry_run": True, "version": source_obj.manifest["version"],
                    "source_kind": source_obj.kind, "install_root": str(paths.install_root),
                    "bin_link": str(paths.bin_link), "python": str(interpreter),
                    "replaces": record["version"] if record else None,
                    "notes": ["no shell startup files are modified", "no services are started",
                              "no proxy or network access is required",
                              "existing Mihomo cores are not touched"]}
        with (locks.operation_lock(scope) if lock else _nulllock()):
            expected = "generations/" + record["generation"] if record else None
            if current_target(paths) != expected:
                raise InstallationError("installation-changed-retry", "installation changed while acquiring the operation lock")
            return _install_locked(scope, paths, source_obj, interpreter, wheelhouse, smoke=smoke)
    finally:
        if source_obj is not None:
            source_obj.close()


@contextmanager
def _nulllock():
    yield


def _install_locked(scope, paths, source_obj, interpreter, wheelhouse, *, smoke):
    _pending_backup(paths)
    _require_install_dir(paths.install_root, scope, create=True, code="installation-failed")
    _require_install_dir(paths.generations, scope, create=True, code="installation-failed")
    require_private_dir(paths.backups_root, create=True, code="installation-failed")

    previous = current_target(paths)
    if previous:
        verify_generation(current_record(scope), paths)

    generation = paths.generations / uuid.uuid4().hex
    generation.mkdir(mode=0o700)
    backup = _backup_dir(paths, "install")
    switched = False
    try:
        lib = generation / "lib"
        lib.mkdir(mode=0o755)
        (generation / "bin").mkdir(mode=0o755)
        stage_payload(source_obj, lib, wheelhouse, interpreter)
        stub = generation / "bin" / CONSOLE_SCRIPT
        stub.write_text(_entry_stub(interpreter, lib, source_obj.manifest), encoding="utf-8")
        os.chmod(stub, 0o755)

        _enforce_generation_ownership(generation, scope)
        if smoke:
            smoke_test(interpreter, lib, source_obj.manifest)
        _clear_pycache(generation)

        digests = {path.relative_to(generation).as_posix(): digest_file(path)
                   for path in _walk_generation(generation)
                   if path.is_file() and path.name != "record.json"}
        record = {"schema": 1, "protocol": PROTOCOL, "version": source_obj.manifest["version"],
                  "generation": generation.name, "scope": scope.name,
                  "install_root": str(paths.install_root), "bin_link": str(paths.bin_link),
                  "python": str(interpreter), "entry_point": source_obj.manifest["entry_point"],
                  "source_kind": source_obj.kind, "source_root": str(source_obj.root),
                  "file_digests": digests,
                  "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        _write_private_json(generation / "record.json", record)

        transaction = {"kind": "install", "scope": scope.name,
                       "install_root": str(paths.install_root), "bin_link": str(paths.bin_link),
                       "generation": generation.name, "previous": previous,
                       "previous_bin": os.readlink(paths.bin_link) if paths.bin_link.is_symlink() else None,
                       "backup": str(backup)}
        _write_private_json(backup / "transaction.json", transaction)
        _write_recovery(backup)
        if previous:
            shutil.copytree(paths.install_root / previous, backup / "previous-generation", symlinks=False)
        _write_private_json(paths.pending, {"kind": "install", "backup": str(backup)})
        sync_dir(paths.generations)

        _switch_current(paths, "generations/" + generation.name)
        switched = True
        for code, activate in (
                ("installation-launcher-activation-failed", lambda: _ensure_launcher(paths)),
                ("installation-permissions-activation-failed", lambda: _make_readonly(generation)),
                ("installation-post-activation-verification-failed", lambda: verify_installed(scope))):
            try:
                activate()
            except BaseException as exc:
                raise InstallationError(code, "activation failed",
                                        "run: ./install.sh --rollback '%s'" % backup) from exc
        _write_private_json(backup / "result.json",
                            {"kind": "install", "generation": generation.name,
                             "version": record["version"], "replaced": previous})
        paths.pending.unlink(missing_ok=True)
        sync_dir(paths.install_root)
        return {"version": record["version"], "generation": generation.name,
                "install_root": str(paths.install_root), "bin_link": str(paths.bin_link),
                "backup": str(backup), "python": str(interpreter), "replaced": previous,
                "source_kind": source_obj.kind,
                "notes": ["no shell startup files were modified", "no services were started"],
                "warnings": []}
    except BaseException as failure:
        if switched:
            try:
                rollback(scope, backup, lock=False)
            except BaseException:
                raise InstallationError("installation-and-rollback-failed", "activation and recovery failed", "recover with the recorded backup: %s" % backup) from failure
            raise InstallationError("installation-failed-rolled-back", "the previous installation was restored") from failure
        if generation.exists():
            _rmtree_rw(generation)
        shutil.rmtree(backup, ignore_errors=True)
        paths.pending.unlink(missing_ok=True)
        raise


def _ensure_launcher(paths):
    from .trust import _check_ancestors
    _check_ancestors(paths.bin_link, "installation-failed", {0} if paths.scope.system else {0, os.geteuid()})
    expected = str(paths.install_root / "current" / "bin" / CONSOLE_SCRIPT)
    if paths.bin_link.is_symlink() and os.readlink(paths.bin_link) == expected:
        return
    _mkdir_owned_parents(paths.bin_dir, 0o755 if paths.scope.system else 0o700)
    if paths.bin_link.is_symlink():
        paths.bin_link.unlink()
    os.symlink(expected, str(paths.bin_link))


def uninstall(scope, *, dry_run=False, lock=True):
    """Remove the installed CLI code and launcher.

    Preserves configuration, credentials, cores, subscriptions and caches;
    never touches shell startup files or services.  The previous tree is
    kept as a self-contained backup restorable by :func:`rollback`."""
    scope.require_mutation()
    if scope.system and os.geteuid() != 0:
        raise PermissionScopeError("scope-violation", "system uninstall requires root and --system")
    paths = InstallPaths(scope)
    target = None
    try:
        target = current_target(paths)
    except MihomoctlError:
        if not paths.install_root.exists():
            raise InstallationError("not-installed", str(paths.install_root)) from None
    if target is None and not (paths.install_root / "generations").is_dir():
        raise InstallationError("not-installed", str(paths.install_root))
    _pending_backup(paths)
    version = None
    problems = []
    try:
        version = verify_installed(scope)["version"]
    except MihomoctlError as error:
        problems = [error.render()]  # allow removing a drifted installation, but report it
    if dry_run:
        return {"dry_run": True, "install_root": str(paths.install_root),
                "bin_link": str(paths.bin_link), "version": version,
                "notes": ["configuration, credentials, cores and caches are preserved",
                          "no shell startup files are modified", "no services are stopped"]}

    with (locks.operation_lock(scope) if lock else _nulllock()):
        _pending_backup(paths)
        _require_install_dir(paths.install_root, scope, code="installation-failed")
        backup = _backup_dir(paths, "uninstall")
        previous_bin = os.readlink(paths.bin_link) if paths.bin_link.is_symlink() else None
        transaction = {"kind": "uninstall", "scope": scope.name,
                       "install_root": str(paths.install_root), "bin_link": str(paths.bin_link),
                       "previous_bin": previous_bin, "backup": str(backup), "version": version}
        _write_private_json(backup / "transaction.json", transaction)
        _write_private_json(paths.pending, {"kind": "uninstall", "backup": str(backup)})

        _write_recovery(backup)
        tree = backup / "tree"
        shutil.copytree(paths.install_root, tree, symlinks=True)
        manifest = sorted("%s: %s" % (p.relative_to(tree).as_posix(), digest_file(p))
                          for p in tree.rglob("*") if p.is_file())
        (backup / "tree-manifest.txt").write_text("\n".join(manifest) + "\n", encoding="utf-8")
        os.chmod(backup / "tree-manifest.txt", 0o600)

        retired = paths.install_root.with_name(".uninstalled-" + uuid.uuid4().hex[:8])
        os.rename(paths.install_root, retired)
        try:
            if paths.bin_link.is_symlink() and os.readlink(paths.bin_link).startswith(str(paths.install_root)):
                paths.bin_link.unlink()
            _rmtree_rw(retired)
        except OSError as exc:
            try:
                _rollback_uninstall(scope, paths, transaction, backup, False)
                if paths.pending.exists():
                    paths.pending.unlink()
            except BaseException:
                raise InstallationError("uninstall-and-rollback-failed", "removal and recovery failed", "recover with backup %s" % backup) from exc
            raise InstallationError("uninstall-failed-rolled-back", "the previous installation was restored") from exc
        _write_private_json(backup / "result.json", {"kind": "uninstall", "generation": target})
        paths.pending.unlink(missing_ok=True)
        sync_dir(paths.install_root.parent)
        notes = ["configuration, credentials, cores and caches were preserved",
                 "no shell startup files were modified", "no services were stopped"]
        legacy = _old_installation_conflict(scope, paths)
        if legacy:
            notes.append("legacy 0.9.x files remain at ~/.local/share/mihomo-userctl; "
                         "use mihomoctl migrate to review them")
        return {"backup": str(backup), "version": version,
                "bin_link": str(paths.bin_link), "problems": problems, "notes": notes}


def rollback(scope, backup, *, dry_run=False, lock=True):
    """Restore the state recorded in a self-contained backup directory."""
    scope.require_mutation()
    backup = Path(backup).absolute()
    require_private_dir(backup, code="installation-failed")
    transaction = _read_private_json(backup / "transaction.json")
    paths = InstallPaths(scope)
    if transaction.get("install_root") != str(paths.install_root) or transaction.get("bin_link") != str(paths.bin_link):
        raise InstallationError("backup-paths-do-not-match-scope", str(backup))
    previous = transaction.get("previous")
    if previous is not None and not re.fullmatch(r"generations/[a-f0-9]{32}", previous):
        raise InstallationError("invalid-backup-generation", "unsafe previous generation")
    kind = transaction.get("kind")
    if kind not in ("install", "uninstall") or transaction.get("scope") != scope.name:
        raise InstallationError("backup-does-not-match-scope", str(backup))
    done = False
    result_file = backup / "result.json"
    if result_file.exists():
        done = _read_private_json(result_file).get("files") == "ROLLED_BACK"
    if dry_run:
        return {"dry_run": True, "kind": kind, "backup": str(backup), "already_restored": done}

    with (locks.operation_lock(scope) if lock else _nulllock()):
        if paths.pending.exists():
            pending = _read_private_json(paths.pending)
            if pending.get("backup") != str(backup):
                raise InstallationError(
                    "stale-backup", "a newer interrupted operation references %s"
                    % pending.get("backup"),
                    "roll back that operation first: ./install.sh --rollback '%s'"
                    % pending.get("backup"))
        if kind == "install":
            _rollback_install(scope, paths, transaction, backup, done)
        else:
            _rollback_uninstall(scope, paths, transaction, backup, done)
        _write_private_json(result_file, {"files": "ROLLED_BACK", "kind": kind})
        if paths.pending.exists():
            paths.pending.unlink(missing_ok=True)
    return {"backup": str(backup), "kind": kind, "restored": True}


def _rollback_install(scope, paths, transaction, backup, done):
    generation = transaction["generation"]
    previous = transaction["previous"]
    active = None
    if paths.install_root.exists():
        try:
            active = current_target(paths)
        except InstallationDriftError:
            active = "unknown"
    if active is not None and active != "generations/" + generation and active != previous:
        raise InstallationError("stale-backup", "current generation is %s" % active,
                                "a later installation happened; only its own backup can roll back")
    if active is None and done:
        return  # idempotent re-run
    if previous and not (paths.install_root / previous).is_dir():
        saved = backup / "previous-generation"
        if not saved.is_dir() or saved.is_symlink():
            raise InstallationError("backup-tree-missing", "the previous generation is unavailable")
        shutil.copytree(saved, paths.install_root / previous, symlinks=False)
    if active == "generations/" + generation:
        _switch_current(paths, previous)
    gen_dir = _generation_dir(paths, generation)
    if gen_dir.exists():
        _rmtree_rw(gen_dir)
    if previous is None:
        paths.bin_link.unlink(missing_ok=True)
        if paths.generations.is_dir() and not any(paths.generations.iterdir()):
            _rmtree_rw(paths.install_root)
    else:
        _ensure_launcher(paths)
        verify_installed(scope)


def _rollback_uninstall(scope, paths, transaction, backup, done):
    if paths.install_root.exists():
        if done:
            verify_installed(scope)
            return
        raise InstallationError("stale-backup",
                                "a new installation exists at %s" % paths.install_root)
    tree = backup / "tree"
    if not tree.is_dir():
        if done:
            return
        raise InstallationError("backup-tree-missing", str(tree))
    _require_install_dir(paths.install_root.parent, scope, create=True, code="installation-failed")
    shutil.copytree(tree, paths.install_root, symlinks=True)
    if current_record(scope) is None or not (paths.install_root / "current").is_symlink():
        raise InstallationError("backup-tree-inconsistent", "no active generation after restore")
    _ensure_launcher(paths)
    verify_installed(scope)


def prune_generations(scope, keep=3, *, lock=True):
    """Delete old generations, always keeping the active one and the newest
    ``keep`` others.  Returns the removed generation names."""
    scope.require_mutation()
    paths = InstallPaths(scope)
    with (locks.operation_lock(scope) if lock else _nulllock()):
        target = current_target(paths)
        if target is None:
            raise InstallationError("not-installed", str(paths.install_root))
        active = target.split("/", 1)[1]
        entries = []
        for directory in paths.generations.iterdir():
            if not GENERATION_RE.fullmatch(directory.name):
                raise InstallationDriftError("unknown-generation-directory", directory.name)
            require_trusted_dir(directory)
            record_path = directory / "record.json"
            created = record_path.stat().st_mtime if record_path.exists() else 0
            entries.append((created, directory.name))
        entries.sort(reverse=True)
        others = [name for _, name in entries if name != active]
        removed = []
        for name in others[keep:]:
            _rmtree_rw(_generation_dir(paths, name))
            removed.append(name)
        return removed


def update(scope, source=None, **kwargs):
    """Offline explicit-source update using the same transactional installer."""
    if source is None:
        raise InstallationError("update-source-required", "provide a reviewed local release source")
    return install(scope, source, **kwargs)


def failure_codes(error):
    """Public diagnostic codes only; never expose exception details or paths."""
    allowed = frozenset({
        "installation-failed-rolled-back", "installation-and-rollback-failed",
        "installation-launcher-activation-failed", "installation-permissions-activation-failed",
        "installation-post-activation-verification-failed", "installation-failed",
        "installation-target-untrusted", "installation-drift", "runtime-untrusted",
        "installation-file-set-changed", "installed-code-modified", "launcher-link-drifted",
        "launcher-link-missing", "generation-not-group-other-writable",
        "generation-symlink-refused", "generation-ownership-invalid", "generation-not-user-owned",
        "record-does-not-match-this-installation", "generation-record-missing"})
    codes = []
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, MihomoctlError) and error.code in allowed:
            code = error.code
        elif isinstance(error, OSError):
            code = "io-error"
        else:
            code = "unclassified-error"
        if code not in codes:
            codes.append(code)
        error = error.__cause__
    return codes


def _write_recovery(backup):
    """Bundle the small installer engine so recovery does not need the source."""
    package = backup / "recovery" / "mihomoctl"
    _mkdir_owned_parents(package, 0o700)
    for name in ("__init__.py", "installation.py", "scope.py", "trust.py", "errors.py", "locks.py"):
        shutil.copyfile(Path(__file__).parent / name, package / name)
        os.chmod(package / name, 0o600)
    bootstrap = Path(__file__).with_name("bootstrap.py")
    if not bootstrap.is_file():
        raise InstallationError("recovery-bootstrap-missing", "install from a complete reviewed release")
    shutil.copyfile(bootstrap, backup / "bootstrap.py")
    os.chmod(backup / "bootstrap.py", 0o600)
