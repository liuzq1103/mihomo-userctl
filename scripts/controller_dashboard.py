"""User-level controller component; no global proxy or daemon."""
import hashlib
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import stat
import subprocess
import tempfile
import zipfile
try:
    from . import acceptance, install_support as files
except ImportError:
    import acceptance
    import install_support as files
try:
    from .controller_types import ControlError
    from .controller_config import private, read_config, patch_config, endpoint
except ImportError:
    from controller_types import ControlError
    from controller_config import private, read_config, patch_config, endpoint

def choose_port(requested):
    if requested is not None and not 1024 <= requested <= 65535:
        raise ControlError("controller-port-out-of-range")
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", requested or 0))
        except OSError:
            raise ControlError("controller-port-in-use", 1) from None
        return probe.getsockname()[1]


def archive_ui(archive, checksum, destination):
    if not checksum or not re.fullmatch(r"[a-f0-9]{64}", checksum):
        raise ControlError("dashboard-requires-pinned-sha256")
    if archive.is_symlink() or archive.stat().st_size > 32 * 1024 * 1024:
        raise ControlError("dashboard-archive-invalid")
    if hashlib.sha256(archive.read_bytes()).hexdigest() != checksum:
        raise ControlError("dashboard-sha256-mismatch")
    with zipfile.ZipFile(archive) as bundle:
        entries = bundle.infolist()
        roots = [e.filename[:-10] for e in entries if e.filename.endswith("index.html")]
        if len(roots) != 1 or len(entries) > 10000:
            raise ControlError("dashboard-archive-needs-one-index-html")
        root, used, seen = roots[0], 0, set()
        for entry in entries:
            name = entry.filename
            if (name.startswith("/") or "\\" in name or ":" in name or ".." in Path(name).parts
                    or stat.S_IFMT(entry.external_attr >> 16) not in (0, stat.S_IFREG, stat.S_IFDIR) or name in seen):
                raise ControlError("dashboard-archive-unsafe-path")
            seen.add(name)
            used += entry.file_size
            if used > 64 * 1024 * 1024:
                raise ControlError("dashboard-archive-too-large")
            if entry.is_dir() or not name.startswith(root):
                continue
            target = destination / name[len(root):]
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with bundle.open(entry) as source:
                data = source.read(64 * 1024 * 1024 + 1)
            if len(data) != entry.file_size:
                raise ControlError("dashboard-archive-invalid-size")
            files.atomic_bytes(target, data)


def setup(args, config):
    text, data, tree = read_config(config)
    if data.get("external-controller"):
        endpoint(data)  # Never silently replace an exposed or unprotected API.
    home = Path(args.home_dir or os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    if not args.home_dir:
        home /= "mihomo"
    private(home, True)
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if not core:
        raise ControlError("mihomo-executable-missing")
    if args.archive is None and data.get("external-ui"):
        raise ControlError("existing-dashboard-preserved-use-explicit-archive-to-replace")
    port = choose_port(args.port)
    if port in (data.get("mixed-port"), data.get("port"), data.get("socks-port")):
        raise ControlError("controller-port-conflicts-with-proxy")
    token = data.get("secret") if data.get("external-controller") else secrets.token_urlsafe(32)
    ui = Path(tempfile.mkdtemp(prefix="userctl-ui-", dir=home))
    candidate = None
    committed = False
    try:
        if args.archive:
            archive_ui(Path(args.archive), args.sha256, ui)
        else:
            bundled = Path(__file__).with_name("dashboard.html")
            files.atomic_bytes(ui / "index.html", bundled.read_bytes())
        changes = {"external-controller": "127.0.0.1:" + str(port), "secret": token,
                   "external-ui": str(ui), "external-ui-name": "", "external-ui-url": "",
                   "external-controller-cors": {"allow-origins": [], "allow-private-network": False}}
        if any(data.get(k) for k in ("external-controller-tls", "external-controller-unix", "external-controller-pipe", "external-doh-server")):
            raise ControlError("additional-controller-listeners-not-supported")
        profile = data.get("profile", {})
        if not isinstance(profile, dict):
            raise ControlError("config-profile-invalid")
        changes["profile"] = dict(profile, **{"store-selected": True})
        updated = patch_config(text, tree, changes).encode()
        fd, name = tempfile.mkstemp(prefix="controller-check-", suffix=".yaml", dir=config.parent)
        os.close(fd)
        candidate = Path(name)
        files.atomic_bytes(candidate, updated)
        process = subprocess.run([core, "-t", "-d", str(home), "-f", str(candidate)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 env=acceptance.clean_environment(), timeout=30)
        if process.returncode:
            raise ControlError("mihomo-config-validation-failed", 1)
        private(config)
        if config.read_bytes().decode("utf-8") != text:
            raise ControlError("config-changed-during-setup")
        backup = config.with_name(config.name + ".before-controller-" + secrets.token_hex(8))
        files.atomic_bytes(backup, text.encode())
        files.atomic_bytes(config, updated)
        committed = True
        return {"endpoint": "127.0.0.1:" + str(port), "backup": str(backup),
                "state": "restart-required", "service": "unchanged", "ui": "external" if args.archive else "bundled"}
    finally:
        if candidate is not None:
            candidate.unlink(missing_ok=True)
        # A directory fsync can fail after os.replace has committed the file.
        # Do not remove assets that the active config already references.
        if not committed and not (candidate is not None and config.read_bytes() == updated):
            shutil.rmtree(ui)
