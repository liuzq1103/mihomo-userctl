"""Core install/update/adopt: explicit, fixed-version, checksum-gated.

Supply chain tiers (design-reference 6.3):
- L2 maintainer pin (mihomo-digests.json) is the trust anchor: known
  versions verify against it and mismatch is a hard FAIL.
- Unknown versions require an explicit --sha256; there is no bypass.
- L1 transport: Content-Length bound before download.
- L4 structure: gzip decompression bounded; ELF magic + e_machine must
  match the request; ``mihomo -v`` version string must equal the tag.
Provenance is recorded without ever claiming upstream signatures.
Download/verify completes before any activation; failed activation
restores the prior binary/config.  The CLI never implicitly downloads
or replaces a core.
"""

import gzip
import hashlib
import http.client
import io
import json
import os
import platform
import struct
import subprocess
import tempfile
import time
import urllib.error
import zlib
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from . import digests
from .config import load_manager, render_manager
from .errors import RollbackFailedError, SupplyChainError, ValidationError
from .lifecycle import runner
from .transaction import run_transaction
from .trust import require_executable_file, require_private_dir, require_private_file

RELEASE_BASE = "https://github.com/MetaCubeX/mihomo/releases/download"
DOWNLOAD_HOSTS = ("github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com")
MAX_ASSET_BYTES = 128 * 1024 * 1024
MAX_CORE_BYTES = 512 * 1024 * 1024

_ARCH = {"x86_64": "amd64", "aarch64": "arm64", "armv7l": "armv7"}
_ELF_MACHINES = {3: 386, 62: "amd64", 183: "arm64", 40: "armv7"}


def _asset_name(version):
    machine = platform.machine().lower()
    arch = _ARCH.get(machine)
    if arch is None:
        raise SupplyChainError("core-arch-unsupported", machine)
    variant = "amd64-compatible" if arch == "amd64" else arch
    return "mihomo-linux-%s-%s.gz" % (variant, version)


def _asset_url(version, asset):
    return "%s/%s/%s" % (RELEASE_BASE, version, asset)


def _download(url, expected_size=None):
    _validate_download_url(url)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "mihomoctl-core-install"})
        opener = urllib.request.build_opener(_RedirectGuard())
        with opener.open(request, timeout=60) as response:
            if response.status == 200:
                length = response.headers.get("Content-Length")
                if length is not None:
                    if not length.isdecimal():
                        raise SupplyChainError("asset-size-invalid")
                    length = int(length)
                    if length <= 0 or length > MAX_ASSET_BYTES:
                        raise SupplyChainError("asset-too-large", "%d bytes" % length)
                    if expected_size is not None and length != expected_size:
                        raise SupplyChainError("asset-size-mismatch", "%d != %d" % (length, expected_size))
                data = response.read(MAX_ASSET_BYTES + 1)
                if len(data) > MAX_ASSET_BYTES:
                    raise SupplyChainError("asset-too-large")
                if length is not None and len(data) != length:
                    raise SupplyChainError("asset-size-mismatch", "incomplete transfer")
                if expected_size is not None and len(data) != expected_size:
                    raise SupplyChainError("asset-size-mismatch", "unexpected asset size")
                return data
            raise SupplyChainError("download-failed", "unexpected response status")
    except (urllib.error.URLError, OSError, ValueError, http.client.HTTPException):
        raise SupplyChainError("download-failed", "official asset transfer could not be verified") from None


def _validate_download_url(value):
    url = urlsplit(value)
    if (url.scheme != "https" or url.hostname not in DOWNLOAD_HOSTS or url.username
            or url.password or url.port not in (None, 443)):
        raise SupplyChainError("non-official-download")


class _RedirectGuard(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _verify_gzip(data, version):
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
            core = compressed.read(MAX_CORE_BYTES + 1)
    except (OSError, EOFError, zlib.error):
        raise SupplyChainError("asset-corrupt", "invalid gzip stream") from None
    if len(core) > MAX_CORE_BYTES:
        raise SupplyChainError("core-too-large", "%d bytes" % len(core))
    if len(core) < 52 or not core.startswith(b"\x7fELF"):
        raise SupplyChainError("core-not-elf", "missing ELF header")
    elf_class, endian = core[4], core[5]
    machine = platform.machine().lower()
    expected_class = 1 if machine == "armv7l" else 2
    if elf_class != expected_class or endian != 1:
        raise SupplyChainError("core-not-elf", "incompatible ELF class or byte order")
    e_machine = struct.unpack_from("<H", core, 18)[0]
    expected = {"x86_64": 62, "aarch64": 183, "armv7l": 40}.get(machine)
    if expected is None or e_machine != expected:
        raise SupplyChainError("core-arch-mismatch",
                               "e_machine=%d expected=%s" % (e_machine, expected))
    return core


def _run_version(binary, as_uid=None):
    result = runner.run_core(binary, ["-v"], timeout=20, as_uid=as_uid)
    if result.returncode != 0:
        raise SupplyChainError("core-version-failed", "exit %d" % result.returncode)
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


def _version_matches(output, version):
    tokens = []
    import re
    for token in re.findall(r"v?\d+\.\d+\.\d+", output or ""):
        tokens.append(token.lstrip("v"))
    return version.lstrip("v") in tokens


def install(scope, version, sha256=None, dry_run=False, force=False):
    """Install a pinned core version into managed storage.

    Known versions verify against the maintainer pin table; unknown
    versions require an explicit sha256.  Nothing is activated until the
    candidate fully verifies."""
    import re
    scope.require_mutation()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", version or ""):
        raise ValidationError("core-version-invalid", "expected vX.Y.Z")
    asset = _asset_name(version)
    url = _asset_url(version, asset)
    pin = digests.lookup(version, asset)
    provenance = None
    if pin is not None:
        if sha256 is not None and sha256 != pin["sha256"]:
            raise SupplyChainError("digest-mismatch",
                                   "provided sha256 differs from the maintainer pin")
        expected = pin["sha256"]
        provenance = "maintainer-pin"
    else:
        if not sha256 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise SupplyChainError("digest-required",
                                   "version %s is not pinned; --sha256 is mandatory" % version,
                                   remediation="review the asset digest yourself and pass --sha256")
        expected = sha256
        provenance = "user-provided"
    plan = {"version": version, "asset": asset, "url": url,
            "sha256": expected, "provenance": provenance}
    if dry_run:
        return {"dry_run": True, "plan": plan}
    data = _download(url)
    digest = hashlib.sha256(data).hexdigest()
    if digest != expected:
        raise SupplyChainError("digest-mismatch",
                               "downloaded sha256 %s != %s (%s)" % (digest, expected, provenance))
    core = _verify_gzip(data, version)
    with tempfile.TemporaryDirectory(prefix="mihomoctl-core-") as folder:
        staged = Path(folder)
        if scope.system:
            staged.chmod(0o711)  # executable bytes only; root owns the directory
        binary = staged / "mihomo"
        binary.write_bytes(core)
        os.chmod(str(binary), 0o755)
        require_executable_file(binary, as_root=scope.system)
        output = _run_version(binary, as_uid=_safe_check_uid(scope))
        if not _version_matches(output, version):
            raise SupplyChainError("core-version-mismatch", "binary does not report the requested version")
        from .locks import operation_lock
        from .transaction import Transaction
        with operation_lock(scope):
            _prepare_core_directories(scope, version)
            destination = scope.cores_root / version / "mihomo"
            if destination.exists() and not force:
                raise SupplyChainError("core-already-installed", "use an explicit replacement operation")
            manager = load_manager(scope) if scope.manager_path.exists() else None
            if manager:
                runner.validate_config(binary, Path(manager.core.config).read_text(encoding="utf-8"),
                                       scope.core_home, as_uid=_safe_check_uid(scope))
            receipt = _read_receipt(scope)
            receipt["installs"].append({"version": version, "binary": str(destination),
                                       "sha256": digest, "binary_sha256": hashlib.sha256(core).hexdigest(),
                                       "url": url, "provenance": provenance,
                                       "note": "digest comparison; not an upstream signature",
                                       "installed_at": int(time.time())})
            tx = Transaction(scope, "core-install")
            _publish_and_activate(scope, tx, manager, destination, core=core, receipt=receipt)
        return {"version": version, "binary": str(destination), "sha256": digest,
                "provenance": provenance, "activated": manager is not None}


def _safe_check_uid(scope):
    if scope.system:
        import pwd
        try:
            uid = pwd.getpwnam("mihomoctl").pw_uid
        except KeyError:
            uid = pwd.getpwnam("nobody").pw_uid
        if uid == 0:
            raise SupplyChainError("core-validator-identity-invalid")
        return uid
    return None


def _read_receipt(scope):
    manifest = scope.cores_root / "manifest.json"
    data = {"format": 1, "installs": []}
    if manifest.exists() or manifest.is_symlink():
        require_private_file(manifest, code="core-receipt-invalid")
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise SupplyChainError("core-receipt-invalid") from None
        if (not isinstance(data, dict) or data.get("format") != 1
                or not isinstance(data.get("installs"), list)):
            raise SupplyChainError("core-receipt-invalid")
    return data


def _prepare_core_directories(scope, version):
    if not scope.system:
        require_private_dir(scope.cores_root, create=True)
        require_private_dir(scope.cores_root / version, create=True)
        return
    from .lifecycle.systemd import ensure_service_account
    from .trust import _check_ancestors
    account = ensure_service_account(create=True)
    for path in (scope.data_root, scope.cores_root, scope.cores_root / version):
        _check_ancestors(path, "core-storage-unsafe", owners={0})
        if path.is_symlink():
            raise SupplyChainError("core-storage-unsafe")
        path.mkdir(mode=0o750, exist_ok=True)
        info = path.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SupplyChainError("core-storage-unsafe")
        os.chown(path, 0, account.pw_gid)
        path.chmod(0o750)


def _application(scope):
    from .app import Application
    return Application(system=scope.system, config_dir=str(scope.config_root))


def _publish_and_activate(scope, tx, manager, binary, core=None, receipt=None):
    """Publish binary, receipt, binding and unit together; restore a running old core on failure."""
    from . import envelope
    from .lifecycle import systemd
    app = _application(scope)
    old_backend = None
    was_running = False
    stopped = False
    attempted_start = False
    new_backend = None
    if manager is not None:
        _old, endpoints, controller, _profile, _cfg = app.resolve()
        old_backend = app._backend(manager, endpoints, controller)
        was_running = bool(old_backend.status().get("running"))
    unit = systemd.unit_path(scope)
    try:
        if manager and manager.core.backend == "systemd" and unit.exists():
            if unit.is_symlink() or not unit.read_text(encoding="utf-8").startswith(systemd.UNIT_MARKER + "\n"):
                raise SupplyChainError("core-unit-not-managed")
        if was_running:
            stopped = True
            old_backend.stop()
        if core is not None:
            tx.write_bytes(binary, core, mode=0o755)
        if receipt is not None:
            tx.write_text(scope.cores_root / "manifest.json", json.dumps(receipt, sort_keys=True) + "\n")
        if manager:
            manager.core.binary = str(binary)
            tx.write_text(scope.manager_path, render_manager(manager))
            if manager.core.backend == "systemd" and unit.exists():
                tx.write_text(unit, systemd.unit_text(manager, scope), mode=0o644 if scope.system else 0o600)
                systemd._systemctl(scope, "daemon-reload")
            if was_running:
                _new, endpoints, controller, _profile, _cfg = app.resolve()
                new_backend = app._backend(_new, endpoints, controller)
                attempted_start = True
                new_backend.start(health_check=lambda: (
                    envelope.combine_checks(app.health()) == envelope.PASS, "local health gate"))
        tx.commit()
    except BaseException as original:
        if attempted_start and new_backend is not None:
            try:
                new_backend.stop()
            except Exception:
                # Restore files first; failure to restore runtime below is reported separately.
                pass
        tx.rollback()
        if stopped:
            try:
                if manager.core.backend == "systemd":
                    systemd._systemctl(scope, "daemon-reload")
                old, endpoints, controller, _profile, _cfg = app.resolve()
                restored = app._backend(old, endpoints, controller)
                if not restored.status().get("running"):
                    restored.start(health_check=lambda: (
                        envelope.combine_checks(app.health()) == envelope.PASS, "restored health gate"))
            except Exception as recovery:
                raise RollbackFailedError("core-runtime-rollback-failed",
                                          "previous files restored but runtime recovery failed") from original
        raise


def _activate(scope, binary, validate=True, dry_run=False):
    """Repoint manager.yaml at the installed binary (transactional)."""
    scope.require_mutation()
    require_executable_file(binary, as_root=scope.system)
    from .locks import operation_lock
    from .transaction import Transaction
    if dry_run:
        return {"binary": str(binary), "dry_run": True}
    with operation_lock(scope):
        manager = load_manager(scope)
        if validate:
            config_text = Path(manager.core.config).read_text(encoding="utf-8")
            uid = _safe_check_uid(scope)
            runner.validate_config(binary, config_text, scope.core_home, as_uid=uid)
        old = manager.core.binary
        tx = Transaction(scope, "core-activate")
        _publish_and_activate(scope, tx, manager, binary)
        return old


def adopt(scope, path, validate=True):
    """Reference an existing trusted binary read-only (adopted)."""
    scope.require_mutation()
    binary = Path(path)
    require_executable_file(binary, as_root=scope.system)
    output = _run_version(binary, as_uid=_safe_check_uid(scope))
    _activate(scope, binary, validate=validate)
    return {"adopted": str(binary), "version": output}


def installed(scope):
    manifest = scope.cores_root / "manifest.json"
    rows = []
    if manifest.exists():
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            rows = data.get("installs", [])
        except (OSError, ValueError):
            rows = []
    manager_path = scope.manager_path
    active = None
    if manager_path.exists():
        try:
            active = load_manager(scope).core.binary
        except Exception:
            active = None
    return {"installs": rows, "active": active}
