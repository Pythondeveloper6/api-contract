"""Fold changes that differ only in endpoint or media type into one report entry.

Removing one serializer field shows up once per operation and per content type
(json, form, multipart). Text and markdown reports show it once, listing the
endpoints. The JSON report never groups: ids and per-change objects stay as is.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..model import Change

_MEDIA_TYPE = re.compile(r"^[\w.+*-]+/[\w.+*-]+$")


def split_location(location: str) -> tuple[str, str | None]:
    """``response:200:multipart/form-data`` -> ``("response:200", "multipart/form-data")``."""
    head, _, last = location.rpartition(":")
    if head and _MEDIA_TYPE.match(last) and location.split(":", 1)[0] in ("request", "response"):
        return head, last
    return location, None


def base_message(change: Change) -> str:
    """The message without the ``(application/xml)`` media-type marker the diff adds."""
    media_type = split_location(change.location)[1]
    if media_type:
        return change.message.replace(f" ({media_type})", "")
    return change.message


@dataclass
class ChangeGroup:
    changes: list[Change]

    @property
    def first(self) -> Change:
        return self.changes[0]

    @property
    def message(self) -> str:
        return base_message(self.first)

    @property
    def endpoints(self) -> list[str]:
        return sorted({c.endpoint for c in self.changes})

    @property
    def media_types(self) -> list[str]:
        return sorted({m for c in self.changes if (m := split_location(c.location)[1])})

    @property
    def attributions(self) -> list[str]:
        return list(dict.fromkeys(c.attribution for c in self.changes if c.attribution))

    @property
    def ids(self) -> list[str]:
        return [c.id for c in self.changes]


def group_changes(changes: list[Change], *, group: bool = True) -> list[ChangeGroup]:
    """Group in order of first appearance. With ``group=False`` every change is its own entry."""
    if not group:
        return [ChangeGroup([c]) for c in changes]
    groups: dict[tuple, ChangeGroup] = {}
    for change in changes:
        key = (
            change.severity,
            change.kind,
            split_location(change.location)[0],
            change.pointer,
            change.detail,
            base_message(change),
            id(change.allowed_by) if change.allowed_by is not None else None,
        )
        # Endpoint-level changes (no pointer, e.g. "endpoint removed") are distinct facts
        # about different endpoints; only fold changes that point into a schema.
        if not change.pointer and not change.location:
            key += (change.endpoint,)
        groups.setdefault(key, ChangeGroup([])).changes.append(change)
    return list(groups.values())
