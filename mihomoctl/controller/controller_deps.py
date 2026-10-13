"""Detect explicitly prepared optional UI dependencies; never install on launch."""
import importlib.util

def interpreter():
    # V1 installs use their selected interpreter and declared optional dependency.
    return None, None

def launch(arguments, module='controller.py', require_textual=True):
    if require_textual and importlib.util.find_spec('textual') is None:
        from .controller_types import ControlError
        raise ControlError('textual-not-installed-use-plain-or-install-tui-extra')
