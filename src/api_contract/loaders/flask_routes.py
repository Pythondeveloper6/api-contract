"""``flask-routes:`` sources: an endpoint inventory from a Flask URL map.

For Flask apps with no OpenAPI library. The document lists every rule and
method with its path parameters (typed from the URL converter) and nothing
else: no request or response schemas, a single undocumented ``default``
response. Removed or renamed endpoints and methods, and changed path
parameter types, are still caught; body and field changes are not.
"""

from __future__ import annotations

import re
from typing import Any

from .flask import FlaskLoader

_RULE_PART = re.compile(r"<(?:([^:<>()]+)(?:\([^<>]*\))?:)?([^<>]+)>")
_CONVERTERS: dict[str, dict[str, Any]] = {
    "int": {"type": "integer"},
    "float": {"type": "number"},
    "uuid": {"type": "string", "format": "uuid"},
    "path": {"type": "string"},
    "string": {"type": "string"},
    "default": {"type": "string"},
    "any": {"type": "string"},
}
_SKIPPED_METHODS = {"HEAD", "OPTIONS"}
INVENTORY = "x-api-contract-inventory"


def inventory(app: Any) -> dict[str, Any]:
    """The minimal OpenAPI 3.0 document for ``app.url_map``."""
    paths: dict[str, Any] = {}
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: r.rule):
        if rule.endpoint == "static" or rule.endpoint.endswith(".static"):
            continue
        params = []
        for converter, name in _RULE_PART.findall(rule.rule):
            schema = dict(_CONVERTERS.get(converter or "default", {"type": "string"}))
            params.append({"name": name, "in": "path", "required": True, "schema": schema})
        path = _RULE_PART.sub(lambda m: "{" + m.group(2) + "}", rule.rule)
        item = paths.setdefault(path, {})
        for method in sorted((rule.methods or set()) - _SKIPPED_METHODS):
            operation: dict[str, Any] = {
                "operationId": rule.endpoint,
                "responses": {"default": {"description": "undocumented"}},
            }
            if params:
                operation["parameters"] = params
            item[method.lower()] = operation
    return {
        "openapi": "3.0.3",
        "info": {"title": f"{app.name} routes", "version": "inventory"},
        INVENTORY: True,
        "paths": paths,
    }


class FlaskRoutesLoader(FlaskLoader):
    """Like ``flask:``, but builds the document from the URL map instead of
    an OpenAPI library. Attribution works the same way."""

    def load(self) -> dict:
        return inventory(self.app)
