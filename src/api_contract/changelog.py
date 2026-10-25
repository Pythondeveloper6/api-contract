"""Consumer-facing changelog: what changed in the API, written for its clients.

Unlike the check report it carries no ids, severities or attribution — only
what an API consumer needs, grouped by how much it should worry them.
"""

from __future__ import annotations

from collections import defaultdict

from .model import Change, Severity

_SECTIONS = (
    (Severity.BREAKING, "Breaking changes"),
    (Severity.POTENTIALLY_BREAKING, "Changes that may affect you"),
    (Severity.SAFE, "New and improved"),
)


def _endpoint(change: Change) -> str:
    return f"`{change.method} {change.raw_path or change.path}`"


def render_changelog(changes: list[Change], *, title: str = "API changes") -> str:
    lines = [f"## {title}", ""]
    if not changes:
        return "\n".join([*lines, "No changes to the API contract.", ""])
    deprecated = [c for c in changes if c.kind in {"endpoint-deprecated", "param-deprecated"}]
    deprecated += [c for c in changes if c.kind == "field-deprecated"]
    skip = {id(c) for c in deprecated}
    for severity, heading in _SECTIONS:
        section = [c for c in changes if c.severity is severity and id(c) not in skip]
        if not section:
            continue
        lines += [f"### {heading}", ""]
        added = [c for c in section if c.kind in {"endpoint-added", "method-added"}]
        lines += [f"- New endpoint {_endpoint(c)}" for c in added]
        grouped: dict[str, list[Change]] = defaultdict(list)
        for change in section:
            if change.kind not in {"endpoint-added", "method-added"}:
                grouped[_endpoint(change)].append(change)
        for endpoint, items in grouped.items():
            if len(items) == 1:
                lines.append(f"- {endpoint}: {items[0].message}")
            else:
                lines.append(f"- {endpoint}:")
                lines += [f"  - {c.message}" for c in items]
        lines.append("")
    if deprecated:
        lines += ["### Deprecations", ""]
        lines += [f"- {_endpoint(c)}: {c.message}" for c in deprecated]
        lines.append("")
    return "\n".join(lines)
