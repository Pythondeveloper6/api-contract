"""Markdown report, shaped for a pull-request comment."""

from __future__ import annotations

import datetime as dt
import shlex

from ..core import CheckResult
from ..model import Severity
from .grouping import ChangeGroup, group_changes
from .text import default_expiry, summary_line

_TITLES = {
    Severity.BREAKING: "Breaking",
    Severity.POTENTIALLY_BREAKING: "Potentially breaking",
    Severity.SAFE: "Safe",
}


def _code(text: str) -> str:
    # Backticks inside inline code would end it early.
    return "`` " + text + " ``" if "`" in text else f"`{text}`"


def _item(group: ChangeGroup) -> list[str]:
    change = group.first
    message = change.message if len(group.changes) == 1 else group.message
    if len(group.changes) == 1:
        lines = [
            f"- **{change.method}** {_code(change.raw_path or change.path or '')} — {message}"
            if change.method
            else f"- {_code(change.raw_path or change.path or '')} — {message}"
        ]
    else:
        endpoints = group.endpoints
        if len(endpoints) == 1:
            lines = [f"- {_code(endpoints[0])} — {message}"]
        else:
            lines = [f"- {message} ({len(endpoints)} endpoints)"]
            lines += [f"  - {_code(endpoint)}" for endpoint in endpoints]
        if group.media_types:
            lines.append(f"  - media types: {', '.join(_code(m) for m in group.media_types)}")
    for attribution in group.attributions:
        lines.append(f"  - at {_code(attribution)}")
    if change.allowed_by is not None:
        entry = change.allowed_by
        lines.append(f"  - allowed until {entry.expires.isoformat()}: {entry.reason}")
    elif change.severity is not Severity.SAFE:
        lines.append(f"  - id: {_code(change.id)}")
        if len(group.changes) > 1:
            lines.append(
                f"  - plus {len(group.changes) - 1} similar changes "
                "(`--no-group` or `--format json` lists every id)"
            )
    return lines


def render(
    result: CheckResult,
    *,
    command: str = "api-contract",
    today: dt.date | None = None,
    group: bool = True,
) -> str:
    status = "passed" if result.ok else "failed"
    lines = [f"### {summary_line(result)} — {status}"]
    for severity in (Severity.BREAKING, Severity.POTENTIALLY_BREAKING, Severity.SAFE):
        changes = [c for c in result.changes if c.severity is severity]
        if not changes:
            continue
        title = f"{_TITLES[severity]} ({len(changes)})"
        body = [line for entry in group_changes(changes, group=group) for line in _item(entry)]
        if severity is Severity.SAFE:
            # Safe changes are context, not action items: keep them folded.
            lines += ["", f"<details><summary>{title}</summary>", "", *body, "", "</details>"]
        else:
            lines += ["", f"#### {title}", "", *body]

    if result.expired:
        lines += ["", "#### Expired allowlist entries", ""]
        lines += [
            f"- {_code(e.id)} expired {e.expires.isoformat()}: {e.reason}" for e in result.expired
        ]
    if result.stale:
        lines += ["", "#### Stale allowlist entries", ""]
        lines += [f"- {_code(e.id)} matches no change" for e in result.stale]

    failing = result.failing
    if failing:
        hint = f"{command} allow {shlex.quote(failing[0].id)}"
        lines += [
            "",
            "Fix the change, or acknowledge it:",
            "",
            "```sh",
            f'{hint} --reason "..." --expires {default_expiry(today)}',
            "```",
        ]
    return "\n".join(lines) + "\n"
