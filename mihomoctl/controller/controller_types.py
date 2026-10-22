"""User-level controller component; no global proxy or daemon."""
import argparse
import unicodedata

SCHEMA = "mihomo-userctl.controller/v1"
COMMANDS = ("controller", "nodes", "groups", "select", "latency", "connections", "traffic", "ui", "dashboard", "tui", "override", "manual", "providers", "provider", "dns", "mode", "subscription", "health-check")
LIMIT = 8 * 1024 * 1024
TEST_URL = "https://www.gstatic.com/generate_204"
TUI_INSTALL_COMMAND = "bash install.sh --user --python <python> --wheelhouse <wheelhouse-dir> --extras tui"

ERROR_LABELS = {
    "node-not-in-core": "节点不在核心代理表中",
    "node-unreachable": "节点存在但探测失败",
    "delay-timeout": "探测超时",
    "unknown-node": "未知节点；请与 mihomoctl nodes --json 中的完整名称核对",
    "invalid-health-check-options": '必须以 group 或 provider 开头，例如 group "Ai+" 或 provider "名称"',
    "textual-environment-incomplete-use-engine-curses":
        "当前解释器无法导入 textual/rich；使用 mihomoctl tui --engine curses（无需安装，t 测速），"
        "或用户私有安装：" + TUI_INSTALL_COMMAND + "（无需 sudo 或系统 pip）",
}


def error_text(code, detail=""):
    text = code + ("（" + ERROR_LABELS[code] + "）" if code in ERROR_LABELS else "")
    return text + (": " + detail if detail else "")


def error_detail(code, detail=""):
    """Envelope detail adds information; the code already has its own field."""
    return ": ".join(part for part in (ERROR_LABELS.get(code, ""), detail) if part) or None


class ControlError(Exception):
    def __init__(self, code, rc=2, detail=""):
        self.code, self.rc = code, rc
        self.detail = detail
        super().__init__(error_text(code, detail))


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
