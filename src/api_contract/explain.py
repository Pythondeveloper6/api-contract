"""``api-contract explain <kind-or-id>``: what a change means and how to ship it safely.

A report line like ``response-field-removed`` says *what* changed. This module
says what it does to clients, why it has its severity, and the
expand/contract steps that make the same change without breaking anyone, so
the allowlist is the last step of a migration rather than the first.
"""

from __future__ import annotations

import difflib

from .model import ApiContractError, Severity
from .rules import DEFAULT_RULES, Rules, alias

# One line per kind: the same text as the tables in docs/rules.md.
_MEANING: dict[str, str] = {
    "endpoint-added": "A new path appears.",
    "endpoint-removed": "A path disappears.",
    "method-added": "A new HTTP method on an existing path.",
    "method-removed": "An HTTP method disappears from a path.",
    "endpoint-deprecated": "An operation is marked `deprecated`.",
    "required-param-added": "A new required parameter.",
    "optional-param-added": "A new optional parameter.",
    "param-removed": (
        "A parameter is removed. Clients that still send it may be ignored or "
        "rejected, depending on the server."
    ),
    "param-became-required": "An optional parameter becomes required.",
    "param-became-optional": "A required parameter becomes optional.",
    "param-serialization-changed": (
        "`style`, `explode`, `allowReserved` or `allowEmptyValue` changed."
    ),
    "param-deprecated": "A parameter is marked `deprecated`.",
    "required-request-body-added": "An operation that took no body now requires one.",
    "optional-request-body-added": "An operation gains an optional body.",
    "request-body-removed": "The body is removed.",
    "request-body-became-required": "An optional body becomes required.",
    "request-body-became-optional": "A required body becomes optional.",
    "request-content-type-added": "A new accepted media type.",
    "request-content-type-removed": "An accepted media type is removed.",
    "response-success-added": (
        "A new 2xx status code. Clients that switch on the status may not expect it."
    ),
    "response-success-removed": "A 2xx status code disappears.",
    "response-status-added": "A new non-2xx status code.",
    "response-status-removed": "A non-2xx status code disappears.",
    "response-content-type-added": "A new media type is returned.",
    "response-content-type-removed": "A returned media type disappears.",
    "response-header-added": "A new response header.",
    "response-header-removed": "A response header disappears.",
    "response-header-became-optional": "A response header that was required may now be missing.",
    "response-header-became-required": "A response header that was optional is now always present.",
    "auth-added": "An operation that was public now requires authentication.",
    "auth-removed": "An operation no longer requires authentication.",
    "auth-alternative-added": "A new way to authenticate is accepted.",
    "auth-alternative-removed": "An accepted way to authenticate is removed.",
    "auth-scopes-added": "An operation now requires more OAuth scopes.",
    "auth-scopes-removed": "An operation requires fewer OAuth scopes.",
    "required-request-field-added": "A new required field in a request body.",
    "optional-request-field-added": "A new optional field in a request body.",
    "request-field-removed": "A request field is removed.",
    "request-field-became-required": "An optional request field becomes required.",
    "request-field-became-optional": "A required request field becomes optional.",
    "response-field-added": "A new field in a response.",
    "response-field-removed": "A response field is removed.",
    "response-field-became-optional": "A response field that was always present may now be absent.",
    "response-field-became-required": (
        "A response field that might be absent is now always present."
    ),
    "field-deprecated": "A field is marked `deprecated`.",
    "type-changed": (
        "The type changed (for example number to string), or a request type was"
        " narrowed, or a response type was widened."
    ),
    "request-type-widened": "A request type now accepts more types.",
    "response-type-narrowed": "A response type now returns fewer types.",
    "format-changed": "`format` changed (for example int32 to int64).",
    "format-added": "A `format` was added to a schema that had none.",
    "format-removed": "The `format` was removed.",
    "request-enum-value-added": "A request enum accepts a new value.",
    "request-enum-value-removed": "A request enum no longer accepts a value.",
    "response-enum-value-added": (
        "A response enum may return a new value. Strict clients can fail on "
        "values they do not know."
    ),
    "response-enum-value-removed": "A response enum can no longer return a value.",
    "request-enum-added": "A free-form request value is now restricted to an enum.",
    "request-enum-removed": "A request enum restriction is lifted.",
    "response-enum-added": "A response value is now documented as an enum.",
    "response-enum-removed": "A response enum restriction is lifted, so any value may come back.",
    "request-became-nullable": "A request value may now be null.",
    "request-became-non-nullable": "A request value may no longer be null.",
    "response-became-nullable": "A response value may now be null.",
    "response-became-non-nullable": "A response value is never null any more.",
    "request-constraint-tightened": "A request constraint is stricter.",
    "request-constraint-loosened": "A request constraint is looser.",
    "response-constraint-tightened": "A response constraint is stricter (a stronger guarantee).",
    "response-constraint-loosened": "A response constraint is looser (a weaker guarantee).",
    "default-changed": "A `default` value changed.",
    "request-variant-added": "A request accepts one more variant.",
    "request-variant-removed": "A request no longer accepts a variant.",
    "response-variant-added": "A response may return one more variant.",
    "response-variant-removed": "A response can no longer return a variant.",
    "composition-changed": (
        "A composition keyword changed in a way that cannot be matched variant by variant."
    ),
    "schema-changed": (
        "Fallback for any schema difference with no more specific kind. It is "
        "never dropped silently."
    ),
}

_SEVERITY_WHY = {
    Severity.BREAKING: "Clients that worked before this change can fail after it.",
    Severity.POTENTIALLY_BREAKING: (
        "Some clients may fail, depending on how strictly they parse or what they send."
    ),
    Severity.SAFE: "Existing clients keep working.",
}

_ADDITIVE = ["No migration needed: existing clients keep working."]
_REMOVE = [
    "Mark it deprecated in the schema (`deprecated: true`, and for endpoints an "
    "`x-sunset: YYYY-MM-DD` date) and tell clients what replaces it.",
    "Ship the replacement next to it and wait until clients have moved (check your "
    "traffic: `api-contract check --usage access.log`).",
    "Remove it after the sunset date; api-contract treats removing a deprecated "
    "endpoint after its `x-sunset` date as safe.",
    "For anything else, acknowledge the final removal with `api-contract allow <id> "
    "--reason ... --expires ...`.",
]
_REQUIRE = [
    "Add it as optional first, with a server-side default for clients that omit it.",
    "Update clients to send it, and wait until old clients are gone.",
    "Only then make it required, acknowledging that last step with "
    "`api-contract allow <id> --reason ... --expires ...`.",
]
_RETYPE = [
    "Expand: add a new field (or parameter) with the new type next to the old one, "
    "and return/accept both.",
    "Migrate clients to the new field; mark the old one deprecated.",
    "Contract: remove the old field once nobody reads or sends it (see the "
    "removal steps: `api-contract explain response-field-removed`).",
]
_RESPONSE_WIDER = [
    "Prefer a new field or a new endpoint version for the wider value, so existing "
    "clients keep getting what they expect.",
    "If the new value must appear in place, confirm that all clients tolerate it "
    "(e.g. unknown enum values fall back to a default), then acknowledge the change "
    "with `api-contract allow <id> --reason ... --expires ...`.",
]
_REQUEST_STRICTER = [
    "Keep accepting what was accepted before; validate the stricter rule only for "
    "a new field, parameter or endpoint version.",
    "If the old input must be rejected, announce it, measure how many requests "
    "would fail, and acknowledge the change with `api-contract allow`.",
]
_AUTH = [
    "Announce the new requirement and give clients credentials in advance.",
    "Accept both the old and the new way during a transition (security "
    "alternatives), then remove the old one.",
    "Acknowledge the final step with `api-contract allow <id> --reason ... --expires ...`.",
]
_REVIEW = [
    "Read the reported old and new values, decide whether any client depends on the "
    "difference, and either revert or acknowledge it with `api-contract allow`.",
    "If this kind is never relevant to your clients, change its severity in "
    "`[tool.api-contract.rules]`.",
]


def _steps(kind: str) -> list[str]:
    severity = DEFAULT_RULES[kind]
    if severity is Severity.SAFE:
        return _ADDITIVE
    if kind.startswith("auth-"):
        return _AUTH
    if "removed" in kind and kind not in {"request-enum-removed", "response-enum-removed"}:
        if kind.startswith("request-") or kind == "param-removed":
            return [
                "Keep accepting it (ignore it server-side) for a deprecation period.",
                *_REMOVE[1:],
            ]
        return _REMOVE
    if "required" in kind and kind != "response-field-became-optional":
        return _REQUIRE
    if kind in {"type-changed", "format-changed", "format-added", "format-removed"}:
        return _RETYPE
    if kind.startswith("request-") or kind == "param-serialization-changed":
        return _REQUEST_STRICTER
    if kind.startswith("response-"):
        return _RESPONSE_WIDER
    return _REVIEW


def _direction(kind: str) -> str:
    if kind.startswith("request-") or "-request-" in kind or "param" in kind:
        return "request"
    if kind.startswith("response-") or "-response-" in kind:
        return "response"
    if kind.startswith(("endpoint-", "method-", "auth-")):
        return "endpoint"
    return "request or response (decided by where the schema is used)"


def explain_kinds() -> dict[str, str]:
    """One-line meaning of every kind."""
    return dict(_MEANING)


def _kind_from_id(change_id: str) -> tuple[str, str] | None:
    """``("GET /x:response:200:total", "type-changed")`` for a full change id."""
    parts = change_id.split(":")
    # The kind is the last part that is a known kind; a detail (enum value...) may follow.
    for index in range(len(parts) - 1, -1, -1):
        if parts[index] in DEFAULT_RULES:
            return ":".join(parts[:index]), parts[index]
    return None


def resolve(target: str) -> tuple[list[str], str | None]:
    """The kinds ``target`` names, and the location part when it is a change id."""
    target = target.strip()
    if target in DEFAULT_RULES:
        return [target], None
    by_alias = [k for k in DEFAULT_RULES if alias(k) == target]
    if by_alias:
        return by_alias, None
    found = _kind_from_id(target)
    if found:
        return [found[1]], found[0] or None
    choices = sorted(set(DEFAULT_RULES) | {alias(k) for k in DEFAULT_RULES})
    close = difflib.get_close_matches(target, choices, n=3, cutoff=0.5)
    hint = f"; did you mean {', '.join(close)}?" if close else "; see docs/rules.md"
    raise ApiContractError(f"unknown change kind or id {target!r}{hint}")


def explain(target: str, *, rules: Rules | None = None) -> str:
    """Plain-text explanation of a kind, a direction-less alias, or a change id."""
    kinds, where = resolve(target)
    blocks = []
    for kind in kinds:
        default = DEFAULT_RULES[kind]
        lines = [kind, "=" * len(kind)]
        if where:
            lines.append(f"Where:      {where}")
        lines.append(f"Severity:   {default.value} (default)")
        if rules is not None and rules.severity(kind) is not default:
            lines[-1] = (
                f"Severity:   {rules.severity(kind).value} "
                f"(this project; the default is {default.value})"
            )
        lines += [
            f"Direction:  {_direction(kind)}",
            "",
            f"What it means: {_MEANING[kind]}",
            f"Why this severity: {_SEVERITY_WHY[default]}",
            "",
            "How to ship it compatibly:",
        ]
        lines += [f"  {n}. {step}" for n, step in enumerate(_steps(kind), 1)]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks) + "\n"
