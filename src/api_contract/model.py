"""Core data types: severities, directions and the ``Change`` record."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ApiContractError(Exception):
    """A user-facing failure (bad config, unreadable spec, ...). The CLI exits 2."""


class Severity(str, Enum):
    BREAKING = "breaking"
    POTENTIALLY_BREAKING = "potentially-breaking"
    SAFE = "safe"

    @property
    def rank(self) -> int:
        """Higher is worse; used for sorting and for ``fail_on`` thresholds."""
        return {"safe": 0, "potentially-breaking": 1, "breaking": 2}[self.value]

    @property
    def label(self) -> str:
        return self.value.replace("-", " ").upper()


class Direction(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NONE = "none"


_PATH_PARAM = re.compile(r"\{[^}/]*\}")


def positional_path(path: str) -> str:
    """``/orders/{order_id}/items/{id}`` -> ``/orders/{}/items/{}``.

    Path parameter names are not part of the wire contract, so renaming one must
    not change a change id or show up as a removed + added endpoint.
    """
    return _PATH_PARAM.sub("{}", path)


_ID_TAIL = re.compile(
    r":(?=(?:request|response|param|security|endpoint-[a-z-]+|method-[a-z-]+)(?::|$)|\*)"
)


def canonical_id(change_id: str) -> str:
    """Normalize a user-written id (e.g. from the allowlist) for comparison."""
    method, sep, rest = change_id.strip().partition(" ")
    if not sep:
        return change_id.strip()
    # Paths may contain ":" (`/v1/things:cancel`), so the path ends at the first
    # ":" that starts what an id puts after it: a location, an endpoint-level
    # kind, or a wildcard.
    match = _ID_TAIL.search(rest)
    path, tail = (rest[: match.start()], rest[match.start() :]) if match else (rest, "")
    return f"{method.upper()} {positional_path(path)}{tail}"


@dataclass
class Change:
    """One difference between two API contracts.

    ``path`` is positional (``/orders/{}``) and is what ids are built from;
    ``raw_path`` keeps the original template from the new spec (old spec for
    removed endpoints), which is what loaders' ``attribute()`` receives and what
    reports show.
    """

    kind: str
    severity: Severity
    direction: Direction
    method: str | None
    path: str | None
    raw_path: str | None
    location: str = ""
    pointer: str = ""
    detail: str | None = None
    old: Any = None
    new: Any = None
    message: str = ""
    component: str | None = None
    attribution: str | None = None
    # Set by the allowlist step: the entry that acknowledged this change.
    allowed_by: Any = field(default=None, compare=False)

    @property
    def id(self) -> str:
        """Stable, readable id, e.g. ``GET /api/orders/{}:response:200:total:type-changed``.

        JSON bodies are the overwhelmingly common case, so ``application/json``
        is left out of the id to keep it short; any other media type stays in.
        """
        head = f"{self.method} {self.path}" if self.method else (self.path or "")
        location = re.sub(r":application/json$", "", self.location)
        parts = [head, location, self.pointer, self.kind, self.detail or ""]
        return ":".join(p for p in parts if p)

    @property
    def endpoint(self) -> str:
        """``GET /api/orders/{id}/`` as written in the spec, for display."""
        path = self.raw_path or self.path or ""
        return f"{self.method} {path}" if self.method else path

    @property
    def allowed(self) -> bool:
        return self.allowed_by is not None

    def sort_key(self) -> tuple:
        return (
            -self.severity.rank,
            self.path or "",
            self.method or "",
            self.location,
            self.pointer,
            self.kind,
            self.detail or "",
        )

    def to_dict(self) -> dict[str, Any]:
        allowed = None
        if self.allowed_by is not None:
            allowed = self.allowed_by.to_dict()
        return {
            "id": self.id,
            "kind": self.kind,
            "severity": self.severity.value,
            "direction": self.direction.value,
            "method": self.method,
            "path": self.path,
            "raw_path": self.raw_path,
            "location": self.location,
            "pointer": self.pointer,
            "detail": self.detail,
            "old": self.old,
            "new": self.new,
            "message": self.message,
            "component": self.component,
            "attribution": self.attribution,
            "allowed": allowed,
        }
