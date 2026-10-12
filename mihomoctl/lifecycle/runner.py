"""Core runner shared by both backends: spawn environment hygiene,
validation staging and version probing.

- The daemon always starts with ``-d <home> -f <config>`` (file-based,
  preserving SIGHUP reload); never stdin/base64.
- CLASH_* override variables, proxy variables and post-up/down hooks are
  stripped from the child environment.
- ``mihomo -t`` runs against a private staging dir (never the live home)
  because parsing can download geodata.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from ..errors import StateError, ValidationError

CLASH_KEYS = ()

STRIP_PREFIXES = ("CLASH_", "LD_")
STRIP_KEYS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}


def child_environment(base=None):
    env = dict(os.environ if base is None else base)
    for key in list(env):
        if key in STRIP_KEYS or any(key.startswith(p) for p in STRIP_PREFIXES):
            del env[key]
    return env


def run_core(binary, args, timeout=20, env=None, cwd=None, as_uid=None, extra_env=None, input_text=None):
    """Run the core binary once; returns CompletedProcess or raises."""
    from ..trust import require_executable_file
    root = hasattr(os, 'geteuid') and os.geteuid() == 0
    require_executable_file(binary, as_root=root)
    if root and (as_uid is None or as_uid == 0):
        raise StateError('core-root-execution-refused', 'core checks must use a non-privileged identity')
    command = [str(binary), *args]
    env = child_environment(env)
    if extra_env:
        env.update(extra_env)
    kwargs = {"capture_output": True, "text": True, "timeout": timeout, "env": env}
    if input_text is not None:
        kwargs["input"] = input_text
    if cwd is not None:
        kwargs["cwd"] = str(cwd)
    if as_uid is not None and hasattr(os, "geteuid") and os.geteuid() == 0 and as_uid != 0:
        # Native Popen credential setup avoids Python callbacks between fork
        # and exec, which can deadlock a threaded TUI/daemon child.
        import pwd
        account = pwd.getpwuid(as_uid)
        kwargs.update(user=account.pw_uid, group=account.pw_gid, extra_groups=[account.pw_gid])
    try:
        return subprocess.run(command, **kwargs)
    except subprocess.TimeoutExpired:
        raise StateError("core-timeout", " ".join(args[:2])) from None
    except OSError as exc:
        raise StateError("core-unavailable", "%s (%s)" % (binary, exc.strerror)) from None


def core_version(binary, as_uid=None):
    result = run_core(binary, ["-v"], timeout=15, as_uid=as_uid)
    if result.returncode != 0:
        raise StateError("core-version-failed", "exit %d" % result.returncode)
    return result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""


_VERSION_TOKEN = re.compile(r"v?\d+\.\d+\.\d+")


def version_matches(binary, expected, as_uid=None):
    text = core_version(binary, as_uid=as_uid)
    tokens = _VERSION_TOKEN.findall(text)
    wanted = expected.lstrip("v")
    return any(t.lstrip("v") == wanted for t in tokens), text.split(" ")[0] if text else ""


def validate_config(binary, config_text, home_dir, as_uid=None, timeout=60):
    """Validate a candidate configuration with ``mihomo -t -d <staging> -f -``.

    The candidate never lands on the managed config path and geodata lands
    in the staging dir, never the live data directory.  When validation is
    dropped to another UID (system scope), the staging dir is chowned so
    the geodata download can actually write.  Core stderr may contain
    secrets (subscription URLs, credentials): it never reaches the raised
    error and is discarded after validation."""
    # A system validator must not need to traverse root-private state roots.
    # TemporaryDirectory starts private and is chowned before dropping uid.
    staging = Path(tempfile.mkdtemp(prefix="mihomoctl-validate-"))
    try:
        if as_uid is not None and hasattr(os, "geteuid") and os.geteuid() == 0 and as_uid != 0:
            import pwd
            entry = pwd.getpwuid(as_uid)
            os.chown(str(staging), as_uid, entry.pw_gid)
            os.chmod(str(staging), 0o700)
        result = run_core(binary, ["-t", "-d", str(staging), "-f", "-"],
                          timeout=timeout, as_uid=as_uid, input_text=config_text)
        if result.returncode != 0:
            raise ValidationError(
                "core-config-invalid",
                "candidate configuration rejected by the core (exit %d)" % result.returncode)
        return True
    finally:
        shutil.rmtree(str(staging), ignore_errors=True)
