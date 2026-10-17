"""Detached one-shot notification worker. Its entire process group expires in 5s."""
import os
from pathlib import Path
import signal
import sys

if __name__ == '__main__':
    signal.signal(signal.SIGALRM, lambda *_: os.killpg(os.getpgrp(), signal.SIGKILL))
    signal.setitimer(signal.ITIMER_REAL, 5)
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    try:
        from mihomoctl.notifications import refresh
        from mihomoctl.scope import Scope
        scope = Scope(system=sys.argv[1] == 'system')
        scope.require_mutation()
        refresh(scope)
    except Exception:
        pass
