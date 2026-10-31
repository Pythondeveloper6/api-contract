"""Migration helpers for teams moving from oasdiff.

* ``import_err_ignore``: an oasdiff ``--err-ignore`` file (``METHOD /path
  free text`` per line) becomes allowlist entries. oasdiff ignores one
  message; api-contract ids are structured differently, so each line becomes
  an endpoint wildcard (``METHOD /path:*``). That is broader than the original
  ignore, which is why every imported entry still needs a reason and an
  expiry: review them before they expire.
* ``import_severity_levels``: an oasdiff ``--severity-levels`` file
  (``check-id LEVEL`` per line) becomes ``[tool.api-contract.rules]``
  overrides, for the oasdiff checks that have an api-contract equivalent.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import yaml

from .allowlist import AllowEntry
from .model import ApiContractError, Severity, canonical_id

# oasdiff check id -> api-contract kinds it corresponds to.
OASDIFF_CHECKS: dict[str, tuple[str, ...]] = {
    "api-path-removed-without-deprecation": ("endpoint-removed",),
    "api-path-removed-before-sunset": ("endpoint-removed",),
    "api-removed-without-deprecation": ("method-removed",),
    "api-removed-before-sunset": ("method-removed",),
    "endpoint-added": ("endpoint-added",),
    "api-deprecated": ("endpoint-deprecated",),
    "new-required-request-parameter": ("required-param-added",),
    "new-optional-request-parameter": ("optional-param-added",),
    "request-parameter-removed": ("param-removed",),
    "request-parameter-became-required": ("param-became-required",),
    "request-parameter-became-optional": ("param-became-optional",),
    "request-parameter-type-changed": ("type-changed",),
    "request-parameter-enum-value-removed": ("request-enum-value-removed",),
    "request-parameter-enum-value-added": ("request-enum-value-added",),
    "added-required-request-body": ("required-request-body-added",),
    "request-body-became-required": ("request-body-became-required",),
    "request-body-became-optional": ("request-body-became-optional",),
    "request-body-media-type-removed": ("request-content-type-removed",),
    "request-body-media-type-added": ("request-content-type-added",),
    "request-body-type-changed": ("type-changed",),
    "new-required-request-property": ("required-request-field-added",),
    "new-optional-request-property": ("optional-request-field-added",),
    "request-property-removed": ("request-field-removed",),
    "request-property-became-required": ("request-field-became-required",),
    "request-property-became-optional": ("request-field-became-optional",),
    "request-property-became-not-nullable": ("request-became-non-nullable",),
    "request-property-became-nullable": ("request-became-nullable",),
    "request-property-type-changed": ("type-changed",),
    "request-property-enum-value-removed": ("request-enum-value-removed",),
    "request-property-enum-value-added": ("request-enum-value-added",),
    "request-property-max-length-decreased": ("request-constraint-tightened",),
    "request-property-max-length-increased": ("request-constraint-loosened",),
    "response-property-removed": ("response-field-removed",),
    "response-required-property-removed": ("response-field-removed",),
    "response-optional-property-removed": ("response-field-removed",),
    "response-property-became-optional": ("response-field-became-optional",),
    "response-property-became-required": ("response-field-became-required",),
    "response-property-became-nullable": ("response-became-nullable",),
    "response-property-type-changed": ("type-changed",),
    "response-body-type-changed": ("type-changed",),
    "response-property-enum-value-added": ("response-enum-value-added",),
    "response-property-enum-value-removed": ("response-enum-value-removed",),
    "response-success-status-removed": ("response-success-removed",),
    "response-non-success-status-removed": ("response-status-removed",),
    "response-media-type-removed": ("response-content-type-removed",),
    "response-required-header-removed": ("response-header-removed",),
    "api-security-added": ("auth-added",),
    "api-security-removed": ("auth-removed",),
    "api-security-scope-added": ("auth-scopes-added",),
    "api-security-scope-removed": ("auth-scopes-removed",),
}

_LEVELS = {
    "ERR": Severity.BREAKING,
    "WARN": Severity.POTENTIALLY_BREAKING,
    "INFO": Severity.SAFE,
    "NONE": Severity.SAFE,
}
_METHODS = {"GET", "PUT", "POST", "DELETE", "OPTIONS", "HEAD", "PATCH", "TRACE"}
_IGNORE_LINE = re.compile(r"^\s*([A-Za-z]+)\s+(/\S*)\s*(.*?)\s*$")


def _lines(text: str):
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            yield number, stripped


def import_err_ignore(
    text: str, *, reason: str, expires: dt.date
) -> tuple[list[AllowEntry], list[int]]:
    """Allowlist entries for an oasdiff err-ignore file, and the line numbers
    that could not be read."""
    if not reason.strip():
        raise ApiContractError("a reason is required for imported allowlist entries")
    entries: dict[str, AllowEntry] = {}
    skipped = []
    for number, line in _lines(text):
        match = _IGNORE_LINE.match(line)
        if not match or match.group(1).upper() not in _METHODS:
            skipped.append(number)
            continue
        method, path, note = match.group(1).upper(), match.group(2), match.group(3)
        change_id = canonical_id(f"{method} {path}:*")
        if change_id in entries:
            continue
        text_reason = f"{reason.strip()} (oasdiff: {note})" if note else reason.strip()
        entries[change_id] = AllowEntry(id=change_id, reason=text_reason, expires=expires)
    return list(entries.values()), skipped


def import_severity_levels(text: str) -> tuple[dict[str, str], list[str]]:
    """``[tool.api-contract.rules]`` overrides for an oasdiff severity-levels
    file, and the oasdiff check ids with no equivalent. When several checks map
    to one kind with different levels, the strictest wins."""
    rules: dict[str, Severity] = {}
    unmapped: list[str] = []
    for number, line in _lines(text):
        parts = line.split()
        if len(parts) != 2 or parts[1].upper() not in _LEVELS:
            raise ApiContractError(
                f"severity-levels line {number}: expected '<check-id> <ERR|WARN|INFO|NONE>', "
                f"got {line!r}"
            )
        check, level = parts[0], _LEVELS[parts[1].upper()]
        kinds = OASDIFF_CHECKS.get(check)
        if not kinds:
            unmapped.append(check)
            continue
        for kind in kinds:
            if kind not in rules or level.rank > rules[kind].rank:
                rules[kind] = level
    return {k: v.value for k, v in sorted(rules.items())}, unmapped


def render_rules_toml(rules: dict[str, str]) -> str:
    lines = ["[tool.api-contract.rules]"]
    lines += [f'{kind} = "{severity}"' for kind, severity in sorted(rules.items())]
    return "\n".join(lines) + "\n"


def render_allowlist_yaml(entries: list[AllowEntry]) -> str:
    data: dict[str, Any] = {
        "allow": [{"id": e.id, "reason": e.reason, "expires": e.expires} for e in entries]
    }
    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000, indent=2)
