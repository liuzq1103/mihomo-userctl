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
import hashlib
import stat
import time
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from pathlib import Path

from ..errors import ConfigError, StateError, ValidationError

CLASH_KEYS = ()

STRIP_PREFIXES = ("CLASH_", "LD_")
STRIP_KEYS = {"http_proxy", "https_proxy", "all_proxy", "no_proxy",
              "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}

# Successes are private process-local objects, never trusted from a plan file.
_validation_session = ContextVar('mihomoctl_validation_session', default=None)


@contextmanager
def validation_session(cache=None):
    current = _validation_session.get()
    token = _validation_session.set(current if current is not None else (cache if cache is not None else {}))
    try:
        yield
    finally:
        _validation_session.reset(token)


def validation_operation(operation):
    @wraps(operation)
    def invoke(*args, **kwargs):
        with validation_session():
            return operation(*args, **kwargs)
    return invoke


GEO_FILES = {'country.mmdb', 'geoip.db', 'geoip.metadb', 'geoip.dat', 'geosite.dat', 'asn.mmdb'}


class _ValidationProof:
    """Internal snapshot receipt; never serialized or accepted from CLI input."""
    def __init__(self, identity, binary, text, home, uid, timeout):
        self._identity = identity
        self._binary, self._text, self._home = binary, text, home
        self._uid, self._timeout = uid, timeout

    def ensure_current(self, binary_bytes=None):
        started = time.monotonic()
        try:
            current = _validation_inputs(self._binary, self._text, self._home, self._uid)[0] + (self._timeout,)
            if current != self._identity:
                raise ValidationError('validation-inputs-changed')
            if binary_bytes is not None and hashlib.sha256(binary_bytes).hexdigest() != self._identity[2]:
                raise ValidationError('validation-inputs-changed')
        except (ConfigError, StateError, ValidationError, OSError) as original:
            error = ValidationError('validation-inputs-changed', 'stage=activation-boundary; elapsed_ms=%d' % ((time.monotonic()-started)*1000))
            error.safe_detail = error.detail
            raise error from None


def _trusted_bytes(path, owners, limit=128 * 1024 * 1024, reader_uid=None):
    """Read a stable, non-linked snapshot without following replaceable paths."""
    import pwd
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValidationError('validation-cache-untrusted', 'cache path must be absolute and confined')
    reader_uid = os.geteuid() if reader_uid is None else reader_uid
    reader_gid = pwd.getpwuid(reader_uid).pw_gid
    def accessible(info, bit):
        rights = info.st_mode >> (6 if info.st_uid == reader_uid else 3 if info.st_gid == reader_gid else 0)
        return reader_uid == 0 or bool(rights & bit)
    # Pin and verify each directory descriptor. O_NOFOLLOW on only the leaf
    # would let a service UID redirect a privileged read via a renamed parent.
    parent = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        root_info = os.fstat(parent)
        if root_info.st_uid not in owners or root_info.st_mode & 0o022 or not accessible(root_info, 1):
            raise ValidationError('validation-cache-untrusted', 'cache root directory is not trusted')
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            os.close(parent)
            parent = child
            info = os.fstat(parent)
            sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
            if info.st_uid not in owners or (info.st_mode & 0o022 and not sticky_root) or not accessible(info, 1):
                raise ValidationError('validation-cache-untrusted', 'cache directory is not trusted or traversable by the core identity')
        fd = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            return _read_trusted_fd(fd, path.name, parent, owners, limit, accessible)
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def _read_trusted_fd(fd, name, parent, owners, limit, accessible):
    before = os.fstat(fd)
    if (not stat.S_ISREG(before.st_mode) or before.st_uid not in owners
            or before.st_mode & 0o022 or before.st_nlink != 1 or before.st_size > limit or not accessible(before, 4)):
        raise ValidationError('validation-cache-untrusted', 'cache must be a trusted, non-writable regular file')
    with os.fdopen(os.dup(fd), 'rb') as stream:
        value = stream.read(limit + 1)
    after = os.fstat(fd)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns, s.st_uid, s.st_mode)
    if len(value) > limit or identity(before) != identity(after) or identity(after) != identity(os.stat(name, dir_fd=parent, follow_symlinks=False)):
        raise ValidationError('validation-cache-changed', 'cache changed while being copied')
    return value


def _validation_inputs(binary, config_text, home_dir, uid):
    from ..yamlutil import strict_load
    from ..trust import _check_ancestors
    for candidate_path in (binary, home_dir):
        value = os.fspath(candidate_path)
        if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValidationError('validation-resource-path-unsafe', 'validation paths must be valid Unicode paths')
        try: value.encode('utf-8', errors='strict')
        except UnicodeError:
            raise ValidationError('validation-resource-path-unsafe', 'validation paths must be valid Unicode paths') from None
    if os.geteuid() != 0 and uid != os.geteuid():
        raise ValidationError('validation-identity-mismatch', 'validation identity differs from the acting identity')
    data = strict_load(config_text)
    if not isinstance(data, dict):
        raise ValidationError('core-config-invalid', 'configuration must be a mapping')
    home = Path(home_dir).absolute()
    owners = {0, uid}
    resources, paths, complete = {}, [], True
    if home.exists() or home.is_symlink():
        _check_ancestors(home / 'resource', 'validation-cache-untrusted', owners)
        for item in sorted(home.iterdir()):
            if item.name.lower() in GEO_FILES:
                resources[item.name] = _trusted_bytes(item, owners, reader_uid=uid)
    for section in ('proxy-providers', 'rule-providers'):
        providers = data.get(section, {})
        if not isinstance(providers, dict):
            raise ValidationError('core-config-invalid', 'invalid provider mapping')
        for name, provider in providers.items():
            if not isinstance(provider, dict):
                raise ValidationError('core-config-invalid', 'invalid provider entry')
            value = provider.get('path')
            if value is None:
                if provider.get('type') in ('http', 'file'):
                    complete = False
                continue
            if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
                raise ValidationError('validation-resource-path-unsafe', 'provider path cannot be isolated')
            try:
                value.encode('utf-8', errors='strict')
            except UnicodeError:
                raise ValidationError('validation-resource-path-unsafe', 'provider path must be valid Unicode') from None
            if '..' in Path(value).parts:
                raise ValidationError('validation-resource-path-unsafe', 'provider path cannot be isolated')
            source = Path(value) if Path(value).is_absolute() else home / value
            try:
                relative = source.relative_to(home)
            except ValueError:
                raise ValidationError('validation-resource-path-unsafe', 'provider resource must stay inside core home') from None
            if not relative.parts or relative.parts[0].lower() in GEO_FILES or relative.name in ('cache.db', '.cache'):
                raise ValidationError('validation-resource-path-unsafe', 'provider resource collides with core state')
            paths.append((section, name, str(relative)))
            if source.exists() or source.is_symlink():
                resources[str(relative)] = _trusted_bytes(source, owners, limit=8 * 1024 * 1024, reader_uid=uid)
            else:
                complete = False
    # The executable has its own stricter trust gate in run_core. Its digest
    # binds reuse even when a core is replaced at an otherwise identical path.
    from ..trust import require_executable_file
    require_executable_file(binary, as_root=os.geteuid() == 0)
    executable = hashlib.sha256(Path(binary).read_bytes()).hexdigest()
    manifest = tuple(sorted((name, hashlib.sha256(value).hexdigest()) for name, value in resources.items()))
    identity = (hashlib.sha256(config_text.encode()).hexdigest(), str(Path(binary).absolute()), executable,
                str(home), uid, os.geteuid(), manifest, tuple(paths), complete)
    return identity, resources, paths, data, complete


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
    kwargs = {"capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": timeout, "env": env}
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


_VERSION_TOKEN = re.compile(r"^Mihomo Meta (v?\d+\.\d+\.\d+)(?:\s|$)")


def reported_version(text):
    match = _VERSION_TOKEN.match(text or '')
    return match[1].lstrip('v') if match else None


def version_matches(binary, expected, as_uid=None):
    text = core_version(binary, as_uid=as_uid)
    wanted = expected.lstrip("v")
    return reported_version(text) == wanted, text.split(" ")[0] if text else ""


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
    started, phase = time.monotonic(), 'prepare'
    uid = os.geteuid() if as_uid is None else as_uid
    staging = None
    hits = 0
    cache_detail = '; cache_inventory=unverified'
    try:
        phase = 'cache-check'
        identity, resources, paths, data, complete = _validation_inputs(binary, config_text, home_dir, uid)
        identity += (timeout,)
        hits = len(resources)
        geo_hits = sum('/' not in name and name.lower() in GEO_FILES for name in resources)
        provider_hits = sum(relative in resources for _section, _name, relative in paths)
        provider_missing = len(paths) - provider_hits + sum(
            provider.get('type') in ('http','file') and provider.get('path') is None
            for section in ('proxy-providers','rule-providers') for provider in data.get(section,{}).values())
        cache_detail = '; geo_cache_files=%d; provider_cache_files=%d; provider_cache_missing=%d' % (geo_hits,provider_hits,provider_missing)
        cache = _validation_session.get()
        if complete and cache is not None and identity in cache:
            return cache[identity]
        staging = Path(tempfile.mkdtemp(prefix="mihomoctl-validate-"))
        for relative, content in resources.items():
            destination = staging / relative
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.write_bytes(content)
            destination.chmod(0o600)
        # Absolute provider paths are rewritten only in the isolated candidate;
        # the actual configuration and its path semantics are never changed.
        if paths:
            import copy
            import yaml
            data = copy.deepcopy(data)
            for section, name, relative in paths:
                data[section][name]['path'] = str(staging / relative)
            isolated_text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=2 ** 31 - 1)
        else:
            isolated_text = config_text
        if as_uid is not None and hasattr(os, "geteuid") and os.geteuid() == 0 and as_uid != 0:
            import pwd
            entry = pwd.getpwuid(as_uid)
            os.chown(str(staging), as_uid, entry.pw_gid)
            os.chmod(str(staging), 0o700)
            for item in staging.rglob('*'):
                os.chown(str(item), as_uid, entry.pw_gid)
        phase = 'core-validation'
        result = run_core(binary, ["-t", "-d", str(staging), "-f", "-"],
                          timeout=timeout, as_uid=as_uid, input_text=isolated_text)
        if result.returncode != 0:
            raise ValidationError(
                "core-config-invalid",
                "candidate configuration rejected by the core (exit %d)" % result.returncode)
        # Reuse only a result whose inputs were stable for the entire check.
        final = _validation_inputs(binary, config_text, home_dir, uid)[0] + (timeout,)
        if identity != final:
            raise ValidationError('validation-inputs-changed', 'validation inputs changed during the core check')
        generated = {str(p.relative_to(staging)) for p in staging.rglob('*') if p.is_file()} - set(resources) - {'cache.db'}
        seeded_unchanged = True
        for relative, content in resources.items():
            try:
                if _trusted_bytes(staging / relative, {0, uid}, reader_uid=uid) != content:
                    seeded_unchanged = False
            except (ConfigError, ValidationError, OSError):
                seeded_unchanged = False
        proof = _ValidationProof(identity, binary, config_text, home_dir, uid, timeout)
        if cache is not None and complete and not generated and seeded_unchanged:
            if len(cache) >= 4:
                cache.clear()
            cache[identity] = proof
        return proof
    except (ConfigError, StateError, ValidationError) as error:
        # Only fixed labels and numbers cross the diagnostic boundary. In
        # particular, core stdout/stderr and file paths never become detail.
        error.detail = 'stage=%s; elapsed_ms=%d; cache_files=%d' % (phase, (time.monotonic() - started) * 1000, hits) + cache_detail
        error.safe_detail = error.detail
        error.args = (error.render(),)
        raise
    except OSError:
        error = ValidationError('validation-cache-unavailable',
                                'stage=%s; elapsed_ms=%d; cache_files=%d' % (phase, (time.monotonic()-started)*1000, hits) + cache_detail)
        error.safe_detail = error.detail
        raise error from None
    finally:
        if staging is not None:
            shutil.rmtree(str(staging), ignore_errors=True)
