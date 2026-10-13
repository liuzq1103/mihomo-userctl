#!/usr/bin/env python3
"""Stable, compact JSON serialization for public mihomo-userctl reports."""

import json


DIAGNOSTICS_SCHEMA = "mihomo-userctl.diagnostics/v1"
RULES_SCHEMA = "mihomo-userctl.rules/v1"


def emit(document):
    """Write exactly one deterministic JSON object to stdout."""
    print(json.dumps(document, sort_keys=True, separators=(",", ":")))


def diagnostics(command, overall, payload=None, error=None):
    document = {"schema": DIAGNOSTICS_SCHEMA, "command": command,
                "overall": overall}
    if payload:
        document.update(payload)
    if error:
        document["error"] = {"code": error}
    emit(document)


def rules(command, overall, payload=None, error=None):
    document = {"schema": RULES_SCHEMA, "command": command,
                "overall": overall}
    if payload:
        document.update(payload)
    if error:
        document["error"] = {"code": error}
    emit(document)
