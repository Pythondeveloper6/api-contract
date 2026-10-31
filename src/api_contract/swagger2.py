"""Convert a Swagger 2.0 document into an equivalent OpenAPI 3.0.3 document.

The result is meant for contract diffing, not for publishing: it keeps every
detail that affects the wire contract (URLs including ``basePath``, parameters,
request/response bodies and media types, security) and is fed to
:func:`api_contract.normalize.normalize`, which only understands OpenAPI 3.

The main moves:

* ``definitions`` -> ``components/schemas`` and every ``$ref`` is retargeted;
* ``in: body`` / ``in: formData`` parameters become a ``requestBody``;
* other parameters carry their type keywords in a ``schema``, with
  ``collectionFormat`` mapped to ``style``/``explode``;
* response ``schema`` becomes ``content`` per produced media type;
* ``securityDefinitions`` -> ``components/securitySchemes``;
* ``x-nullable``, ``type: file`` and string ``discriminator`` are rewritten.

The input is never mutated.
"""

from __future__ import annotations

import copy
from typing import Any

from .model import ApiContractError

_JSON = "application/json"
_URLENCODED = "application/x-www-form-urlencoded"
_MULTIPART = "multipart/form-data"
_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

_REF_PREFIXES = (
    ("#/definitions/", "#/components/schemas/"),
    ("#/parameters/", "#/components/parameters/"),
    ("#/responses/", "#/components/responses/"),
)
# Type/validation keywords a non-body parameter or header carries; they move into `schema`.
_SCHEMA_KEYWORDS = (
    "type",
    "format",
    "enum",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "uniqueItems",
    "x-nullable",
)
_PARAM_KEYS = ("name", "in", "description", "required", "deprecated", "allowEmptyValue")
_SCHEMA_MAPS = ("properties", "patternProperties")
_FLOWS = {
    "implicit": "implicit",
    "password": "password",
    "application": "clientCredentials",
    "accessCode": "authorizationCode",
}


def convert_swagger2(doc: dict[str, Any]) -> dict[str, Any]:
    """Return an OpenAPI 3.0.3 document equivalent to the Swagger 2.0 ``doc``."""
    if not isinstance(doc, dict):
        raise ApiContractError("a Swagger document must be a mapping")
    version = str(doc.get("swagger", ""))
    if version != "2.0":
        raise ApiContractError(f"expected a Swagger 2.0 document, got swagger={version!r}")
    return _Converter(_rewrite_refs(doc)).convert()


def _rewrite_refs(node: Any) -> Any:
    """Deep copy of ``node`` with 2.0 local ``$ref`` targets moved under ``components``."""
    if isinstance(node, dict):
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                for old, new in _REF_PREFIXES:
                    if value.startswith(old):
                        value = new + value[len(old) :]
                        break
                out[key] = value
            else:
                out[key] = _rewrite_refs(value)
        return out
    if isinstance(node, list):
        return [_rewrite_refs(v) for v in node]
    return node


def _is_body_like(param: Any) -> bool:
    return isinstance(param, dict) and param.get("in") in ("body", "formData")


class _Converter:
    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.consumes: list[str] = list(doc.get("consumes") or [])
        self.produces: list[str] = list(doc.get("produces") or [])
        self.global_params: dict[str, Any] = doc.get("parameters") or {}

    # -- document ----------------------------------------------------------

    def convert(self) -> dict[str, Any]:
        doc = self.doc
        out: dict[str, Any] = {"openapi": "3.0.3", "info": doc.get("info", {})}
        servers = self._servers()
        if servers:
            out["servers"] = servers
        for key in ("tags", "externalDocs", "security"):
            if key in doc:
                out[key] = doc[key]
        out["paths"] = self._paths()
        components = self._components()
        if components:
            out["components"] = components
        for key, value in doc.items():
            if key.startswith("x-"):
                out[key] = value
        return out

    def _servers(self) -> list[dict[str, str]]:
        # basePath is already folded into the path keys, so the URL stops at the host.
        host = self.doc.get("host")
        if not host:
            return []
        return [{"url": f"{s}://{host}"} for s in self.doc.get("schemes") or ["https"]]

    def _components(self) -> dict[str, Any]:
        doc = self.doc
        components: dict[str, Any] = {}
        if doc.get("definitions"):
            components["schemas"] = {n: self.schema(s) for n, s in doc["definitions"].items()}
        # Body/formData parameters can't be component parameters; uses are inlined instead.
        params = {
            n: self.parameter(p) for n, p in self.global_params.items() if not _is_body_like(p)
        }
        if params:
            components["parameters"] = params
        if doc.get("responses"):
            components["responses"] = {
                n: self.response(r, self.produces) for n, r in doc["responses"].items()
            }
        if doc.get("securityDefinitions"):
            components["securitySchemes"] = {
                n: self.security_scheme(s) for n, s in doc["securityDefinitions"].items()
            }
        return components

    # -- paths -------------------------------------------------------------

    def _paths(self) -> dict[str, Any]:
        base = str(self.doc.get("basePath") or "").rstrip("/")
        if base and not base.startswith("/"):
            base = "/" + base
        out: dict[str, Any] = {}
        for path, item in (self.doc.get("paths") or {}).items():
            if str(path).startswith("x-") or not isinstance(item, dict):
                out[path] = item
                continue
            out[base + str(path)] = self.path_item(item)
        return out

    def path_item(self, item: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        shared = item.get("parameters") or []
        for key, value in item.items():
            if key == "parameters":
                plain = self.plain_parameters(value)
                if plain:
                    out[key] = plain
            elif key in _METHODS and isinstance(value, dict):
                out[key] = self.operation(value, shared)
            else:
                out[key] = value
        return out

    def resolve(self, param: Any) -> Any:
        """Inline a ``$ref`` to a global body/formData parameter; leave other refs alone."""
        prefix = "#/components/parameters/"
        if isinstance(param, dict) and str(param.get("$ref", "")).startswith(prefix):
            target = self.global_params.get(param["$ref"][len(prefix) :])
            if _is_body_like(target):
                return target
        return param

    def plain_parameters(self, params: list[Any]) -> list[Any]:
        resolved = [self.resolve(p) for p in params]
        return [self.parameter(p) for p in resolved if not _is_body_like(p)]

    def operation(self, op: dict[str, Any], shared: list[Any]) -> dict[str, Any]:
        consumes = op.get("consumes") or self.consumes or [_JSON]
        produces = op.get("produces") or self.produces or [_JSON]
        own = [self.resolve(p) for p in op.get("parameters") or []]
        own_keys = {(p.get("in"), p.get("name")) for p in own if isinstance(p, dict)}
        # Path-level body/formData parameters apply unless the operation redefines them.
        inherited = [
            p
            for p in (self.resolve(q) for q in shared)
            if _is_body_like(p) and (p.get("in"), p.get("name")) not in own_keys
        ]
        body_like = [p for p in [*own, *inherited] if _is_body_like(p)]

        out: dict[str, Any] = {}
        for key, value in op.items():
            if key in ("consumes", "produces", "schemes"):
                continue
            if key == "parameters":
                plain = self.plain_parameters(value)
                if plain:
                    out[key] = plain
            elif key == "responses":
                out[key] = {
                    str(code): self.response(r, produces) for code, r in (value or {}).items()
                }
            else:
                out[key] = value
        body = self.request_body(body_like, consumes)
        if body:
            out["requestBody"] = body
        return out

    # -- parameters --------------------------------------------------------

    def request_body(self, params: list[dict[str, Any]], consumes: list[str]) -> dict[str, Any]:
        body = next((p for p in params if p["in"] == "body"), None)
        if body is not None:
            schema = self.schema(body.get("schema", {}))
            out: dict[str, Any] = {
                "required": body.get("required") is True,
                "content": {mt: {"schema": copy.deepcopy(schema)} for mt in consumes},
            }
            if "description" in body:
                out["description"] = body["description"]
            return out
        form = [p for p in params if p["in"] == "formData"]
        if not form:
            return {}
        has_file = any(p.get("type") == "file" for p in form)
        media = [m for m in consumes if m in (_URLENCODED, _MULTIPART)]
        if has_file:
            media = [_MULTIPART]
        elif not media:
            media = [_URLENCODED]
        properties: dict[str, Any] = {}
        for p in form:
            prop = self.param_schema(p)
            if "description" in p:
                prop["description"] = p["description"]
            properties[p["name"]] = prop
        schema = {"type": "object", "properties": properties}
        required = [p["name"] for p in form if p.get("required") is True]
        if required:
            schema["required"] = required
        return {
            "required": bool(required),
            "content": {mt: {"schema": copy.deepcopy(schema)} for mt in media},
        }

    def parameter(self, param: dict[str, Any]) -> dict[str, Any]:
        if "$ref" in param:
            return param
        out = {k: param[k] for k in _PARAM_KEYS if k in param}
        out.update({k: v for k, v in param.items() if k.startswith("x-") and k != "x-nullable"})
        location = param.get("in")
        if location == "path":
            out["required"] = True
        out["schema"] = self.param_schema(param)
        if param.get("type") == "array":
            out.update(_serialization(location, param.get("collectionFormat", "csv")))
        return out

    def param_schema(self, obj: dict[str, Any]) -> dict[str, Any]:
        """Schema for a 2.0 parameter/header/items object (type keywords live inline)."""
        schema = {k: copy.deepcopy(obj[k]) for k in _SCHEMA_KEYWORDS if k in obj}
        if isinstance(obj.get("items"), dict):
            schema["items"] = self.param_schema(obj["items"])
        return self.schema(schema)

    # -- responses ---------------------------------------------------------

    def response(self, resp: Any, produces: list[str]) -> Any:
        if not isinstance(resp, dict) or "$ref" in resp:
            return resp
        out: dict[str, Any] = {"description": resp.get("description", "")}
        content: dict[str, Any] = {}
        if "schema" in resp:
            schema = self.schema(resp["schema"])
            content = {mt: {"schema": copy.deepcopy(schema)} for mt in produces or [_JSON]}
        for mt, example in (resp.get("examples") or {}).items():
            content.setdefault(mt, {})["example"] = example
        if content:
            out["content"] = content
        if resp.get("headers"):
            out["headers"] = {n: self.header(h) for n, h in resp["headers"].items()}
        out.update({k: v for k, v in resp.items() if k.startswith("x-")})
        return out

    def header(self, header: dict[str, Any]) -> dict[str, Any]:
        out = {"schema": self.param_schema(header)}
        if "description" in header:
            out["description"] = header["description"]
        return out

    # -- security ----------------------------------------------------------

    @staticmethod
    def security_scheme(scheme: dict[str, Any]) -> dict[str, Any]:
        kind = scheme.get("type")
        extras = {k: v for k, v in scheme.items() if k == "description" or k.startswith("x-")}
        if kind == "basic":
            return {"type": "http", "scheme": "basic", **extras}
        if kind == "oauth2":
            flow = _FLOWS.get(str(scheme.get("flow")), str(scheme.get("flow")))
            urls = {k: scheme[k] for k in ("authorizationUrl", "tokenUrl") if k in scheme}
            return {
                "type": "oauth2",
                "flows": {flow: {**urls, "scopes": scheme.get("scopes") or {}}},
                **extras,
            }
        return dict(scheme)

    # -- schemas -----------------------------------------------------------

    def schema(self, node: Any) -> Any:
        """Rewrite 2.0-only schema keywords, recursively; everything else is kept."""
        if isinstance(node, list):
            return [self.schema(n) for n in node]
        if not isinstance(node, dict):
            return node
        out: dict[str, Any] = {}
        for key, value in node.items():
            if key == "x-nullable":
                if value is True:
                    out["nullable"] = True
            elif key in _SCHEMA_MAPS and isinstance(value, dict):
                out[key] = {n: self.schema(s) for n, s in value.items()}
            elif key in ("items", "allOf", "anyOf", "oneOf", "not", "additionalProperties"):
                out[key] = self.schema(value)
            elif key == "discriminator" and isinstance(value, str):
                out[key] = {"propertyName": value}
            else:
                out[key] = copy.deepcopy(value)
        if out.get("type") == "file":
            out["type"] = "string"
            out["format"] = "binary"
        return out


def _serialization(location: Any, collection_format: str) -> dict[str, Any]:
    """Map 2.0 ``collectionFormat`` onto 3.0 ``style``/``explode`` for an array parameter."""
    if location in ("path", "header"):
        return {"style": "simple", "explode": False}
    if collection_format == "multi":
        return {"style": "form", "explode": True}
    if collection_format == "ssv":
        return {"style": "spaceDelimited", "explode": False}
    if collection_format == "pipes":
        return {"style": "pipeDelimited", "explode": False}
    # csv (the 2.0 default); tsv has no 3.0 equivalent and is treated alike.
    return {"style": "form", "explode": False}
