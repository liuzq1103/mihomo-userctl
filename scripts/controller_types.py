"""User-level controller component; no global proxy or daemon."""
import argparse
import unicodedata

SCHEMA = "mihomo-userctl.controller/v1"
COMMANDS = ("controller", "nodes", "groups", "select", "latency", "connections", "traffic", "ui", "dashboard", "tui", "override", "manual", "providers", "provider", "dns", "mode", "subscription")
LIMIT = 8 * 1024 * 1024
TEST_URL = "https://www.gstatic.com/generate_204"


class ControlError(Exception):
    def __init__(self, code, rc=2):
        self.code, self.rc = code, rc
        super().__init__(code)


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ControlError("invalid-options")


def label(value):
    if not isinstance(value, str) or len(value) > 512 or any(unicodedata.category(c) in ("Cc", "Cf") for c in value):
        raise ControlError("controller-response-invalid-label")
    return value


def number(value):
    if type(value) not in (int, float) or not 0 <= value <= 2 ** 63:
        raise ControlError("controller-response-invalid-number")
    return value
