"""Best-effort, cache-only foreground notifications, independent of runtime health."""
from contextvars import ContextVar
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from . import __version__
from .credentials import write_atomic
from .locks import operation_lock
from .release import WEB, read_json, version_key
from .release_identity import version_order
from .trust import require_private_dir, require_private_file

INTERVAL = 24 * 60 * 60
TUI_NOTICE = ContextVar('release_notice', default=None)


def _paths(scope):
    directory = scope.state_root / 'release-notifications'
    require_private_dir(directory, create=True)
    return directory / 'state.json'


def _read(path):
    if not path.exists() and not path.is_symlink():
        return {}
    require_private_file(path)
    if path.stat().st_size > 8192:
        raise ValueError('notification state limit')
    data = read_json(path)
    if not isinstance(data, dict) or set(data) - {'attempted_at', 'notified', 'observation'}:
        raise ValueError('notification state invalid')
    if 'notified' in data:
        version_key(data['notified'])
    attempted = data.get('attempted_at', 0)
    if type(attempted) not in (int, float) or not 0 <= attempted < float('inf'):
        raise ValueError('notification time invalid')
    return data


def prepare(scope):
    """Never waits for locks or network; any optional failure suppresses the notice."""
    if os.environ.get('MIHOMOCTL_NO_UPDATE_CHECK') == '1':
        return None
    try:
        scope.require_mutation()
        with operation_lock(scope, 'release-notifications'):
            path = _paths(scope)
            data = _read(path)
            previous = json.dumps(data, sort_keys=True)
            now = time.time()
            observed = data.get('observation')
            notice = None
            if observed is not None:
                version = observed['observed_version']
                expected_url = WEB + '/releases/tag/v' + version
                if (observed['release_url'] != expected_url or type(observed['checked_at']) is not int
                        or observed['checked_at'] < 0):
                    raise ValueError('notification observation invalid')
                if (version_order(version) > version_order(__version__)
                        and version_key(version) > version_key(data.get('notified', '0.0.0'))):
                    data['notified'] = version
                    notice = ('mihomoctl: newer release observed: %s (checked_at=%s)\n%s\n'
                              'Upgrade: mihomoctl update --latest' %
                              (version, observed['checked_at'], expected_url))
            launch = (now - data.get('attempted_at', 0) >= INTERVAL
                      or data.get('attempted_at', 0) > now)
            if launch:
                data['attempted_at'] = now
            # Claim before printing or spawning, including failed attempts.
            if json.dumps(data, sort_keys=True) != previous:
                write_atomic(path, json.dumps(data))
            if launch:
                subprocess.Popen([sys.executable, '-I', '-B',
                                  str(Path(__file__).with_name('release_worker.py')),
                                  'system' if scope.system else 'user'],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL, start_new_session=True,
                                 close_fds=True)
            return notice
    except Exception:
        return None


def refresh(scope):
    from .release import check
    observed = check(timeout=4)
    with operation_lock(scope, 'release-notifications'):
        path = _paths(scope)
        data = _read(path)
        data['observation'] = observed
        write_atomic(path, json.dumps(data))


def take_tui_notice():
    notice = TUI_NOTICE.get()
    TUI_NOTICE.set(None)
    return notice
