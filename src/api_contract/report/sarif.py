"""SARIF 2.1.0 report, for GitHub code scanning and other SARIF consumers."""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

from .. import __version__
from ..core import CheckResult
from ..model import Change, Severity

INFORMATION_URI = "https://github.com/Pythondeveloper6/api-contract"
HELP_URI = "https://pythondeveloper6.github.io/api-contract/rules/"
EXPIRED_RULE = "allowlist-entry-expired"

# "app.main.Order (app/main.py:7)" -> file and line of the code behind a change.
_FILE_LINE = re.compile(r"\((?P<file>[^()]+?):(?P<line>\d+)\)\s*$")


def parse_location(attribution: str | None) -> tuple[str, int] | None:
    """The ``(file, line)`` in an attribution string, or None when it has none."""
    match = _FILE_LINE.search(attribution or "")
    if not match:
        return None
    uri = match["file"].replace("\\", "/").removeprefix("./")
    return uri, int(match["line"])


def level_for(change: Change, failing: set[int]) -> str:
    if id(change) in failing:
        return "error"
    return "note" if change.severity is Severity.SAFE else "warning"


def _locations(change: Change) -> list[dict[str, Any]]:
    location: dict[str, Any] = {"logicalLocations": [{"name": change.endpoint, "kind": "resource"}]}
    found = parse_location(change.attribution)
    if found:
        uri, line = found
        location["physicalLocation"] = {
            "artifactLocation": {"uri": uri},
            "region": {"startLine": line},
        }
    return [location]


def _rule(kind: str, description: str) -> dict[str, Any]:
    return {
        "id": kind,
        "shortDescription": {"text": description},
        "helpUri": HELP_URI,
    }


def render(
    result: CheckResult,
    *,
    command: str = "api-contract",
    today: dt.date | None = None,
    group: bool = True,
    **_: Any,
) -> str:
    failing = {id(c) for c in result.failing}
    rules = {c.kind: _rule(c.kind, c.kind.replace("-", " ")) for c in result.changes}
    if result.expired:
        rules[EXPIRED_RULE] = _rule(EXPIRED_RULE, "allowlist entry expired")

    results: list[dict[str, Any]] = []
    for change in result.changes:
        entry: dict[str, Any] = {
            "ruleId": change.kind,
            "level": level_for(change, failing),
            "message": {"text": f"{change.endpoint} {change.message}"},
            "locations": _locations(change),
            "partialFingerprints": {"apiContractId/v1": change.id},
        }
        if change.allowed_by is not None:
            entry["suppressions"] = [
                {"kind": "external", "justification": change.allowed_by.reason}
            ]
        results.append(entry)
    for expired in result.expired:
        results.append(
            {
                "ruleId": EXPIRED_RULE,
                "level": "error",
                "message": {
                    "text": f"{expired.id} expired {expired.expires.isoformat()}: {expired.reason}"
                },
                "partialFingerprints": {"apiContractId/v1": expired.id},
            }
        )

    sarif = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "api-contract",
                        "version": __version__,
                        "informationUri": INFORMATION_URI,
                        "rules": [rules[k] for k in sorted(rules)],
                    }
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2) + "\n"
