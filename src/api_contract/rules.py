"""Change kinds and their default severities.

Direction decides severity: a *request* change breaks clients when it adds a
requirement, a *response* change breaks them when it removes a guarantee. That
is why most schema kinds come in ``request-`` / ``response-`` pairs.

Projects override severities in ``[tool.api-contract.rules]``. A key may be a
full kind (``response-enum-value-added``) or the kind with its ``request-`` /
``response-`` part removed (``enum-value-added``), which then applies to both
directions. An exact kind beats the direction-less alias.
"""

from __future__ import annotations

from collections.abc import Mapping

from .model import ApiContractError, Severity

B = Severity.BREAKING
P = Severity.POTENTIALLY_BREAKING
S = Severity.SAFE

DEFAULT_RULES: dict[str, Severity] = {
    # Endpoints
    "endpoint-added": S,
    "endpoint-removed": B,
    "method-added": S,
    "method-removed": B,
    "endpoint-deprecated": S,
    # Parameters
    "required-param-added": B,
    "optional-param-added": S,
    "param-removed": P,
    "param-became-required": B,
    "param-became-optional": S,
    "param-serialization-changed": P,
    "param-deprecated": S,
    # Request body
    "required-request-body-added": B,
    "optional-request-body-added": S,
    "request-body-removed": P,
    "request-body-became-required": B,
    "request-body-became-optional": S,
    "request-content-type-added": S,
    "request-content-type-removed": B,
    # Responses
    "response-success-added": P,
    "response-success-removed": B,
    "response-status-added": S,
    "response-status-removed": P,
    "response-content-type-added": S,
    "response-content-type-removed": B,
    "response-header-added": S,
    "response-header-removed": B,
    "response-header-became-optional": B,
    "response-header-became-required": S,
    # Security
    "auth-added": B,
    "auth-removed": S,
    "auth-alternative-added": S,
    "auth-alternative-removed": B,
    "auth-scopes-added": B,
    "auth-scopes-removed": S,
    # Schema: fields
    "required-request-field-added": B,
    "optional-request-field-added": S,
    "request-field-removed": P,
    "request-field-became-required": B,
    "request-field-became-optional": S,
    "response-field-added": S,
    "response-field-removed": B,
    "response-field-became-optional": B,
    "response-field-became-required": S,
    "field-deprecated": S,
    # Schema: types and formats
    "type-changed": B,
    "request-type-widened": S,
    "response-type-narrowed": S,
    "format-changed": B,
    "format-added": P,
    "format-removed": P,
    # Schema: enums
    "request-enum-value-added": S,
    "request-enum-value-removed": B,
    "response-enum-value-added": P,
    "response-enum-value-removed": S,
    "request-enum-added": B,
    "request-enum-removed": S,
    "response-enum-added": S,
    "response-enum-removed": P,
    # Schema: nullability
    "request-became-nullable": S,
    "request-became-non-nullable": B,
    "response-became-nullable": B,
    "response-became-non-nullable": S,
    # Schema: constraints (maxLength, minimum, pattern, additionalProperties, ...)
    "request-constraint-tightened": P,
    "request-constraint-loosened": S,
    "response-constraint-tightened": S,
    "response-constraint-loosened": P,
    "default-changed": P,
    # Schema: composition (oneOf / anyOf / allOf / not) and anything unrecognized
    "request-variant-added": S,
    "request-variant-removed": B,
    "response-variant-added": P,
    "response-variant-removed": S,
    "composition-changed": P,
    "schema-changed": P,
}


def alias(kind: str) -> str:
    """``response-enum-value-added`` -> ``enum-value-added``."""
    for word in ("request-", "response-"):
        if word in kind:
            return kind.replace(word, "", 1)
    return kind


class Rules:
    """Kind -> severity lookup with per-project overrides."""

    def __init__(self, overrides: Mapping[str, str | Severity] | None = None) -> None:
        aliases = {alias(k) for k in DEFAULT_RULES}
        self.overrides: dict[str, Severity] = {}
        for key, value in (overrides or {}).items():
            if key not in DEFAULT_RULES and key not in aliases:
                raise ApiContractError(f"unknown change kind in rules: {key!r}")
            try:
                self.overrides[key] = Severity(value)
            except ValueError:
                choices = ", ".join(s.value for s in Severity)
                raise ApiContractError(
                    f"invalid severity {value!r} for rule {key!r} (choose from: {choices})"
                ) from None

    def severity(self, kind: str) -> Severity:
        if kind in self.overrides:
            return self.overrides[kind]
        if alias(kind) in self.overrides:
            return self.overrides[alias(kind)]
        return DEFAULT_RULES[kind]
