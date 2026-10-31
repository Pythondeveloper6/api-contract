"""Traffic samples for ``--usage``: count requests per operation.

Two input shapes are read, line by line, and may be mixed:

* access logs in Common/Combined Log Format (nginx, Apache, gunicorn,
  uvicorn): the ``"GET /api/orders/42?x=1 HTTP/1.1"`` request part is used;
* JSON lines with a method and a path or URL, under any of the usual keys
  (``method`` / ``request_method`` / ``http.method`` and ``path`` / ``url`` /
  ``uri`` / ``request_uri`` / ``http.target`` / ``url.path``). This covers
  structured app logs and most OpenTelemetry span exports flattened to JSON.

A line may carry a ``count`` (JSON) for pre-aggregated exports. Concrete
paths are matched to the spec's templates (``/api/orders/42`` ->
``/api/orders/{}``), static segments winning over parameters.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .model import ApiContractError

_LOG_REQUEST = re.compile(r'"([A-Z]+) (\S+)(?: HTTP/[\d.]+)?"')
_METHOD_KEYS = ("method", "request_method", "http.method", "http.request.method", "verb")
_PATH_KEYS = (
    "path",
    "url.path",
    "http.target",
    "request_uri",
    "uri",
    "url",
    "http.url",
    "url.full",
    "request",
)


@dataclass
class UsageSample:
    """Request counts keyed by ``(METHOD, positional path template)``."""

    hits: Counter[tuple[str, str]] = field(default_factory=Counter)
    lines: int = 0
    unmatched: int = 0


def _lookup(record: dict[str, Any], key: str) -> Any:
    if key in record:
        return record[key]
    node: Any = record
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _parse_line(line: str) -> tuple[str, str, int] | None:
    line = line.strip()
    if not line:
        return None
    if line.startswith("{"):
        try:
            record = json.loads(line)
        except ValueError:
            record = None
        if isinstance(record, dict):
            attrs = record.get("attributes")
            if isinstance(attrs, dict):  # OpenTelemetry spans keep these under attributes
                record = {**attrs, **record}
            method = next((_lookup(record, k) for k in _METHOD_KEYS if _lookup(record, k)), None)
            target = next((_lookup(record, k) for k in _PATH_KEYS if _lookup(record, k)), None)
            if isinstance(target, str) and isinstance(method, str) and " " in target.strip():
                target = target.split()[1] if len(target.split()) > 1 else target
            if isinstance(method, str) and isinstance(target, str):
                count = record.get("count", 1)
                return method.upper(), target, count if isinstance(count, int) else 1
            return None
    match = _LOG_REQUEST.search(line)
    if match:
        return match.group(1), match.group(2), 1
    return None


def _path_of(target: str) -> str:
    parts = urlsplit(target)
    return parts.path or "/"


class _Matcher:
    def __init__(self, templates: Iterable[str]) -> None:
        compiled = []
        for template in templates:
            regex = "^" + "[^/]+".join(re.escape(p) for p in template.split("{}")) + "/?$"
            # Fewer parameters and longer literal text first: /orders/new beats /orders/{}.
            literal = len(template.replace("{}", ""))
            compiled.append((template.count("{}"), -literal, template, re.compile(regex)))
        self.templates = sorted(compiled)

    def match(self, path: str) -> str | None:
        for _, _, template, regex in self.templates:
            if regex.match(path) or regex.match(path.rstrip("/") + "/"):
                return template
        return None


def read_usage(paths: Iterable[str | Path], templates: Iterable[str]) -> UsageSample:
    """Count requests in the given files against the spec's path templates."""
    matcher = _Matcher(templates)
    sample = UsageSample()
    for path in paths:
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise ApiContractError(f"cannot read usage file {path}: {exc.strerror or exc}") from exc
        for line in text.splitlines():
            parsed = _parse_line(line)
            if parsed is None:
                continue
            sample.lines += 1
            method, target, count = parsed
            template = matcher.match(_path_of(target))
            if template is None:
                sample.unmatched += 1
                continue
            sample.hits[(method, template)] += count
    return sample
