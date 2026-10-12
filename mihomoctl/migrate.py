"""Explicit, rollbackable import of the historical configuration and owned loader."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urlsplit

from .config import CoreSettings, Manager, Profile, render_manager
from .credentials import Credentials, _yaml_str
from .errors import ConfigError, StateError, UsageError
from .trust import require_executable_file, require_private_file
from .yamlutil import strict_load

BEGIN_MARKER = '# >>> mihomo-userctl managed loader >>>'
END_MARKER = '# <<< mihomo-userctl managed loader <<<'


def legacy_dir(scope):
    return scope.config_root.parent / 'mihomo'


def parse_env_file(text, allowed):
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=(.*)', line)
        if not match or match[1] not in allowed or match[1] in values:
            raise ConfigError('legacy-config-invalid', 'invalid or duplicate assignment')
        raw = match[2]
        if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in '\'"':
            raw = raw[1:-1]
        values[match[1]] = raw
    return values


def load_legacy(directory):
    conf, env = directory / 'mihomo-shell.conf', directory / 'client.env'
    if not conf.exists() and not env.exists():
        return None
    result = []
    for path, allowed in ((conf, {'MIHOMO_SERVICE', 'MIHOMO_PORT', 'MIHOMO_READY_URL', 'MIHOMO_READY_TIMEOUT', 'MIHOMO_STOP_TIMEOUT'}),
                          (env, {'MIHOMO_HTTP_PROXY', 'MIHOMO_HTTPS_PROXY', 'MIHOMO_ALL_PROXY'})):
        if not path.exists():
            result.append({})
            continue
        require_private_file(path, code='legacy-config-invalid')
        if path.stat().st_size > 65536:
            raise ConfigError('legacy-config-invalid', 'legacy configuration too large')
        result.append(parse_env_file(path.read_text(encoding='utf-8'), allowed))
    return tuple(result)


def strip_loader_block(text):
    if BEGIN_MARKER not in text and END_MARKER not in text:
        return text
    if text.count(BEGIN_MARKER) != 1 or text.count(END_MARKER) != 1:
        return None
    start = text.index(BEGIN_MARKER)
    finish = text.index(END_MARKER) + len(END_MARKER)
    if finish <= start or start and text[start - 1] != '\n':
        return None
    if finish < len(text) and text[finish] not in '\r\n':
        return None
    if text[finish:finish + 2] == '\r\n':
        finish += 2
    elif text[finish:finish + 1] == '\n':
        finish += 1
    return text[:start] + text[finish:]


def _loader(scope, path):
    info = path.lstat()
    if path.is_symlink() or not path.is_file() or info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ConfigError('loader-unsafe', 'startup file is not safely owned')
    raw = path.read_bytes()
    text = raw.decode('utf-8')
    stripped = strip_loader_block(text)
    if stripped is None:
        raise StateError('loader-ambiguous', 'customized or ambiguous loader markers')
    start = text.index(BEGIN_MARKER)
    finish = text.index(END_MARKER) + len(END_MARKER)
    block = text[start:finish]
    # Historical immutable generation metadata commits to the exact block.
    # A marker alone is insufficient authorization to remove custom text.
    root = scope.data_root.parent / 'mihomo-userctl'
    current = root / 'current'
    if not current.is_symlink():
        raise StateError('loader-unverified', 'historical generation metadata is required to identify the loader')
    generation = current.resolve(strict=True)
    if generation.parent != root / 'generations':
        raise StateError('loader-unverified', 'historical generation escapes its managed root')
    record_path = generation / 'installation.json'
    require_private_file(record_path, code='loader-unverified')
    record = json.loads(record_path.read_text(encoding='utf-8'))
    if record.get('home') != str(Path.home()) or record.get('bashrc') != str(path) or \
            record.get('loader_sha256') != hashlib.sha256(block.encode()).hexdigest():
        raise StateError('loader-ambiguous', 'loader differs from the historical installation receipt')
    return raw, stripped.encode('utf-8'), info.st_mode & 0o777


def preview(scope):
    legacy = load_legacy(legacy_dir(scope))
    plan = {'legacy_config': bool(legacy), 'already_initialized': scope.manager_path.exists(),
            'loader_blocks': {}, 'legacy_units': []}
    if legacy:
        plan['import'] = {'config': str(legacy_dir(scope) / 'config.yaml'), 'credentials': bool(legacy[1])}
    if not scope.system:
        for filename in ('.bashrc', '.zshrc', '.profile'):
            path = Path.home() / filename
            if path.exists() and BEGIN_MARKER.encode() in path.read_bytes():
                try:
                    _loader(scope, path)
                    state = 'identified'
                except (ConfigError, StateError, ValueError):
                    state = 'ambiguous'
                plan['loader_blocks'][str(path)] = state
        base = Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'systemd/user'
        for path in sorted(base.glob('*.service')):
            if path.name == 'paseo.service' or 'mihomo-userctl paseo' in path.read_text(errors='replace'):
                plan['legacy_units'].append({'unit': str(path), 'action': 'report-only'})
    return plan


def apply(scope, remove_loader=True, import_config=True, core=None):
    from .endpoints import parse_endpoints
    from .lifecycle import runner, systemd
    from .transaction import run_transaction
    scope.require_mutation()
    plan = preview(scope)
    loader_changes = {}
    if remove_loader:
        if scope.system and plan['loader_blocks']:
            raise UsageError('migration-system-shell', 'system migration never edits a user startup file')
        for filename in plan['loader_blocks']:
            path = Path(filename)
            loader_changes[path] = _loader(scope, path)
    should_import = bool(import_config and plan['legacy_config'] and not scope.manager_path.exists())
    config_text = manager = creds = None
    if should_import:
        source = legacy_dir(scope) / 'config.yaml'
        require_private_file(source, code='legacy-config-invalid')
        config_text = source.read_text(encoding='utf-8')
        cfg = strict_load(config_text)
        if (cfg.get('tun') or {}).get('enable'):
            raise ConfigError('legacy-config-invalid', 'disable legacy TUN before migration; enable it explicitly afterward')
        endpoints, controller = parse_endpoints(cfg, system_scope=scope.system)
        _, proxies = load_legacy(legacy_dir(scope))
        http_url = urlsplit(proxies.get('MIHOMO_HTTP_PROXY') or proxies.get('MIHOMO_HTTPS_PROXY') or '')
        socks_url = urlsplit(proxies.get('MIHOMO_ALL_PROXY') or '')
        if http_url.hostname not in ('127.0.0.1', '::1') or socks_url.hostname not in ('127.0.0.1', '::1'):
            raise ConfigError('legacy-config-invalid', 'legacy clients must use loopback proxy URLs')
        creds = Credentials(unquote(http_url.username or ''), unquote(http_url.password or ''))
        if (unquote(socks_url.username or ''), unquote(socks_url.password or '')) != (creds.username, creds.password):
            raise ConfigError('legacy-config-invalid', 'HTTP and SOCKS credentials differ')
        http = next((e for e in endpoints if e.supports_http and e.port == http_url.port and e.address == http_url.hostname), None)
        socks = next((e for e in endpoints if e.supports_socks and e.port == socks_url.port and e.address == socks_url.hostname), None)
        if http is None or socks is None:
            raise ConfigError('legacy-config-invalid', 'legacy endpoint does not match the core configuration')
        for endpoint in (http, socks):
            if endpoint.legacy:
                pairs = [tuple(value.split(':', 1)) for value in cfg.get('authentication', [])]
            else:
                users = next(row.get('users', []) for row in cfg.get('listeners', []) if row['name'] == endpoint.name)
                pairs = [(row['username'], row['password']) for row in users]
            if (creds.username, creds.password) not in pairs:
                raise ConfigError('legacy-credentials-mismatch', 'legacy client credentials do not match the selected core listeners')
        binary = core or shutil.which('mihomo')
        if not binary:
            raise UsageError('migration-core-required', 'pass --core PATH to reference an existing trusted binary')
        binary = str(Path(binary).absolute())
        require_executable_file(binary, as_root=scope.system)
        uid = systemd.ensure_service_account().pw_uid if scope.system else None
        runner.validate_config(binary, config_text, scope.core_home, as_uid=uid)
        target = scope.config_root / 'mihomo/config.yaml'
        credential_path = scope.credentials_dir / 'default.yaml'
        manager = Manager(core=CoreSettings(binary=binary, config=str(target), backend='systemd' if scope.system else 'process'),
                          profiles={'default': Profile('default', http.name, socks.name, str(credential_path))})

    def action(tx):
        result = {'imported': False, 'loader_removed': [], 'legacy_units': plan['legacy_units'], 'idempotent': True}
        if manager is not None:
            tx.write_text(Path(manager.core.config), config_text, mode=0o640 if scope.system else 0o600)
            tx.write_text(Path(manager.profiles['default'].credentials_file), 'username: %s\npassword: %s\n' % (_yaml_str(creds.username), _yaml_str(creds.password)))
            tx.write_text(scope.manager_path, render_manager(manager))
            if scope.system:
                systemd._prepare_system_paths(scope, manager)
            result.update(imported=True, idempotent=False)
        for path, (original, stripped, mode) in loader_changes.items():
            if path.read_bytes() != original:
                raise StateError('loader-changed', 'startup file changed during migration')
            tx.write_bytes(path, stripped, mode=mode)
            result['loader_removed'].append(str(path))
            result['idempotent'] = False
        result['backup'] = str(tx.backup_root)
        return result
    return run_transaction(scope, 'migrate', action, allow_paths=loader_changes)
