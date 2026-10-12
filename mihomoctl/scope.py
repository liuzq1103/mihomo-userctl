"""Scope resolution: user (XDG) and system (fixed) path roots.

Rules (architecture-v1):
- One managed Mihomo runtime per scope.
- User paths respect XDG config/data/state/cache roots; a private
  state-directory runtime fallback is used when XDG_RUNTIME_DIR is absent.
- System paths are fixed constants; never discovered from HOME, CWD or
  untrusted environment variables.
"""

import os
from pathlib import Path

from .errors import ConfigError, PermissionScopeError

SYSTEM_CONFIG = "/etc/mihomoctl"
SYSTEM_DATA = "/var/lib/mihomoctl"
SYSTEM_CACHE = "/var/cache/mihomoctl"
SYSTEM_RUNTIME = "/run/mihomoctl"


def _xdg(name, default):
    value = os.environ.get(name)
    if value:
        path = Path(value)
        if not path.is_absolute():
            raise ConfigError("config-invalid", "%s must be absolute" % name)
        return path
    return Path.home() / default


class Scope:
    """Resolved path roots for one scope. Construction performs no changes."""

    def __init__(self, system=False, config_dir=None):
        self.system = bool(system)
        self.config_dir_override = Path(config_dir).expanduser() if config_dir else None
        if self.config_dir_override is not None and not self.config_dir_override.is_absolute():
            raise ConfigError("config-invalid", "config_dir must be absolute")
        if self.system:
            self.config_root = self.config_dir_override or Path(SYSTEM_CONFIG)
            self.data_root = Path(SYSTEM_DATA)
            self.cache_root = Path(SYSTEM_CACHE)
            self.state_root = Path(SYSTEM_DATA)
            self.runtime_root = Path(SYSTEM_RUNTIME)
        else:
            self.config_root = self.config_dir_override or _xdg("XDG_CONFIG_HOME", Path(".config")) / "mihomoctl"
            self.data_root = _xdg("XDG_DATA_HOME", Path(".local/share")) / "mihomoctl"
            self.state_root = _xdg("XDG_STATE_HOME", Path(".local/state")) / "mihomoctl"
            self.cache_root = _xdg("XDG_CACHE_HOME", Path(".cache")) / "mihomoctl"
            runtime = os.environ.get("XDG_RUNTIME_DIR")
            if runtime and Path(runtime).is_absolute():
                self.runtime_root = Path(runtime) / "mihomoctl"
            else:
                # Private fallback inside the state root (never world temp dirs).
                self.runtime_root = self.state_root / "runtime"

    @property
    def name(self):
        return "system" if self.system else "user"

    # ---- well-known files -------------------------------------------------
    @property
    def manager_path(self):
        return self.config_root / "manager.yaml"

    @property
    def credentials_dir(self):
        return self.config_root / "profiles"

    @property
    def cores_root(self):
        return self.data_root / "cores"

    @property
    def core_home(self):
        """Mihomo home dir (-d): geodata and runtime downloads."""
        return self.data_root / "core-home"

    @property
    def runtime_state(self):
        return self.state_root / "runtime.json"

    @property
    def logs_dir(self):
        return self.state_root / "logs"

    @property
    def integration_dir(self):
        return self.config_root / "integration"

    @property
    def adapters_dir(self):
        return self.config_root / "adapters"

    @property
    def backups_root(self):
        return self.state_root / "backups"

    @property
    def staging_root(self):
        return self.cache_root / "staging"

    @property
    def tun_receipt(self):
        # The system data/state root is 0750 so the dedicated core account can
        # traverse core-home. Authorization remains in a root-private 0700
        # child, including reconciliation writes outside a Transaction.
        return self.state_root / "tun" / "authorization.json"

    def is_private_user_path(self, path):
        """True when ``path`` lives inside this user scope's private roots."""
        path = Path(path).expanduser().resolve()
        for root in (self.config_root, self.data_root, self.state_root, self.cache_root):
            try:
                path.relative_to(root.resolve())
                return True
            except ValueError:
                continue
        return False

    def require_mutation(self):
        if not hasattr(os, 'geteuid'):
            raise PermissionScopeError('linux-required', 'production mutations require Linux')
        if self.system and os.geteuid() != 0:
            raise PermissionScopeError('system-requires-root', '--system mutations require UID 0')
        if not self.system and os.geteuid() == 0:
            raise PermissionScopeError('root-requires-system', 'UID 0 must explicitly select --system for mutations')

    def context(self):
        return {
            "scope": self.name,
            "config_dir": str(self.config_root),
            "manager": str(self.manager_path),
            "data_dir": str(self.data_root),
            "state_dir": str(self.state_root),
            "cache_dir": str(self.cache_root),
            "runtime_dir": str(self.runtime_root),
        }
