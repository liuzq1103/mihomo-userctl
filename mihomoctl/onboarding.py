"""First-use orchestration shared by Textual and the plain SSH menu."""
import json
from pathlib import Path

from .errors import MihomoctlError


def prepare(app):
    if app.scope.manager_path.exists():
        manager = app.load_manager()
        app.resolve()  # Existing invalid configurations are reported, never reset.
        return {'state': 'ready', 'config': manager.core.config}
    from .portable import bundle_root, prepare_core
    if bundle_root() is not None:
        core = prepare_core(app.scope)
    else:
        from .controller.controller_transaction import find_core
        core = find_core()
    try:
        app.initialize(str(core))
    except MihomoctlError as error:
        if error.code != 'already-initialized':
            raise
    return {'state': 'ready', 'config': app.load_manager().core.config}


def needs_setup(app):
    if app is None or not isinstance(getattr(getattr(app, 'scope', None), 'manager_path', None), Path):
        return False
    if not app.scope.manager_path.exists():
        return True
    from .yamlutil import strict_load
    try:
        cfg = strict_load(Path(app.load_manager().core.config).read_text(encoding='utf-8'))
        return not isinstance(cfg, dict) or not (cfg.get('proxies') or cfg.get('proxy-providers'))
    except (MihomoctlError, OSError, ValueError):
        return True


def guided_shape(data):
    """Only an untouched new configuration or our exact simple routing preset."""
    if not data.get('proxy-groups') and data.get('rules', []) == ['MATCH,DIRECT']:
        return True
    groups = data.get('proxy-groups', [])
    return (data.get('rules') == ['MATCH,Proxy'] and len(groups) == 1
            and groups[0].get('name') == 'Proxy' and groups[0].get('type') == 'select'
            and set(groups[0]) <= {'name', 'type', 'proxies', 'use'})


def guided_policy(incoming):
    """Select nodes/providers without importing remote listener or host settings."""
    from .controller.controller_subscriptions import provider_policy
    from .controller.controller_types import ControlError
    nodes, providers = incoming.get('proxies', []), incoming.get('proxy-providers', {})
    if not nodes and not providers:
        raise ControlError('subscription-node-list-invalid', 1)
    if any(row.get('name') in ('Proxy', 'DIRECT', 'REJECT') for row in nodes):
        raise ControlError('subscription-reserved-node-name-use-advanced', 1)
    group = {'name': 'Proxy', 'type': 'select', 'proxies': [row['name'] for row in nodes]}
    if providers:
        group['use'] = list(providers)
    changes = {'proxies': nodes, 'proxy-providers': providers, 'proxy-groups': [group],
               'rules': ['MATCH,Proxy'], 'rule-providers': {}}
    return provider_policy(changes)
