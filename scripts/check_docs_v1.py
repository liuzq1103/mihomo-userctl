#!/usr/bin/env python3
"""Validate shipped Markdown links, V1 entry points and the documentation contract.

tests/docs-test.sh used to own this contract. It is now only a wrapper that
execs this module, because the V1 CI (.github/workflows/test.yml) runs this
file and never the shell script. Every assertion that still describes the V1
product was migrated here; the 0.9.x assertions were dropped instead of being
carried forward, and the retired `install.sh` flags they used to require are now
rejected by check_install_parameters().
"""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("README.md", "README.en.md", "INSTALL.md", "CHANGELOG.md", "SECURITY.md",
            "docs/architecture-v1.md", "docs/code-audit.md", "docs/design-reference.md",
            "docs/release-review.md", "docs/adr/0002-v1-generic-runtime.md")

# Every topic must exist in both languages: a one-sided documentation set is a
# contract break, not a style preference.
BILINGUAL_TOPICS = (
    "README.md",
    "paseo.md",
    "paseo-production.md",
    "control-plane.md",
    "console.md",
    "failover.md",
    "console-acceptance.md",
    "quick-install.md",
    "acceptance.md",
    "agent-install-prompt.md",
    "agent-local-install-prompt.md",
    "offline-install.md",
    "deployment-contract.md",
    "first-run.md",
    "shared-runtime.md",
    "agent-update-prompt.md",
    "architecture.md",
    "codex-install-prompt.md",
    "mihoro-inspiration.md",
    "rules.md",
    "security.md",
    "setup.md",
    "troubleshooting.md",
    "update.md",
    "vscode-remote.md",
)

# The generic prompt must stay product-agnostic and must keep the V1 boundaries.
GENERIC_PROMPT_MARKERS = {
    "en": ("capability gate", "read-only audit", "explicit approval", "Sensitive information",
           "rollback", "final acceptance", "redacted diff", "complete test suite",
           "systemctl --user", "VS Code Remote", "http.proxy", "setup.md", "architecture.md",
           "security.md", "acceptance.md", "scripts/acceptance.sh", "PASS", "FAIL", "UNVERIFIED",
           "DEFERRED", "--expect-status", "PIPESTATUS", "SHA256"),
    "zh-CN": ("能力检查", "只读审计", "明确批准", "敏感信息", "回滚", "最终验收", "脱敏 diff",
              "完整测试套件", "systemctl --user", "VS Code Remote", "http.proxy", "setup.md",
              "architecture.md", "security.md", "acceptance.md", "scripts/acceptance.sh", "PASS",
              "FAIL", "UNVERIFIED", "DEFERRED", "--expect-status", "PIPESTATUS", "SHA256"),
}

PRODUCT_SPECIFIC_INTERFACE = re.compile(
    r"Plan mode|Plan \u6a21\u5f0f|request_user_input|interactive popup|\u4ea4\u4e92\u5f39\u7a97|"
    r"Codex client|Codex \u5ba2\u6237\u7aef|Skills?")

MAINTAINER_ROUTING_POLICY = re.compile(
    rb"SEA[-_ ]?AD|sea-ad-single-cell|Ai\+|"
    + rb"\xe5\xad\xa6\xe6\x9c\xaf\xe6\x90\x9c\xe7\xb4\xa2|\xe5\xad\xa6\xe6\x9c\xaf\xe8\xae\xbf\xe9\x97\xae"
    + rb"|Academic (Search|Access)")
PRIVATE_VALUES = re.compile(rb"17890|docs/(en|zh-CN)/migration\.md")
PRE_EXPANDED_BUNDLE = re.compile(r"PUBLIC/mihomo-offline|\$BUNDLE/|Shared deployment directory:")

# Pages that are deliberately kept as archived 0.9.x tutorials: their command
# surface is migration history and the banner above each one states that V1 must
# not follow it. Agent-facing pages are never exempt -- they are executed.
ARCHIVED_PAGES = frozenset((
    "docs/en/setup.md", "docs/zh-CN/setup.md",
    "docs/en/quick-install.md", "docs/zh-CN/quick-install.md",
))
ARCHIVE_BANNER = re.compile(r"0\.9\.x")
ARCHIVE_WORDS = ("Archived", "archive", "\u5f52\u6863", "\u5386\u53f2", "historical", "history")

# `install.sh --<flag>` outside a command, in Markdown.
INSTALL_SH = re.compile(r"(?<![A-Za-z0-9_.-])install\.sh\b")
FLAG = re.compile(r"--[A-Za-z0-9][A-Za-z0-9-]*")
SEGMENT_BREAK = re.compile(r"[`|\n\u3001\uff0c\u3002\uff1b;]|&&|\|\|")


def relative(document):
    return str(document.relative_to(ROOT)).replace("\\", "/")


def documents():
    for name in REQUIRED:
        if "/" not in name:
            yield ROOT / name
    yield ROOT / "README.zh-CN.md"
    yield from sorted((ROOT / "docs").rglob("*.md"))


def has_unclosed_fence(text):
    active = None
    for line in text.splitlines():
        match = re.match(r"^ {0,3}(`{3,}|~{3,})(.*)$", line)
        if not match:
            continue
        marker, rest = match.groups()
        if active is None:
            active = marker
        elif marker[0] == active[0] and len(marker) >= len(active) and not rest.strip():
            active = None
    return active is not None


def check_documents(errors):
    for document in documents():
        if not document.is_file():
            continue
        text = document.read_text(encoding="utf-8-sig")
        if has_unclosed_fence(text):
            errors.append("unclosed-code-fence: " + relative(document))
        if "\ufffd" in text:
            errors.append("replacement-character: " + relative(document))
        for raw in re.findall(r"\]\(([^)]+)\)", text):
            target = raw.strip().split(" ", 1)[0].strip("<>").split("#", 1)[0]
            if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            if not (document.parent / unquote(target)).exists():
                errors.append("broken-link: " + relative(document) + " -> " + target)


def check_entrypoints(errors):
    for name in ("README.md", "README.en.md", "INSTALL.md"):
        if (ROOT / name).exists():
            text = (ROOT / name).read_text(encoding="utf-8-sig")
            for marker in ("mihomoctl", "--system", "profile", "init"):
                if marker not in text:
                    errors.append("v1-entrypoint-missing: " + name + ": " + marker)


def check_bilingual_topics(errors):
    for language in ("en", "zh-CN"):
        for topic in BILINGUAL_TOPICS:
            if not (ROOT / "docs" / language / topic).is_file():
                errors.append("bilingual-topic-missing: docs/%s/%s" % (language, topic))


def check_readme_entry(errors):
    """V1 makes INSTALL.md the authoritative installation entry for every language."""
    for name in ("README.md", "README.en.md", "README.zh-CN.md"):
        text = (ROOT / name).read_text(encoding="utf-8-sig")
        if "INSTALL.md" not in text:
            errors.append("readme-install-entry-missing: " + name)
    navigation = (("README.zh-CN.md", "](README.md)"), ("README.md", "](README.en.md)"),
                  ("README.en.md", "](README.md)"))
    for name, marker in navigation:
        if marker not in (ROOT / name).read_text(encoding="utf-8-sig"):
            errors.append("readme-navigation-missing: " + name + ": " + marker)


def check_agent_prompts(errors):
    for language in ("en", "zh-CN"):
        prompt = ROOT / "docs" / language / "agent-install-prompt.md"
        text = prompt.read_text(encoding="utf-8-sig")
        for marker in GENERIC_PROMPT_MARKERS[language]:
            if marker not in text:
                errors.append("generic-prompt-marker-missing: %s: %s" % (language, marker))
        match = PRODUCT_SPECIFIC_INTERFACE.search(text)
        if match:
            errors.append("generic-prompt-names-product-interface: %s: %s" % (language, match.group(0)))
        compatibility = (ROOT / "docs" / language / "codex-install-prompt.md").read_text(encoding="utf-8-sig")
        if "](agent-install-prompt.md)" not in compatibility:
            errors.append("legacy-prompt-does-not-point-to-generic-prompt: " + language)
        if "```text" in compatibility:
            errors.append("legacy-prompt-duplicates-executable-prompt: " + language)
    local = "docs/%s/offline-install.md"
    for language in ("en", "zh-CN"):
        for name in ("docs/%s/agent-local-install-prompt.md" % language, local % language):
            if PRE_EXPANDED_BUNDLE.search((ROOT / name).read_text(encoding="utf-8-sig")):
                errors.append("local-installation-requires-pre-expanded-bundle: " + name)


def check_published_content(errors):
    """No personal port, removed guide or maintainer-only routing policy in public files."""
    scanned = [ROOT / "README.md", ROOT / "README.en.md", ROOT / "README.zh-CN.md",
               ROOT / "docs", ROOT / "examples"]
    for target in scanned:
        if not target.exists():
            continue
        files = sorted(target.rglob("*")) if target.is_dir() else [target]
        for path in files:
            if not path.is_file():
                continue
            body = path.read_bytes()
            if PRIVATE_VALUES.search(body):
                errors.append("published-content-leaks-private-value: " + relative(path))
            if path.suffix.lower() == ".md" and MAINTAINER_ROUTING_POLICY.search(body):
                errors.append("maintainer-routing-policy-in-public-documentation: " + relative(path))


def installer_parameters():
    """Flags the real installer accepts, read from the two entry points themselves."""
    accepted = set()
    bootstrap = (ROOT / "scripts" / "bootstrap.py").read_text(encoding="utf-8")
    accepted.update(re.findall(r'add_argument\(\s*"(--[A-Za-z0-9][A-Za-z0-9-]*)"', bootstrap))
    shell = (ROOT / "install.sh").read_text(encoding="utf-8")
    usage = shell.split("usage() {", 1)[-1].split("\nEOF", 1)[0]
    accepted.update(re.findall(r"(?<![A-Za-z0-9_-])(--?[A-Za-z][A-Za-z0-9-]*)", usage))
    return accepted


def check_install_parameters(errors):
    """Every `install.sh --<flag>` in the documentation must still exist.

    The retired 0.9.x flags used to be required by tests/docs-test.sh; the same
    pages now fail the build instead of failing only an agent's install run.
    """
    accepted = installer_parameters()
    for document in documents():
        if not document.is_file():
            continue
        name = relative(document)
        if name in ARCHIVED_PAGES:
            if not any(ARCHIVE_BANNER.search(line) and any(word in line for word in ARCHIVE_WORDS)
                       for line in document.read_text(encoding="utf-8-sig").splitlines()[:10]):
                errors.append("archived-page-missing-banner: " + name)
            continue
        for number, line in enumerate(document.read_text(encoding="utf-8-sig").splitlines(), 1):
            for segment in SEGMENT_BREAK.split(line):
                if not INSTALL_SH.search(segment):
                    continue
                for flag in FLAG.findall(segment):
                    if flag not in accepted:
                        errors.append("unknown-install-parameter: %s:%d: %s" % (name, number, flag))


def main():
    errors = []
    check_documents(errors)
    check_entrypoints(errors)
    check_bilingual_topics(errors)
    check_readme_entry(errors)
    check_agent_prompts(errors)
    check_published_content(errors)
    check_install_parameters(errors)
    for error in errors:
        print(error)
    if not errors:
        print("documentation: required V1 documents, local links and installer "
              "parameters passed")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
