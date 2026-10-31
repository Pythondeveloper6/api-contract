"""JUnit XML report, for GitLab (``artifacts:reports:junit``), Jenkins and similar."""

from __future__ import annotations

import datetime as dt
import xml.etree.ElementTree as ET
from typing import Any

from ..core import CheckResult
from .sarif import EXPIRED_RULE


def render(
    result: CheckResult,
    *,
    command: str = "api-contract",
    today: dt.date | None = None,
    group: bool = True,
    **_: Any,
) -> str:
    failing = {id(c) for c in result.failing}
    cases: list[ET.Element] = []
    failures = skipped = 0
    for change in result.changes:
        case = ET.Element("testcase", classname=change.endpoint, name=change.id)
        if id(change) in failing:
            failures += 1
            failure = ET.SubElement(case, "failure", type=change.kind, message=change.message)
            failure.text = f"{change.endpoint} {change.message}"
        elif change.allowed_by is not None:
            skipped += 1
            entry = change.allowed_by
            message = f"allowed until {entry.expires.isoformat()}: {entry.reason}"
            ET.SubElement(case, "skipped", message=message)
        cases.append(case)
    for entry in result.expired:
        failures += 1
        case = ET.Element("testcase", classname="allowlist", name=entry.id)
        message = f"expired {entry.expires.isoformat()}: {entry.reason}"
        ET.SubElement(case, "failure", type=EXPIRED_RULE, message=message).text = message
        cases.append(case)

    counts = {"tests": str(len(cases)), "failures": str(failures), "skipped": str(skipped)}
    root = ET.Element("testsuites", counts)
    suite = ET.SubElement(root, "testsuite", {"name": "api-contract", "errors": "0", **counts})
    suite.extend(cases)
    ET.indent(root)
    return (
        ET.tostring(root, encoding="unicode", xml_declaration=True).replace(
            "<?xml version='1.0' encoding='utf-8'?>", '<?xml version="1.0" encoding="utf-8"?>'
        )
        + "\n"
    )
