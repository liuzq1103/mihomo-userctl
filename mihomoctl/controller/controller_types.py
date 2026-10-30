"""User-level controller component; no global proxy or daemon."""
import argparse
import hashlib
import hmac
import json
import re
import secrets
import unicodedata

SCHEMA = "mihomo-userctl.controller/v1"
COMMANDS = ("controller", "nodes", "groups", "select", "latency", "connections", "traffic", "ui", "dashboard", "tui", "override", "manual", "providers", "provider", "dns", "mode", "subscription", "health-check")
LIMIT = 8 * 1024 * 1024
TEST_URL = "https://www.gstatic.com/generate_204"
TUI_INSTALL_COMMAND = "bash install.sh --user --python <python> --wheelhouse <wheelhouse-dir> --extras tui"

ERROR_LABELS = {
    'cross-level-selection-refused': '聚合组禁止直接选择叶子；先切子组再切入口。明确授权后才可使用 --allow-cross-level',
    'selection-target-unverified': '目标身份尚未确认；刷新节点与分组后重试',
    'validation-inputs-changed':'校验后核心或依赖资源已变化；请重新预览并保存',
    'probe-unverified':'测速结果未确认',
    'controller-capability-unsupported':'当前核心不支持此控制器接口',
    'subscription-cleanup-incomplete':'预览临时材料清理失败；请检查私有目录并重新预览',
    'ambiguous-node': '节点名称有多个来源；请指定 --provider 或在界面选择来源',
    'node-disappeared': '节点在 provider 刷新后已消失；请刷新列表',
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


def safe_failure(error):
    """Only explicitly safe projections may leave filesystem/runtime code."""
    detail = getattr(error, 'safe_detail', '')
    return detail if isinstance(detail, str) and len(detail) <= 2048 else ''


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ControlError("invalid-options")


def label(value):
    if not isinstance(value, str) or len(value) > 512 or any(unicodedata.category(c) in ("Cc", "Cf") for c in value):
        raise ControlError("controller-response-invalid-label")
    return value


def request_label(value):
    if value is None: return None
    sensitive = len(value) > 512 or re.search(r'(?i)[a-z][a-z0-9+.-]*://|(?:password|secret|token|uuid|key)\s*[:=]|[^\s:]+:[^\s@]+@', value)
    return '[redacted request]' if sensitive else value


_NODE_ID_KEY = secrets.token_bytes(32)


def node_identity(name, provider=None):
    # Per-process correlation only; no public hash verifier for a redacted URL
    # or a weak credential-shaped request label.
    return hmac.new(_NODE_ID_KEY,json.dumps([provider,name],ensure_ascii=True).encode('ascii'),hashlib.sha256).hexdigest()


def number(value):
    if type(value) not in (int, float) or not 0 <= value <= 2 ** 63:
        raise ControlError("controller-response-invalid-number")
    return value
