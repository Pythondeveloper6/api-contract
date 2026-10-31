"""GitHub Actions workflow commands: inline annotations on the run and the diff."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ..core import CheckResult
from ..model import Severity
from .sarif import EXPIRED_RULE, parse_location
from .text import summary_line


def escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(value: str) -> str:
    return escape_data(value).replace(":", "%3A").replace(",", "%2C")


def _command(level: str, title: str, message: str, location: tuple[str, int] | None) -> str:
    props = []
    if location:
        props += [f"file={escape_property(location[0])}", f"line={location[1]}"]
    props.append(f"title={escape_property(title)}")
    return f"::{level} {','.join(props)}::{escape_data(message)}"


def render(
    result: CheckResult,
    *,
    command: str = "api-contract",
    today: dt.date | None = None,
    group: bool = True,
    **_: Any,
) -> str:
    failing = {id(c) for c in result.failing}
    lines = []
    for change in result.changes:
        if change.severity is Severity.SAFE:
            continue
        level = "error" if id(change) in failing else "warning"
        lines.append(
            _command(
                level,
                f"api-contract: {change.kind}",
                f"{change.endpoint} {change.message} (id: {change.id})",
                parse_location(change.attribution),
            )
        )
    for entry in result.expired:
        message = f"{entry.id} expired {entry.expires.isoformat()}: {entry.reason}"
        lines.append(_command("error", f"api-contract: {EXPIRED_RULE}", message, None))
    lines.append(summary_line(result))
    return "\n".join(lines) + "\n"
