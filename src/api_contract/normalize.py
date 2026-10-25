"""Turn an OpenAPI 3.0/3.1 document into a canonical form that is cheap to diff.

The normalized document is what the snapshot file stores. It keeps only what
affects the wire contract, in a shape where equal contracts compare equal:

* every ``$ref`` is resolved inline, except references to *recursive*
  components (those on a reference cycle). Inlining those would never end, and
  mutually recursive clusters grow factorially even with cycle detection, so
  each is normalized once into ``recursive_schemas`` and every use becomes a
  marker, ``{"x-api-contract-ref": "Node"}`` — the cycle point. The differ
  follows these markers itself;
* docs-only keys (``description``, ``example``, ``x-*``, ...) are dropped;
* 3.0 ``nullable: true`` and 3.1 ``type: [..., "null"]`` (or a ``null``
  member of ``anyOf``/``oneOf``) become the same ``nullable: true``;
* path parameters are positional (``/orders/{}``) so renaming one is a no-op;
* parameters become a mapping keyed ``"<in>:<name>"`` (``"path:<index>"``),
  path-level parameters and global security are folded into each operation,
  and serialization defaults are made explicit;
* keys are sorted, and order-insensitive lists (``required``, ``enum``,
  ``oneOf``...) are sorted.

Keys starting with ``x-api-contract`` are bookkeeping written by this module
(raw path templates, component names for attribution); the differ ignores them.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
from collections.abc import Iterable
from fnmatch import fnmatchcase
from typing import Any
from urllib.parse import unquote

from .model import ApiContractError, positional_path

DEFAULT_IGNORE_KEYS: tuple[str, ...] = (
    "description",
    "summary",
    "example",
    "examples",
    "title",
    "externalDocs",
    "x-*",
)

INTERNAL_PREFIX = "x-api-contract"
FORMAT_MARKER = "x-api-contract"
COMPONENT = "x-api-contract-component"
REF = "x-api-contract-ref"
# Keys that may sit next to a recursive-component marker (``{REF: name, **overlay}``):
# they apply to that use of the component, on top of its definition.
OVERLAY_KEYS = frozenset({"nullable", "deprecated", "readOnly", "writeOnly", "default"})
RECURSIVE = "recursive_schemas"
EXTERNAL_REF = "x-api-contract-external-ref"
RAW_PATH = "x-api-contract-path"
PARAM_NAME = "x-api-contract-name"
SNAPSHOT_FORMAT = 1

METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

# Values are mappings of user-chosen names to schemas: the names must never be
# mistaken for docs keys (a property called "description" is real data).
_SCHEMA_MAP_KEYS = {"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"}
_SCHEMA_KEYS = {
    "items",
    "not",
    "contains",
    "propertyNames",
    "if",
    "then",
    "else",
    "unevaluatedItems",
    "additionalItems",
    "contentSchema",
}
# ``true``/``{}`` mean "anything goes", the same as leaving the key out.
_OPEN_SCHEMA_KEYS = {"additionalProperties", "unevaluatedProperties"}
_SCHEMA_LIST_KEYS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_UNORDERED_LIST_KEYS = ("allOf", "anyOf", "oneOf")
_DATA_KEYS = {"default", "enum", "const", "example", "examples"}

# OpenAPI says these header parameters are ignored; they're described elsewhere.
_IGNORED_HEADER_PARAMS = {"accept", "content-type", "authorization"}
_DEFAULT_STYLE = {"query": "form", "cookie": "form", "path": "simple", "header": "simple"}


def canonical_json(value: Any) -> str:
    """Compact, key-sorted JSON used for equality and deterministic sorting."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def dump_snapshot(normalized: dict[str, Any]) -> str:
    """Pretty, sorted JSON: the on-disk snapshot format."""
    return json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def is_normalized(doc: Any) -> bool:
    return isinstance(doc, dict) and FORMAT_MARKER in doc


def normalize(doc: dict[str, Any], *, ignore_keys: Iterable[str] | None = None) -> dict[str, Any]:
    """Return the canonical form of an OpenAPI document (or of a snapshot).

    Normalizing a snapshot again is a no-op apart from applying the current
    ``ignore_keys``, so a snapshot can always be fed back in.
    """
    if not isinstance(doc, dict):
        raise ApiContractError("an OpenAPI document must be a mapping")
    # YAML reads unquoted keys like `200:` as integers; JSON keys are always strings.
    doc = _str_keys(doc)
    ignore = tuple(DEFAULT_IGNORE_KEYS if ignore_keys is None else ignore_keys)
    normalizer = _Normalizer(doc, ignore)
    if is_normalized(doc):
        return _sorted(normalizer.renormalize())
    if "swagger" in doc:
        raise ApiContractError("Swagger 2.0 documents are not supported; convert to OpenAPI 3")
    version = str(doc.get("openapi", ""))
    if version and not version.startswith("3."):
        raise ApiContractError(f"unsupported OpenAPI version {version!r}")
    if not isinstance(doc.get("paths", {}), dict):
        raise ApiContractError("'paths' must be a mapping")
    return _sorted(normalizer.document())


def _str_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _str_keys(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_str_keys(v) for v in value]
    return value


def _sorted(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sorted(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_sorted(v) for v in value]
    return value


def _jsonable(value: Any) -> Any:
    """Deep copy of example/default data, with YAML dates turned into strings."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (_dt.date, _dt.datetime)):
        return value.isoformat()
    return value


def _component_name(ref: str) -> str | None:
    for prefix in ("#/components/schemas/", "#/definitions/"):
        if ref.startswith(prefix):
            return unquote(ref[len(prefix) :]).replace("~1", "/").replace("~0", "~")
    return None


class _Normalizer:
    def __init__(self, doc: dict[str, Any], ignore: tuple[str, ...]) -> None:
        self.doc = doc
        self.ignore = ignore
        self._cache: dict[str, dict[str, Any]] = {}
        # Bumped whenever a cycle marker is emitted. A resolved $ref whose
        # expansion emitted none doesn't depend on the ref stack, so it's cached.
        self._cycles = 0
        self.recursive = _recursive_components(doc) if not is_normalized(doc) else set()
        self.defs: dict[str, dict[str, Any]] = {}

    # -- helpers -----------------------------------------------------------

    def ignored(self, key: str) -> bool:
        if key.startswith(INTERNAL_PREFIX):
            return False
        return any(fnmatchcase(key, pattern) for pattern in self.ignore)

    def lookup(self, ref: str) -> Any:
        if not ref.startswith("#/") or ref == "#/":
            raise ApiContractError(f"unresolvable $ref {ref!r}")
        node: Any = self.doc
        for raw in ref[2:].split("/"):
            part = unquote(raw).replace("~1", "/").replace("~0", "~")
            if isinstance(node, dict) and part in node:
                node = node[part]
            elif isinstance(node, list) and part.isdigit() and int(part) < len(node):
                node = node[int(part)]
            else:
                raise ApiContractError(f"unresolvable $ref {ref!r}")
        return node

    def deref(self, node: Any) -> Any:
        """Resolve a non-schema object (parameter, response, ...) through ``$ref`` chains."""
        seen: set[str] = set()
        while isinstance(node, dict) and isinstance(node.get("$ref"), str):
            ref = node["$ref"]
            if not ref.startswith("#"):
                raise ApiContractError(f"external $ref {ref!r} is not supported outside schemas")
            if ref in seen:
                raise ApiContractError(f"circular $ref {ref!r}")
            seen.add(ref)
            node = self.lookup(ref)
        return node

    # -- document ----------------------------------------------------------

    def document(self) -> dict[str, Any]:
        global_security = self.doc.get("security")
        paths: dict[str, Any] = {}
        for raw_path in sorted(self.doc.get("paths") or {}):
            item = self.deref(self.doc["paths"][raw_path])
            if not isinstance(item, dict):
                continue
            out_item = paths.setdefault(positional_path(raw_path), {RAW_PATH: raw_path})
            common = item.get("parameters") or []
            for method in METHODS:
                op = item.get(method)
                if isinstance(op, dict):
                    out_item[method] = self.operation(op, common, global_security, raw_path)
        return {FORMAT_MARKER: {"format": SNAPSHOT_FORMAT}, "paths": paths, RECURSIVE: self.defs}

    def operation(
        self, op: dict[str, Any], common: list[Any], global_security: Any, raw_path: str
    ) -> dict[str, Any]:
        path_names = re.findall(r"\{([^}/]*)\}", raw_path)
        params: dict[str, Any] = {}
        # Operation-level parameters override path-level ones with the same key.
        for raw in [*common, *(op.get("parameters") or [])]:
            param = self.deref(raw)
            if isinstance(param, dict):
                key_value = self.parameter(param, path_names)
                if key_value:
                    params[key_value[0]] = key_value[1]
        out: dict[str, Any] = {
            "parameters": params,
            "responses": {},
            "security": self.security(op.get("security", global_security)),
        }
        if op.get("deprecated") is True:
            out["deprecated"] = True
        if "requestBody" in op:
            body = self.deref(op["requestBody"])
            if isinstance(body, dict):
                out["requestBody"] = {
                    "required": body.get("required") is True,
                    "content": self.content(body.get("content")),
                }
        for code, response in (op.get("responses") or {}).items():
            response = self.deref(response)
            if not isinstance(response, dict):
                continue
            headers = {}
            for name, header in (response.get("headers") or {}).items():
                if name.lower() == "content-type":
                    continue
                header = self.deref(header)
                if isinstance(header, dict):
                    headers[name.lower()] = {
                        "required": header.get("required") is True,
                        "schema": self.param_schema(header),
                    }
            out["responses"][str(code).upper()] = {
                "content": self.content(response.get("content")),
                "headers": headers,
            }
        return out

    def parameter(self, param: dict[str, Any], path_names: list[str]) -> tuple[str, Any] | None:
        location, name = param.get("in"), param.get("name")
        if not isinstance(location, str) or not isinstance(name, str):
            return None
        out: dict[str, Any] = {}
        if location == "path":
            key = f"path:{path_names.index(name)}" if name in path_names else f"path:{name}"
            out[PARAM_NAME] = name
            # Path parameters are always required, whatever the document says.
            out["required"] = True
        else:
            if location == "header":
                name = name.lower()
                if name in _IGNORED_HEADER_PARAMS:
                    return None
            key = f"{location}:{name}"
            out["required"] = param.get("required") is True
        style = param.get("style", _DEFAULT_STYLE.get(location, "form"))
        out["style"] = style
        out["explode"] = bool(param.get("explode", style == "form"))
        for flag in ("allowReserved", "allowEmptyValue", "deprecated"):
            if param.get(flag) is True:
                out[flag] = True
        out["schema"] = self.param_schema(param)
        return key, out

    def param_schema(self, obj: dict[str, Any]) -> dict[str, Any]:
        if "schema" in obj:
            return self.schema(obj["schema"])
        # A parameter or header may carry its schema under `content` instead.
        for media in (obj.get("content") or {}).values():
            if isinstance(media, dict) and "schema" in media:
                return self.schema(media["schema"])
        return {}

    def content(self, content: Any) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for media_type, media in sorted((content or {}).items()):
            key = str(media_type).split(";")[0].strip().lower()
            if key in out:
                continue
            media = media if isinstance(media, dict) else {}
            out[key] = {"schema": self.schema(media["schema"])} if "schema" in media else {}
        return out

    @staticmethod
    def security(requirements: Any) -> list[dict[str, list[str]]]:
        """A sorted list of alternatives; each maps scheme name -> sorted scopes.

        An empty alternative (``{}``) means "anonymous allowed".
        """
        out = []
        for alt in requirements or []:
            if isinstance(alt, dict):
                out.append({str(k): sorted(set(v or [])) for k, v in alt.items()})
        unique = {canonical_json(alt): alt for alt in out}
        return [unique[k] for k in sorted(unique)]

    def renormalize(self) -> dict[str, Any]:
        """Re-apply schema normalization (and the current ignore list) to a snapshot."""
        paths: dict[str, Any] = {}
        for path, item in (self.doc.get("paths") or {}).items():
            out_item = {}
            for key, op in item.items():
                if key not in METHODS:
                    out_item[key] = op
                    continue
                op = dict(op)
                op["parameters"] = {
                    k: {**p, "schema": self.schema(p.get("schema", {}))}
                    for k, p in (op.get("parameters") or {}).items()
                }
                if "requestBody" in op:
                    body = op["requestBody"]
                    op["requestBody"] = {**body, "content": self.recontent(body.get("content"))}
                op["responses"] = {
                    code: {
                        **resp,
                        "content": self.recontent(resp.get("content")),
                        "headers": {
                            n: {**h, "schema": self.schema(h.get("schema", {}))}
                            for n, h in (resp.get("headers") or {}).items()
                        },
                    }
                    for code, resp in (op.get("responses") or {}).items()
                }
                out_item[key] = op
            paths[path] = out_item
        defs = {name: self.schema(d) for name, d in (self.doc.get(RECURSIVE) or {}).items()}
        return {**self.doc, "paths": paths, RECURSIVE: defs}

    def recontent(self, content: Any) -> dict[str, Any]:
        return {
            mt: ({"schema": self.schema(m["schema"])} if "schema" in m else {})
            for mt, m in (content or {}).items()
        }

    # -- schemas -----------------------------------------------------------

    def schema(self, node: Any, stack: tuple[str, ...] = ()) -> dict[str, Any]:
        if node is True or node is None:
            return {}
        if node is False:
            return {"not": {}}
        if not isinstance(node, dict):
            return {}
        if isinstance(node.get("$ref"), str):
            return self._ref_schema(node, stack)

        out: dict[str, Any] = {}
        for key, value in node.items():
            if self.ignored(key):
                continue
            if key.startswith(INTERNAL_PREFIX):
                out[key] = value
            elif key in _SCHEMA_MAP_KEYS and isinstance(value, dict):
                out[key] = {name: self.schema(sub, stack) for name, sub in value.items()}
            elif key in _OPEN_SCHEMA_KEYS:
                if value is False:
                    out[key] = False
                elif isinstance(value, dict):
                    sub = self.schema(value, stack)
                    if sub:
                        out[key] = sub
            elif key in _SCHEMA_KEYS and isinstance(value, (dict, bool)):
                out[key] = self.schema(value, stack)
            elif key in _SCHEMA_LIST_KEYS and isinstance(value, list):
                out[key] = [self.schema(sub, stack) for sub in value]
            elif key == "required" and isinstance(value, list):
                out[key] = sorted({str(v) for v in value})
            elif key == "discriminator" and isinstance(value, dict):
                out[key] = {k: _jsonable(v) for k, v in value.items() if not self.ignored(k)}
            else:
                out[key] = _jsonable(value)
        return _unify(out)

    def _ref_schema(self, node: dict[str, Any], stack: tuple[str, ...]) -> dict[str, Any]:
        ref = node["$ref"]
        name = _component_name(ref)
        if not ref.startswith("#"):
            resolved: dict[str, Any] = {EXTERNAL_REF: ref}
        elif name in self.recursive:
            if name not in self.defs:
                self.defs[name] = {}  # placeholder: the definition refers to itself
                self.defs[name] = {**self.schema(self.lookup(ref)), COMPONENT: name}
            resolved = {REF: name}
            siblings = {k: v for k, v in node.items() if k != "$ref"}
            extra = self.schema(siblings, stack) if siblings else {}
            if set(extra) <= OVERLAY_KEYS:
                # Annotations next to a recursive $ref ride on the marker; the
                # differ overlays them onto the definition.
                return {**resolved, **extra}
            return _unify({"allOf": [resolved, extra]})
        elif ref in stack:
            # Only reachable through refs that aren't components (rare): no
            # definition is stored, the marker alone stands for the cycle.
            self._cycles += 1
            resolved = {REF: name or ref}
        elif ref in self._cache:
            resolved = self._cache[ref]
        else:
            before = self._cycles
            resolved = self.schema(self.lookup(ref), (*stack, ref))
            if name:
                resolved = {**resolved, COMPONENT: name}
            if self._cycles == before:
                self._cache[ref] = resolved
        siblings = {k: v for k, v in node.items() if k != "$ref"}
        if not siblings:
            return resolved
        # 3.1 allows keys next to $ref (and 3.0 generators emit `nullable` there):
        # treat them as an allOf with the target, which _unify collapses when it can.
        extra = self.schema(siblings, stack)
        if not extra:
            return resolved
        return _unify({"allOf": [resolved, extra]})


def _types(schema: dict[str, Any]) -> list[str]:
    t = schema.get("type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [str(x) for x in t]
    return []


def _is_null_schema(schema: Any) -> bool:
    if not isinstance(schema, dict):
        return False
    public = {k: v for k, v in schema.items() if not k.startswith(INTERNAL_PREFIX)}
    return public in ({"type": "null"}, {"enum": [None]}, {"const": None})


def _unify(out: dict[str, Any]) -> dict[str, Any]:
    """Canonicalize nullability, exclusive bounds, enums and composition lists."""
    nullable = out.pop("nullable", False) is True
    types = _types(out)
    if "null" in types and len(types) > 1:
        nullable = True
        types = [t for t in types if t != "null"]
    if types:
        unique = sorted(set(types))
        out["type"] = unique[0] if len(unique) == 1 else unique

    enum = out.get("enum")
    if isinstance(enum, list):
        if None in enum and len(enum) > 1:
            nullable = True
            enum = [v for v in enum if v is not None]
        unique_enum = {canonical_json(v): v for v in enum}
        out["enum"] = [unique_enum[k] for k in sorted(unique_enum)]

    # 3.0 spells exclusive bounds as booleans next to minimum/maximum; 3.1 as numbers.
    for bound, exclusive in (("minimum", "exclusiveMinimum"), ("maximum", "exclusiveMaximum")):
        if out.get(exclusive) is True and bound in out:
            out[exclusive] = out.pop(bound)
        elif out.get(exclusive) is False:
            del out[exclusive]

    for keyword in ("anyOf", "oneOf"):
        members = out.get(keyword)
        if not isinstance(members, list):
            continue
        non_null = [m for m in members if not _is_null_schema(m)]
        if len(non_null) < len(members) and non_null:
            nullable = True
            if len(non_null) == 1:
                # `anyOf: [X, null]` is just a nullable X.
                del out[keyword]
                out["allOf"] = [*out.get("allOf", []), non_null[0]]
            else:
                out[keyword] = non_null

    if nullable:
        out["nullable"] = True

    for keyword in _UNORDERED_LIST_KEYS:
        if isinstance(out.get(keyword), list):
            unique_members = {canonical_json(m): m for m in out[keyword]}
            out[keyword] = [unique_members[k] for k in sorted(unique_members)]

    if isinstance(out.get("allOf"), list):
        rest = {k: v for k, v in out.items() if k != "allOf"}
        merged = _merge([rest, *out["allOf"]])
        if merged is not None:
            return _unify(merged)
    return out


def _merge(schemas: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Merge ``allOf`` members into one schema, or ``None`` if they conflict.

    Only the unambiguous cases merge: disjoint keys, identical values, property
    maps without clashing names, and ``required`` lists. Anything else keeps the
    ``allOf`` so the differ can still compare it, conservatively.
    """
    if any(EXTERNAL_REF in s for s in schemas):
        return None
    markers = [s for s in schemas if REF in s]
    if markers:
        # A lone marker merges with plain overlay keys (`allOf: [Node]`, or
        # `anyOf: [Node, null]` which arrives here as a nullable `allOf: [Node]`),
        # so it reads the same as `$ref: Node` with `nullable` next to it.
        rest = [s for s in schemas if s is not markers[0]]
        if len(markers) > 1 or not all(
            k in OVERLAY_KEYS or k == COMPONENT for s in rest for k in s
        ):
            return None
        marker = dict(markers[0])
        for schema in rest:
            for key, value in schema.items():
                if key == COMPONENT:
                    continue
                if key == "nullable":
                    marker[key] = marker.get(key) is True or value is True
                elif key in marker and canonical_json(marker[key]) != canonical_json(value):
                    return None
                else:
                    marker[key] = value
        return marker
    merged: dict[str, Any] = {}
    for schema in schemas:
        for key, value in schema.items():
            if key == COMPONENT:
                # The outermost name wins: it's the schema the user referenced.
                merged.setdefault(key, value)
            elif key not in merged:
                merged[key] = value
            elif key == "nullable":
                merged[key] = merged[key] or value
            elif key == "required":
                merged[key] = sorted(set(merged[key]) | set(value))
            elif key == "properties" and isinstance(value, dict):
                props = dict(merged[key])
                for name, sub in value.items():
                    if name in props and canonical_json(props[name]) != canonical_json(sub):
                        return None
                    props[name] = sub
                merged[key] = props
            elif canonical_json(merged[key]) != canonical_json(value):
                return None
    return merged


def _schema_refs(node: Any) -> set[str]:
    """Names of the components referenced anywhere inside ``node``."""
    found: set[str] = set()
    stack = [node]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            ref = item.get("$ref")
            if isinstance(ref, str):
                name = _component_name(ref)
                if name:
                    found.add(name)
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


def _recursive_components(doc: dict[str, Any]) -> set[str]:
    """Components that sit on a reference cycle (Tarjan's SCC, iteratively:
    large specs have more components than Python's recursion limit)."""
    schemas = dict((doc.get("definitions") or {}).items())
    schemas.update(((doc.get("components") or {}).get("schemas") or {}).items())
    graph = {name: sorted(_schema_refs(s) & schemas.keys()) for name, s in schemas.items()}
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    recursive: set[str] = set()
    counter = 0
    for root in graph:
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            node, i = work.pop()
            if i == 0:
                index[node] = low[node] = counter
                counter += 1
                stack.append(node)
                on_stack.add(node)
            if i < len(graph[node]):
                work.append((node, i + 1))
                nxt = graph[node][i]
                if nxt not in index:
                    work.append((nxt, 0))
                elif nxt in on_stack:
                    low[node] = min(low[node], index[nxt])
                continue
            if low[node] == index[node]:
                component = []
                while True:
                    member = stack.pop()
                    on_stack.discard(member)
                    component.append(member)
                    if member == node:
                        break
                if len(component) > 1 or node in graph[node]:
                    recursive.update(component)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[node])
    return recursive
