"""Plain-text report for terminals and CI logs."""

from __future__ import annotations

import datetime as dt
import shlex

from ..core import CheckResult
from ..model import Severity
from .grouping import ChangeGroup, group_changes

_SECTIONS = (Severity.BREAKING, Severity.POTENTIALLY_BREAKING, Severity.SAFE)


def summary_line(result: CheckResult) -> str:
    total = len(result.changes)
    if not total:
        return "API contract: no changes"
    noun = "change" if total == 1 else "changes"
    parts = [f"{result.count(Severity.BREAKING)} breaking"]
    allowed = sum(1 for c in result.changes if c.allowed)
    if allowed:
        parts.append(f"{allowed} allowed")
    return f"API contract: {total} {noun} ({', '.join(parts)})"


def default_expiry(today: dt.date | None = None) -> str:
    return ((today or dt.date.today()) + dt.timedelta(days=30)).isoformat()


def _change_lines(group: ChangeGroup, *, show_id: bool) -> list[str]:
    change = group.first
    message = change.message if len(group.changes) == 1 else group.message
    if len(group.changes) == 1:
        lines = [f"  {change.endpoint}  {message}"]
    else:
        endpoints = group.endpoints
        if len(endpoints) == 1:
            lines = [f"  {endpoints[0]}  {message}"]
        else:
            lines = [f"  {message}  ({len(endpoints)} endpoints)"]
            lines += [f"      {endpoint}" for endpoint in endpoints]
        if group.media_types:
            lines.append(f"      media types: {', '.join(group.media_types)}")
    for attribution in group.attributions:
        lines.append(f"      at: {attribution}")
    if change.client:
        lines.append(f"      client: {change.client}")
    if change.hits is not None:
        hits = sum(c.hits or 0 for c in group.changes)
        lines.append(f"      traffic: {hits} request{'s' if hits != 1 else ''} in the usage sample")
    if change.allowed_by is not None:
        entry = change.allowed_by
        lines.append(f"      allowed until {entry.expires.isoformat()}: {entry.reason}")
    elif show_id:
        lines.append(f"      id: {change.id}")
        if len(group.changes) > 1:
            lines.append(
                f"      (+{len(group.changes) - 1} similar changes; "
                "--no-group or --format json lists every id)"
            )
    return lines


def render(
    result: CheckResult,
    *,
    command: str = "api-contract",
    today: dt.date | None = None,
    group: bool = True,
) -> str:
    lines = [summary_line(result)]
    lines += [f"WARNING: {w}" for w in result.warnings]
    for severity in _SECTIONS:
        changes = [c for c in result.changes if c.severity is severity]
        if not changes:
            continue
        lines += ["", severity.label]
        for entry in group_changes(changes, group=group):
            lines += _change_lines(entry, show_id=severity is not Severity.SAFE)

    if result.expired:
        lines += ["", "EXPIRED ALLOWLIST ENTRIES (these fail the check)"]
        for entry in result.expired:
            lines.append(f"  {entry.id}  expired {entry.expires.isoformat()}: {entry.reason}")
    if result.stale:
        lines += ["", "STALE ALLOWLIST ENTRIES (match no change; consider removing)"]
        lines += [f"  {entry.id}" for entry in result.stale]

    failing = result.failing
    if failing:
        hint = f"{command} allow {shlex.quote(failing[0].id)}"
        lines += [
            "",
            "Fix the change, or acknowledge it:",
            f'  {hint} --reason "..." --expires {default_expiry(today)}',
        ]
    return "\n".join(lines) + "\n"
