"""The single public JSON envelope (schema mihomoctl/v1) and check model."""

from dataclasses import dataclass, field, asdict

from . import SCHEMA

PASS = "PASS"
FAIL = "FAIL"
UNVERIFIED = "UNVERIFIED"
SKIPPED = "SKIPPED"

CONFIRMED = "confirmed"
INFERRED = "inferred"
UNAVAILABLE = "unavailable"

_ORDER = {PASS: 0, SKIPPED: 1, UNVERIFIED: 2, FAIL: 3}


@dataclass
class Check:
    name: str
    status: str
    evidence: str = CONFIRMED
    detail: str = ""

    def to_dict(self):
        row = {"name": self.name, "status": self.status, "evidence": self.evidence}
        if self.detail:
            row["detail"] = self.detail
        return row


def combine(statuses):
    """Overall from check statuses: FAIL > UNVERIFIED > PASS; SKIPPED neutral."""
    worst = PASS
    for status in statuses:
        if status not in _ORDER:
            status = UNVERIFIED
        if status == SKIPPED:
            continue
        if _ORDER.get(status, _ORDER[UNVERIFIED]) > _ORDER[worst]:
            worst = status
    return worst


def combine_checks(checks):
    return combine([check.status for check in checks])


def envelope(command, scope_name, overall, data=None, checks=None, errors=None):
    document = {
        "schema": SCHEMA,
        "command": command,
        "scope": scope_name,
        "overall": overall,
    }
    document["data"] = data if data is not None else {}
    document["checks"] = [check.to_dict() if isinstance(check, Check) else check for check in (checks or [])]
    document["errors"] = list(errors or [])
    return document


def exit_code(overall):
    if overall == PASS:
        return 0
    if overall == FAIL:
        return 1
    return 2
