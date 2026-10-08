"""User-level controller component; no global proxy or daemon."""
import os
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

def apply_policy(config, original, updated, home_dir=None):
    if original == updated:
        return {"state": "unchanged", "service": "unchanged"}
    home = Path(home_dir or str(Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share"))) / "mihomo"))
    private(home, True)
    core = os.environ.get("MIHOMO_CORE_BIN") or shutil.which("mihomo")
    if not core:
        raise ControlError("mihomo-executable-missing")
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
        private(config)
        if config.read_bytes().decode("utf-8") != original:
            raise ControlError("config-changed-during-policy-edit")
        backup = config.with_name(config.name + ".before-policy-" + secrets.token_hex(8))
        files.atomic_bytes(backup, original.encode())
        try:
            files.atomic_bytes(config, updated.encode())
        except OSError:
            # replace may have succeeded before a directory fsync failed.
            # Restore only our exact candidate, never a later concurrent edit.
            try:
                active = config.read_bytes()
                if active == updated.encode():
                    files.atomic_bytes(config, original.encode())
                elif active != original.encode():
                    raise ControlError("config-write-failed-concurrent-edit-preserved")
            except OSError:
                raise ControlError("config-write-failed-rollback-incomplete-use-private-backup") from None
            raise ControlError("config-write-failed-original-restored") from None
        return {"state": "restart-required", "backup": str(backup), "service": "unchanged"}
    finally:
        candidate.unlink(missing_ok=True)
