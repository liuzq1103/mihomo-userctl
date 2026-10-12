#!/usr/bin/env python3
"""Validate shipped Markdown links and V1 entry-point documentation."""
from pathlib import Path
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = ("README.md", "README.en.md", "INSTALL.md", "CHANGELOG.md", "SECURITY.md",
            "docs/architecture-v1.md", "docs/code-audit.md", "docs/design-reference.md",
            "docs/release-review.md", "docs/adr/0002-v1-generic-runtime.md")


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


def main():
    errors = []
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append("required-document-missing: " + name)
    documents = list((ROOT / "docs").rglob("*.md")) + [ROOT / n for n in REQUIRED if "/" not in n]
    for document in documents:
        if not document.is_file():
            continue
        text = document.read_text(encoding="utf-8-sig")
        if has_unclosed_fence(text):
            errors.append("unclosed-code-fence: " + str(document.relative_to(ROOT)))
        if "\ufffd" in text:
            errors.append("replacement-character: " + str(document.relative_to(ROOT)))
        for raw in re.findall(r"\]\(([^)]+)\)", text):
            target = raw.strip().split(" ", 1)[0].strip("<>").split("#", 1)[0]
            if not target or re.match(r"[A-Za-z][A-Za-z0-9+.-]*:", target):
                continue
            path = document.parent / unquote(target)
            if not path.exists():
                errors.append("broken-link: " + str(document.relative_to(ROOT)) + " -> " + target)
    for name in ("README.md", "README.en.md", "INSTALL.md"):
        if (ROOT / name).exists():
            text = (ROOT / name).read_text(encoding="utf-8-sig")
            for marker in ("mihomoctl", "--system", "profile", "init"):
                if marker not in text:
                    errors.append("v1-entrypoint-missing: " + name + ": " + marker)
    for error in errors:
        print(error)
    if not errors:
        print("documentation: required V1 documents and local links passed")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
