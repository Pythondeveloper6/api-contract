"""Policies applied after the diff: client profiles, frozen paths and sunsets.

The differ judges each change on its own. These policies add what only the
project knows:

* **Client profiles** (``[tool.api-contract.clients.<name>]``): endpoints a
  given client uses (by path glob or OpenAPI tag) get that client's rules and
  failure threshold. An app-store mobile client that can't upgrade in lockstep
  can fail on ``potentially-breaking`` while the web client fails on
  ``breaking`` only.
* **Frozen paths** (``frozen = ["/v1/*"]``): every change under a frozen
  prefix is breaking, even an addition. ``/v1/`` is frozen while ``/v2/``
  evolves.
* **Sunsets**: an operation marked ``deprecated: true`` with an
  ``x-sunset: YYYY-MM-DD`` date may be removed once that date has passed (the
  removal becomes safe). Removing it before the date stays breaking and the
  message says how early it is.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any

from .model import Change, Severity
from .normalize import SUNSET, TAGS
from .rules import Rules

_REMOVALS = {"endpoint-removed", "method-removed"}
_ADDITIONS = {"endpoint-added", "method-added"}


@dataclass
class ClientProfile:
    """Endpoints one client depends on, and how strictly to judge them."""

    name: str
    paths: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    fail_on: Severity | None = None
    rules: dict[str, Severity] = field(default_factory=dict)

    def matches(self, change: Change, tags: set[str]) -> bool:
        if any(_path_matches(change, pattern) for pattern in self.paths):
            return True
        return bool(tags.intersection(self.tags))


def _path_matches(change: Change, pattern: str) -> bool:
    candidates = {change.raw_path or "", change.path or ""}
    return any(c and fnmatchcase(c, pattern) for c in candidates)


def _operation(doc: dict[str, Any] | None, change: Change) -> dict[str, Any]:
    if not doc or not change.path or not change.method:
        return {}
    op = (doc.get("paths") or {}).get(change.path, {}).get(change.method.lower())
    return op if isinstance(op, dict) else {}


def _parse_date(value: Any) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def apply_policies(
    changes: list[Change],
    old: dict[str, Any] | None,
    new: dict[str, Any] | None,
    *,
    base_rules: dict[str, Severity] | None = None,
    clients: list[ClientProfile] | tuple[ClientProfile, ...] = (),
    frozen: tuple[str, ...] | list[str] = (),
    today: dt.date | None = None,
) -> None:
    """Adjust severities in place. ``old`` / ``new`` are *normalized* documents."""
    today = today or dt.date.today()
    for change in changes:
        old_op, new_op = _operation(old, change), _operation(new, change)
        tags = set(new_op.get(TAGS) or ()) | set(old_op.get(TAGS) or ())

        for profile in clients:
            if profile.matches(change, tags):
                change.client = profile.name
                change.fail_on = profile.fail_on
                if profile.rules:
                    rules = Rules({**(base_rules or {}), **profile.rules})
                    change.severity = rules.severity(change.kind)
                break

        if change.kind in _REMOVALS and old_op.get("deprecated") is True:
            sunset = _parse_date(old_op.get(SUNSET))
            if sunset is not None and sunset <= today:
                change.severity = Severity.SAFE
                change.message += f" (deprecated, sunset {sunset.isoformat()} has passed)"
            elif sunset is not None:
                days = (sunset - today).days
                change.message += (
                    f" before its sunset date {sunset.isoformat()} ({days} days early)"
                )
            else:
                change.message += " (deprecated, but no x-sunset date was declared)"

        for pattern in frozen:
            if _path_matches(change, pattern):
                change.severity = Severity.BREAKING
                change.message += f" [frozen: {pattern}]"
                break
    changes.sort(key=Change.sort_key)


def apply_usage(
    changes: list[Change],
    hits: dict[tuple[str, str], int],
    *,
    unused_severity: Severity | None = None,
) -> None:
    """Record traffic per change; optionally downgrade changes nobody exercised.

    ``hits`` maps ``(METHOD, positional path)`` to a request count (see
    :mod:`api_contract.usage`). Added endpoints have no traffic by definition
    and are left alone.
    """
    for change in changes:
        if not change.method or not change.path or change.kind in _ADDITIONS:
            continue
        change.hits = hits.get((change.method, change.path), 0)
        if (
            change.hits == 0
            and unused_severity is not None
            and change.severity.rank > unused_severity.rank
        ):
            change.severity = unused_severity
            change.message += " (no traffic in the usage sample)"
    changes.sort(key=Change.sort_key)
