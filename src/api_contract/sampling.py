"""Runtime response sampling: do real responses match the contract?

A schema diff only sees what the schema declares. ``api-contract
verify-samples`` takes responses recorded from a running service (staging,
canary, a test run) and checks each one against the snapshot, catching drift
between what the code returns and what the contract promises.

Samples are JSON lines (``{"method", "path", "status", "body"}``; ``url``
may replace ``path`` and ``body`` may be a JSON string) or a HAR export from
browser dev tools or a proxy. The validator understands the normalized
schema: types, ``nullable``, ``properties`` / ``required`` /
``additionalProperties``, ``items``, ``enum``, ``const``, ``allOf`` /
``anyOf`` / ``oneOf`` and recursive components. Formats and numeric or string
limits are not enforced: they are about validation, not shape.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .model import ApiContractError
from .normalize import RECURSIVE, REF
from .usage import _Matcher

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
}


@dataclass
class Sample:
    method: str
    path: str
    status: str
    body: Any
    has_body: bool = True


@dataclass
class SampleReport:
    checked: int = 0
    problems: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems


def _decode(body: Any) -> tuple[Any, bool]:
    if body is None:
        return None, False
    if isinstance(body, str):
        try:
            return json.loads(body), True
        except ValueError:
            return body, True
    return body, True


def read_samples(path: str | Path) -> list[Sample]:
    """Read JSON-lines samples or a HAR file."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiContractError(f"cannot read samples {path}: {exc.strerror or exc}") from exc
    samples: list[Sample] = []
    stripped = text.lstrip()
    if stripped.startswith("{") and '"log"' in stripped[:200]:
        try:
            har = json.loads(text)
        except ValueError as exc:
            raise ApiContractError(f"{path} is not valid HAR JSON: {exc}") from exc
        for entry in har.get("log", {}).get("entries", []):
            request, response = entry.get("request", {}), entry.get("response", {})
            content = response.get("content", {})
            if "json" not in str(content.get("mimeType", "")):
                continue
            body, has = _decode(content.get("text"))
            samples.append(
                Sample(
                    method=str(request.get("method", "GET")).upper(),
                    path=urlsplit(str(request.get("url", ""))).path or "/",
                    status=str(response.get("status", "")),
                    body=body,
                    has_body=has,
                )
            )
        return samples
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError as exc:
            raise ApiContractError(f"{path}:{number}: not a JSON line: {exc}") from exc
        if not isinstance(record, dict) or "status" not in record:
            raise ApiContractError(f"{path}:{number}: needs method, path (or url) and status")
        target = record.get("path") or record.get("url") or ""
        body, has = _decode(record.get("body"))
        samples.append(
            Sample(
                method=str(record.get("method", "GET")).upper(),
                path=urlsplit(str(target)).path or "/",
                status=str(record["status"]),
                body=body,
                has_body=has and "body" in record,
            )
        )
    return samples


class _Validator:
    def __init__(self, recursive: dict[str, Any]) -> None:
        self.recursive = recursive

    def errors(self, schema: Any, value: Any, where: str, depth: int = 0) -> list[str]:
        if not isinstance(schema, dict) or not schema or depth > 100:
            return []
        if REF in schema:
            target = self.recursive.get(schema[REF], {})
            overlay = {k: v for k, v in schema.items() if k != REF}
            return self.errors({**target, **overlay}, value, where, depth + 1)
        if value is None:
            if schema.get("nullable") or "null" in _types(schema):
                return []
            if any(k in schema for k in ("anyOf", "oneOf")):
                pass  # a null member may sit in a variant
            elif _types(schema) or "properties" in schema:
                return [f"{where}: null is not allowed"]
        problems: list[str] = []
        types = _types(schema)
        if types and not any(_is_type(value, t) for t in types):
            return [f"{where}: expected {' or '.join(types)}, got {_type_name(value)}"]
        if "enum" in schema and value not in schema["enum"]:
            problems.append(f"{where}: {value!r} is not one of {schema['enum']!r}")
        if "const" in schema and value != schema["const"]:
            problems.append(f"{where}: expected {schema['const']!r}, got {value!r}")
        for member in schema.get("allOf") or []:
            problems += self.errors(member, value, where, depth + 1)
        for key in ("anyOf", "oneOf"):
            variants = schema.get(key)
            if variants and all(self.errors(v, value, where, depth + 1) for v in variants):
                problems.append(f"{where}: matches none of the {key} variants")
        if isinstance(value, dict):
            props = schema.get("properties") or {}
            for name in schema.get("required") or []:
                if name not in value:
                    problems.append(f"{where}.{name}: required field missing")
            for name, item in value.items():
                if name in props:
                    problems += self.errors(props[name], item, f"{where}.{name}", depth + 1)
                elif schema.get("additionalProperties") is False:
                    problems.append(f"{where}.{name}: field not declared in the contract")
                elif isinstance(schema.get("additionalProperties"), dict):
                    problems += self.errors(
                        schema["additionalProperties"], item, f"{where}.{name}", depth + 1
                    )
        if isinstance(value, list) and isinstance(schema.get("items"), dict):
            for index, item in enumerate(value):
                problems += self.errors(schema["items"], item, f"{where}[{index}]", depth + 1)
                if len(problems) > 20:
                    break
        return problems


def _types(schema: dict[str, Any]) -> list[str]:
    value = schema.get("type")
    if isinstance(value, str):
        return [value]
    return [t for t in value if isinstance(t, str)] if isinstance(value, list) else []


def _is_type(value: Any, name: str) -> bool:
    if name == "null":
        return value is None
    if name == "integer":
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            or (isinstance(value, float) and value.is_integer())
        )
    if name == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    expected = _JSON_TYPES.get(name)
    return expected is None or isinstance(value, expected)


def _type_name(value: Any) -> str:
    if value is None:
        return "null"
    return {
        bool: "boolean",
        int: "integer",
        float: "number",
        str: "string",
        list: "array",
        dict: "object",
    }.get(type(value), type(value).__name__)


def _response(responses: dict[str, Any], status: str) -> dict[str, Any] | None:
    for key in (status, f"{status[:1]}XX", "DEFAULT"):
        if key in responses:
            return responses[key]
    return None


def verify_samples(normalized: dict[str, Any], samples: list[Sample]) -> SampleReport:
    """Check each sample's status and JSON body against a normalized contract."""
    paths = normalized.get("paths") or {}
    matcher = _Matcher(paths)
    validator = _Validator(normalized.get(RECURSIVE) or {})
    report = SampleReport()
    for sample in samples:
        label = f"{sample.method} {sample.path} -> {sample.status}"
        template = matcher.match(sample.path)
        op = (paths.get(template) or {}).get(sample.method.lower()) if template else None
        if not isinstance(op, dict):
            report.unmatched.append(label)
            continue
        report.checked += 1
        endpoint = f"{sample.method} {paths[template].get('x-api-contract-path', template)}"
        response = _response(op.get("responses") or {}, sample.status)
        if response is None:
            report.problems.append(f"{endpoint}: status {sample.status} is not in the contract")
            continue
        if not sample.has_body:
            continue
        content = response.get("content") or {}
        media = content.get("application/json") or next(
            (m for t, m in content.items() if t.endswith("+json")), None
        )
        if media is None:
            continue
        for problem in validator.errors(media.get("schema") or {}, sample.body, "$"):
            report.problems.append(f"{endpoint} {sample.status}: {problem}")
    return report


def render_report(report: SampleReport) -> str:
    lines = [
        f"Response samples: {report.checked} checked, {len(report.problems)} problem(s), "
        f"{len(report.unmatched)} not in the contract"
    ]
    if report.problems:
        lines += ["", "MISMATCHES"] + [f"  {p}" for p in report.problems]
    if report.unmatched:
        lines += ["", "UNDOCUMENTED ENDPOINTS (no matching operation)"]
        lines += [f"  {u}" for u in sorted(set(report.unmatched))]
    return "\n".join(lines) + "\n"
