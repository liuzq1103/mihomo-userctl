"""Profile credentials: username/password data files.

Credential files contain data, never executable assignments; the strict
YAML loader rejects anchors/aliases and duplicate keys, and the schema
allows exactly ``username`` and ``password``.  Passwords may contain any
printable characters (URLs percent-encode them); usernames reject the
mihomo ``user:pass`` separator and whitespace.  Writes are atomic
(temp file + fsync + replace) inside a private directory.
"""

import os
import secrets
import string
import tempfile
from pathlib import Path

from .errors import ConfigError
from .trust import require_private_dir
from .yamlutil import read_private_yaml

_ALPHABET = string.ascii_letters + string.digits


def generate(prefix="mihomo"):
    return prefix + "-" + "".join(secrets.choice(_ALPHABET) for _ in range(20))


def _username(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ConfigError("credentials-invalid", "username must be a non-empty string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value) or any(ch in value for ch in ": \t\r\n"):
        raise ConfigError("credentials-invalid", "username contains forbidden characters")
    return value


def _password(value):
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ConfigError("credentials-invalid", "password must be a non-empty string")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise ConfigError("credentials-invalid", "password contains control characters")
    return value


class Credentials:
    def __init__(self, username, password):
        self.username = username
        self.password = password

    def redacted(self):
        return {"username": self.username[:2] + "***", "password": "***"}

    @classmethod
    def load(cls, path):
        data = read_private_yaml(path, code="credentials-invalid")
        if not isinstance(data, dict) or set(data) - {"username", "password"} or "username" not in data or "password" not in data:
            raise ConfigError("credentials-invalid", "expected exactly username and password fields")
        return cls(_username(data["username"]), _password(data["password"]))

    @classmethod
    def create(cls, path, username=None, password=None):
        creds = cls(username or generate("user"), password or generate())
        write_atomic(Path(path), "username: %s\npassword: %s\n" % (_yaml_str(creds.username), _yaml_str(creds.password)), mode=0o600)
        return creds


def _yaml_str(value):
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def write_atomic(path: Path, text: str, mode=0o600):
    """Atomic publication: write a private temp file in the same directory,
    fsync, then os.replace over the target.  The directory must already be
    a validated private dir."""
    require_private_dir(path.parent, create=True)
    fd, temporary = tempfile.mkstemp(prefix="." + path.name + "-", dir=str(path.parent))
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, str(path))
        if hasattr(os, 'O_DIRECTORY'):
            parent_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(parent_fd)
            finally:
                os.close(parent_fd)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
