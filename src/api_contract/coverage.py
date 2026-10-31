"""How much of the contract the schema actually describes.

A schema diff is blind to whatever the schema leaves out. ``api-contract
coverage`` (and the warnings ``check`` prints) make that visible:

* **typed responses**: operations whose success response declares a body
  schema (or is a 204/304 with nothing to declare). A response typed as
  "anything" (``{}``) or with no content at all is a blind spot;
* **declared errors**: operations that list at least one 4xx/5xx or
  ``default`` response, so a change to the error envelope is caught;
* **declared auth**: operations with a security requirement, so adding or
  removing auth is caught.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ._safety import clean
from .normalize import METHODS, RAW_PATH

_NO_BODY = {"204", "205", "304"}


@dataclass
class OperationCoverage:
    endpoint: str
    typed_response: bool
    declares_errors: bool
    declares_auth: bool


@dataclass
class Coverage:
    operations: list[OperationCoverage] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.operations)

    def _pct(self, attr: str) -> float:
        if not self.operations:
            return 0.0
        return 100.0 * sum(1 for op in self.operations if getattr(op, attr)) / self.total

    @property
    def typed_pct(self) -> float:
        return self._pct("typed_response")

    @property
    def errors_pct(self) -> float:
        return self._pct("declares_errors")

    @property
    def auth_pct(self) -> float:
        return self._pct("declares_auth")

    def to_dict(self) -> dict[str, Any]:
        return {
            "operations": self.total,
            "typed_responses_pct": round(self.typed_pct, 1),
            "declared_errors_pct": round(self.errors_pct, 1),
            "declared_auth_pct": round(self.auth_pct, 1),
            "untyped": [op.endpoint for op in self.operations if not op.typed_response],
            "no_error_responses": [op.endpoint for op in self.operations if not op.declares_errors],
            "no_auth": [op.endpoint for op in self.operations if not op.declares_auth],
        }


def _typed(responses: dict[str, Any]) -> bool:
    success = {code: r for code, r in responses.items() if code.startswith("2") or code == "2XX"}
    if not success:
        return False
    for code, response in success.items():
        if code in _NO_BODY:
            return True
        for media in (response.get("content") or {}).values():
            if isinstance(media, dict) and media.get("schema"):
                return True
    return False


def measure(normalized: dict[str, Any]) -> Coverage:
    """Coverage of a *normalized* document."""
    result = Coverage()
    for path, item in sorted((normalized.get("paths") or {}).items()):
        raw = item.get(RAW_PATH, path)
        for method in METHODS:
            op = item.get(method)
            if not isinstance(op, dict):
                continue
            responses = op.get("responses") or {}
            result.operations.append(
                OperationCoverage(
                    endpoint=f"{method.upper()} {raw}",
                    typed_response=_typed(responses),
                    declares_errors=any(
                        c.startswith(("4", "5")) or c == "DEFAULT" for c in responses
                    ),
                    declares_auth=bool(op.get("security")),
                )
            )
    return result


def warnings_for(normalized: dict[str, Any]) -> list[str]:
    """Warnings for a schema too thin for the check to mean much."""
    cov = measure(normalized)
    if cov.total == 0:
        return [
            "the schema has no operations, so nothing is being checked; is the source "
            "right? (Flask apps without an OpenAPI library: try the flask-routes: source)"
        ]
    if cov.typed_pct == 0:
        return [
            f"none of the {cov.total} operations declares a typed success response, so "
            "only endpoints, parameters and status codes are compared; see "
            "`api-contract coverage`"
        ]
    return []


def render_text(cov: Coverage, *, limit: int = 20) -> str:
    lines = [
        f"API contract coverage: {cov.total} operations",
        f"  typed success response  {cov.typed_pct:5.1f}%",
        f"  declared error response {cov.errors_pct:5.1f}%",
        f"  declared auth           {cov.auth_pct:5.1f}%",
    ]
    data = cov.to_dict()
    for key, title in (
        ("untyped", "Untyped success responses"),
        ("no_error_responses", "No 4xx/5xx/default response declared"),
    ):
        items = data[key]
        if not items:
            continue
        lines += ["", f"{title} ({len(items)}):"]
        lines += [f"  {clean(endpoint)}" for endpoint in items[:limit]]
        if len(items) > limit:
            lines.append(f"  ... and {len(items) - limit} more (--format json lists all)")
    return "\n".join(lines) + "\n"
