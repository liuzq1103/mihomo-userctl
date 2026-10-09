"""User-level controller component; no global proxy or daemon."""
import os
import hashlib
from pathlib import Path
import secrets
import shutil
import subprocess
import tempfile
try:
    from . import acceptance, install_support as files
except ImportError:
    import acceptance
    import install_support as files
try:
    from .controller_types import ControlError
    from .controller_config import private
except ImportError:
    from controller_types import ControlError
    from controller_config import private

def find_core():
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if core:
        return core
    local = Path.home() / ".local/bin/mihomo"
    if local.is_file() and os.access(local, os.X_OK) and local.stat().st_uid == os.getuid():
        return str(local)
    raise ControlError("mihomo-executable-missing")


def validate_candidate(config, home_dir, updated):
    home = Path(home_dir or str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo"))
    core = find_core()
    private(home, True)
    fd, name = tempfile.mkstemp(prefix="policy-check-", suffix=".yaml", dir=config.parent)
    os.close(fd)
    candidate = Path(name)
    try:
        files.atomic_bytes(candidate, updated.encode())
        result = subprocess.run([core, "-t", "-d", str(home), "-f", str(candidate)],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=acceptance.clean_environment(), timeout=30)
        if result.returncode:
            raise ControlError("mihomo-config-validation-failed", 1)
    finally:
        candidate.unlink(missing_ok=True)


def apply_policy(config, original, updated, home_dir=None):
    if original == updated:
        return {"state": "unchanged", "service": "unchanged"}
    validate_candidate(config, home_dir, updated)
    private(config)
    if config.read_bytes().decode("utf-8") != original:
        raise ControlError("config-changed-during-policy-edit")
    backup = config.with_name(config.name + ".before-policy-" + secrets.token_hex(8))
    files.atomic_bytes(backup, original.encode())
    try:
        files.atomic_bytes(config, updated.encode())
    except OSError:
        try:
            active = config.read_bytes()
            if active == updated.encode():
                files.atomic_bytes(config, original.encode())
            elif active != original.encode():
                raise ControlError("config-write-failed-concurrent-edit-preserved")
        except OSError:
            raise ControlError("config-write-failed-rollback-incomplete-use-private-backup") from None
        raise ControlError("config-write-failed-original-restored") from None
    result = {"state": "restart-required", "backup": str(backup), "service": "unchanged"}
    # A receipt survives closing the TUI before restarting. It contains no credentials.
    receipt = dict(result, sha256=hashlib.sha256(updated.encode()).hexdigest(),
                   backup_sha256=hashlib.sha256(original.encode()).hexdigest())
    try:
        files.write_json(config.with_name(config.name + ".userctl-state.json"), receipt)
    except OSError:
        result["warning"] = "restart-receipt-unavailable"
    return result


def pending_state(config):
    path = config.with_name(config.name + ".userctl-state.json")
    if not path.exists():
        return {}
    import json
    private(path)
    if path.stat().st_size > 4096:
        raise ControlError("configuration-receipt-invalid")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlError("configuration-receipt-invalid")
    backup = Path(value.get("backup", ""))
    if backup.parent != config.parent or not backup.name.startswith(config.name + ".before-policy-"):
        raise ControlError("configuration-receipt-invalid")
    private(config)
    private(backup)
    if (hashlib.sha256(config.read_bytes()).hexdigest() != value.get("sha256") or
            hashlib.sha256(backup.read_bytes()).hexdigest() != value.get("backup_sha256")):
        return {}
    return value
