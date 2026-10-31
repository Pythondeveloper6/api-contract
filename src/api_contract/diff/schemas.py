"""Recursive, direction-aware comparison of two normalized JSON Schemas.

The comparator never decides severity itself: it reports a change *kind*
(``response-field-removed``, ``request-constraint-tightened``...) and the rules
table maps kinds to severities. Anything it does not understand is reported as
``schema-changed`` (potentially breaking) rather than silently dropped.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..model import Direction
from ..normalize import COMPONENT, EXTERNAL_REF, INTERNAL_PREFIX, REF, canonical_json

# emit(kind, pointer, old, new, message, detail, component)
Emit = Callable[[str, str, Any, Any, str, "str | None", "str | None"], None]
# subject(pointer) -> 'response field "items[].total"'
Subject = Callable[[str], str]

# A larger value is stricter for these...
_MAX_KEYS = ("maxLength", "maxItems", "maxProperties", "maximum", "exclusiveMaximum")
# ...and a smaller one is stricter for these.
_MIN_KEYS = ("minLength", "minItems", "minProperties", "minimum", "exclusiveMinimum")

_HANDLED = {
    "type",
    "nullable",
    "format",
    "enum",
    "const",
    "default",
    "properties",
    "required",
    "items",
    "additionalProperties",
    "oneOf",
    "anyOf",
    "allOf",
    "not",
    "discriminator",
    "deprecated",
    "readOnly",
    "writeOnly",
    "pattern",
    "multipleOf",
    "uniqueItems",
    *_MAX_KEYS,
    *_MIN_KEYS,
}
# Pure annotations: never part of the contract, even when the user stops ignoring them.
_ANNOTATIONS = {
    "description",
    "title",
    "summary",
    "example",
    "examples",
    "externalDocs",
    "$comment",
    "$schema",
    "$id",
    "xml",
}


# Bookkeeping keys that stand in for a schema and so must take part in comparisons.
_MARKERS = (REF, EXTERNAL_REF)


def strip_internal(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: strip_internal(v)
            for k, v in value.items()
            if not k.startswith(INTERNAL_PREFIX) or k in _MARKERS
        }
    if isinstance(value, list):
        return [strip_internal(v) for v in value]
    return value


def same(old: Any, new: Any) -> bool:
    """Equality that ignores bookkeeping keys (component names, raw paths)."""
    return canonical_json(strip_internal(old)) == canonical_json(strip_internal(new))


def fmt(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return "|".join(value) if value else "any"
    return json.dumps(value, sort_keys=True, default=str)


def child(pointer: str, name: str) -> str:
    return f"{pointer}.{name}" if pointer else name


def schema_types(schema: dict[str, Any]) -> set[str]:
    t = schema.get("type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return set(t)
    # Generators often leave `type` out when the shape makes it obvious.
    if "properties" in schema or "additionalProperties" in schema or "required" in schema:
        return {"object"}
    if "items" in schema:
        return {"array"}
    return set()


def _covers(wide: set[str], narrow: set[str]) -> bool:
    """Every value valid for ``narrow`` is valid for ``wide`` (integer is a number)."""
    return all(t in wide or (t == "integer" and "number" in wide) for t in narrow)


def _overlap(a: set[str], b: set[str]) -> bool:
    return bool(a & b) or _covers(a, {"integer"}) and _covers(b, {"integer"})


def _enum(schema: dict[str, Any]) -> list[Any] | None:
    if isinstance(schema.get("enum"), list):
        return schema["enum"]
    if "const" in schema:
        return [schema["const"]]
    return None


def is_never(schema: Any) -> bool:
    """The 3.1 ``false`` schema (normalized to ``{"not": {}}``): no value is valid."""
    if not isinstance(schema, dict):
        return False
    public = {k: v for k, v in schema.items() if not k.startswith(INTERNAL_PREFIX)}
    return public == {"not": {}}


def _overlay(marker: dict[str, Any]) -> dict[str, Any]:
    """The keys sitting next to a recursive marker."""
    return {k: v for k, v in marker.items() if k not in _MARKERS}


def member_name(member: dict[str, Any]) -> str | None:
    """A composition member's name: its component, or the recursive component it marks."""
    return member.get(COMPONENT) or member.get(REF)


def refs_in(value: Any) -> set[str]:
    """Names of the recursive components referenced (by marker) inside ``value``."""
    found: set[str] = set()
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            if isinstance(item.get(REF), str):
                found.add(item[REF])
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return found


@dataclass
class Recursive:
    """The documents' recursive component definitions, and which of them changed
    either directly or through a component they reference."""

    old: dict[str, dict[str, Any]] = field(default_factory=dict)
    new: dict[str, dict[str, Any]] = field(default_factory=dict)
    changed: set[str] = field(default_factory=set)

    @classmethod
    def build(cls, old: dict[str, Any], new: dict[str, Any]) -> Recursive:
        names = old.keys() | new.keys()
        changed = {n for n in names if n not in old or n not in new or not same(old[n], new[n])}
        deps = {n: refs_in(old.get(n)) | refs_in(new.get(n)) for n in names}
        grew = True
        while grew:
            grew = False
            for name in names - changed:
                if deps[name] & changed:
                    changed.add(name)
                    grew = True
        return cls(old, new, changed)


class SchemaDiff:
    def __init__(
        self,
        direction: Direction,
        emit: Emit,
        subject: Subject,
        recursive: Recursive | None = None,
    ) -> None:
        self.direction = direction
        self.request = direction is Direction.REQUEST
        self.emit = emit
        self.subject = subject
        self.recursive = recursive or Recursive()
        # Marker pairs already followed under this root: a recursive component is
        # compared once, where it is first reached, which also ends the recursion.
        self._followed: set[tuple[str | None, str | None]] = set()

    def same(self, old: Any, new: Any) -> bool:
        if not same(old, new):
            return False
        # Equal text can still hide a change inside a referenced recursive component.
        return not (self.recursive.changed and refs_in(new) & self.recursive.changed)

    def _emit(
        self,
        kind: str,
        pointer: str,
        old: Any,
        new: Any,
        message: str,
        component: str | None,
        detail: str | None = None,
    ) -> None:
        self.emit(kind, pointer, old, new, message, detail, component)

    def _dir(self, request_kind: str, response_kind: str) -> str:
        return request_kind if self.request else response_kind

    # ---------------------------------------------------------------------

    def compare(
        self,
        old: dict[str, Any],
        new: dict[str, Any],
        pointer: str = "",
        component: str | None = None,
    ) -> None:
        # `allOf: [Node, Stamp]` -> `Node` (a lone recursive member collapses to its
        # marker): compare member lists so only Stamp's fields show as removed.
        if _bare_all_of(old) and "allOf" not in new:
            new = {"allOf": [new]}
        elif _bare_all_of(new) and "allOf" not in old:
            old = {"allOf": [old]}
        if REF in old or REF in new:
            self._follow(old, new, pointer, component)
            return
        if self.same(old, new):
            return
        component = new.get(COMPONENT) or old.get(COMPONENT) or component
        subject = self.subject(pointer)

        if EXTERNAL_REF in old or EXTERNAL_REF in new:
            self._emit(
                "schema-changed",
                pointer,
                old.get(EXTERNAL_REF),
                new.get(EXTERNAL_REF),
                f"{subject} external $ref changed",
                component,
                "$ref",
            )
            return

        if not self._types(old, new, pointer, subject, component):
            return
        self._nullable(old, new, pointer, subject, component)
        self._format(old, new, pointer, subject, component)
        self._enum(old, new, pointer, subject, component)
        self._constraints(old, new, pointer, subject, component)
        if not same(old.get("default"), new.get("default")):
            self._emit(
                "default-changed",
                pointer,
                old.get("default"),
                new.get("default"),
                f"{subject} default changed: {fmt(old.get('default'))} -> "
                f"{fmt(new.get('default'))}",
                component,
            )
        if pointer and new.get("deprecated") is True and old.get("deprecated") is not True:
            self._emit("field-deprecated", pointer, None, True, f"{subject} deprecated", component)
        self._properties(old, new, pointer, component)
        if "items" in old or "items" in new:
            # A missing `items` allows anything, the same as `{}`.
            self.compare(old.get("items", {}), new.get("items", {}), pointer + "[]", component)
        self._additional(old, new, pointer, subject, component)
        self._composition(old, new, pointer, subject, component)
        self._unknown(old, new, pointer, subject, component)

    def _follow(self, old, new, pointer, component) -> None:
        """Compare through ``{"x-api-contract-ref": name}`` markers (recursive components).

        Keys next to a marker (``nullable``, ``deprecated``...) apply to this use
        of the component and are overlaid onto its definition.
        """
        old_name, new_name = old.get(REF), new.get(REF)
        if old_name is not None and new_name is not None:
            old_extra, new_extra = _overlay(old), _overlay(new)
            # With a marker on only one side, the other side is a finite inline tree,
            # so the walk ends on its own; two markers need this guard.
            if (old_name, new_name) in self._followed or (
                old_name == new_name and old_name not in self.recursive.changed
            ):
                # The definitions are compared elsewhere (or are equal): only what
                # this use adds on top of them is left.
                if not same(old_extra, new_extra):
                    self.compare(old_extra, new_extra, pointer, component)
                return
            self._followed.add((old_name, new_name))
        old_def = self._definition(old, self.recursive.old)
        new_def = self._definition(new, self.recursive.new)
        if old_def is None or new_def is None:
            # A marker with no stored definition: all we can compare is the name.
            if old_name != new_name:
                self._emit(
                    "schema-changed",
                    pointer,
                    old_name,
                    new_name,
                    f"{self.subject(pointer)} recursive structure changed",
                    component,
                    "recursion",
                )
            return
        self.compare(old_def, new_def, pointer, component)

    @staticmethod
    def _definition(schema: dict[str, Any], defs: dict[str, dict[str, Any]]) -> Any:
        """The schema a marker stands for (with its overlay keys); others as they are."""
        name = schema.get(REF)
        if name is None:
            return schema
        definition = defs.get(name)
        if definition is None:
            return None
        return {**definition, **_overlay(schema)}

    # -- scalars -----------------------------------------------------------

    def _types(self, old, new, pointer, subject, component) -> bool:
        """Report a type change; return False when sub-diffs would only be noise."""
        old_never, new_never = is_never(old), is_never(new)
        if old_never or new_never:
            if old_never == new_never:
                return False
            # `false` is the narrowest schema there is: nothing is valid.
            if new_never:
                kind = self._dir("type-changed", "response-type-narrowed")
                verb = "narrowed" if kind == "response-type-narrowed" else "changed"
                old_t: list[str] | str = sorted(schema_types(old)) or "any"
                new_t: list[str] | str = "never"
            else:
                kind = self._dir("request-type-widened", "type-changed")
                verb = "widened" if kind == "request-type-widened" else "changed"
                old_t, new_t = "never", sorted(schema_types(new)) or "any"
            self._emit(
                kind,
                pointer,
                strip_internal(old),
                strip_internal(new),
                f"{subject} type {verb}: {fmt(old_t)} -> {fmt(new_t)}",
                component,
            )
            return False
        ot, nt = schema_types(old), schema_types(new)
        if ot == nt:
            return True
        if not ot:
            kind = self._dir("type-changed", "response-type-narrowed")
        elif not nt or _covers(nt, ot):
            kind = self._dir("request-type-widened", "type-changed")
        elif _covers(ot, nt):
            kind = self._dir("type-changed", "response-type-narrowed")
        else:
            kind = "type-changed"
        verb = {"request-type-widened": "widened", "response-type-narrowed": "narrowed"}.get(
            kind, "changed"
        )
        old_types, new_types = sorted(ot), sorted(nt)
        self._emit(
            kind,
            pointer,
            old_types,
            new_types,
            f"{subject} type {verb}: {fmt(old_types)} -> {fmt(new_types)}",
            component,
        )
        return not (ot and nt) or _overlap(ot, nt)

    def _nullable(self, old, new, pointer, subject, component) -> None:
        was, now = old.get("nullable") is True, new.get("nullable") is True
        if was == now:
            return
        if now:
            kind = self._dir("request-became-nullable", "response-became-nullable")
            message = f"{subject} became nullable"
        else:
            kind = self._dir("request-became-non-nullable", "response-became-non-nullable")
            message = f"{subject} is no longer nullable"
        self._emit(kind, pointer, was, now, message, component)

    def _format(self, old, new, pointer, subject, component) -> None:
        of, nf = old.get("format"), new.get("format")
        if of == nf:
            return
        if of and nf:
            kind, message = "format-changed", f"{subject} format changed: {of} -> {nf}"
        elif nf:
            kind, message = "format-added", f"{subject} format added: {nf}"
        else:
            kind, message = "format-removed", f"{subject} format removed: {of}"
        self._emit(kind, pointer, of, nf, message, component)

    def _enum(self, old, new, pointer, subject, component) -> None:
        oe, ne = _enum(old), _enum(new)
        if oe is None and ne is None:
            return
        if oe is None:
            kind = self._dir("request-enum-added", "response-enum-added")
            self._emit(kind, pointer, None, ne, f"{subject} restricted to {fmt(ne)}", component)
            return
        if ne is None:
            kind = self._dir("request-enum-removed", "response-enum-removed")
            self._emit(kind, pointer, oe, None, f"{subject} no longer an enum", component)
            return
        old_values = {canonical_json(v): v for v in oe}
        new_values = {canonical_json(v): v for v in ne}
        for key in sorted(new_values.keys() - old_values.keys()):
            value = new_values[key]
            kind = self._dir("request-enum-value-added", "response-enum-value-added")
            self._emit(
                kind,
                pointer,
                None,
                value,
                f"{subject} enum value added: {json.dumps(value)}",
                component,
                key,
            )
        for key in sorted(old_values.keys() - new_values.keys()):
            value = old_values[key]
            kind = self._dir("request-enum-value-removed", "response-enum-value-removed")
            self._emit(
                kind,
                pointer,
                value,
                None,
                f"{subject} enum value removed: {json.dumps(value)}",
                component,
                key,
            )

    def _constraints(self, old, new, pointer, subject, component) -> None:
        checks: list[tuple[str, bool | None]] = []
        for key in (*_MAX_KEYS, *_MIN_KEYS):
            o, n = old.get(key), new.get(key)
            if o == n or not all(isinstance(v, (int, float)) or v is None for v in (o, n)):
                continue
            if o is None:
                tightened = True
            elif n is None:
                tightened = False
            else:
                tightened = n < o if key in _MAX_KEYS else n > o
            checks.append((key, tightened))
        for key in ("pattern", "multipleOf"):
            o, n = old.get(key), new.get(key)
            if o != n:
                # A changed pattern can't be ordered; `None` means "unknown direction".
                checks.append((key, n is not None if o is None or n is None else None))
        if bool(old.get("uniqueItems")) != bool(new.get("uniqueItems")):
            checks.append(("uniqueItems", bool(new.get("uniqueItems"))))

        for key, direction in checks:
            o, n = old.get(key), new.get(key)
            # Unknown direction: report whichever reading hurts this direction.
            tightened = self.request if direction is None else direction
            word = "tightened" if tightened else "loosened"
            kind = f"{self.direction.value}-constraint-{word}"
            self._emit(
                kind, pointer, o, n, f"{subject} {key} {word}: {fmt(o)} -> {fmt(n)}", component, key
            )

    # -- objects and arrays --------------------------------------------------

    def _visible(self, schema: Any, defs: dict[str, dict[str, Any]]) -> Any:
        if schema is None:
            return None
        # A recursive marker's own keys win; its definition supplies the rest.
        resolved = self._definition(schema, defs) or schema
        if self.request and resolved.get("readOnly") is True:
            return None
        if not self.request and resolved.get("writeOnly") is True:
            return None
        return schema

    def _properties(self, old, new, pointer, component) -> None:
        op, np_ = old.get("properties") or {}, new.get("properties") or {}
        oreq, nreq = set(old.get("required") or []), set(new.get("required") or [])
        names = sorted(set(op) | set(np_) | oreq | nreq)
        for name in names:
            os_ = self._visible(op.get(name, {} if name in oreq else None), self.recursive.old)
            ns_ = self._visible(np_.get(name, {} if name in nreq else None), self.recursive.new)
            if os_ is None and ns_ is None:
                continue
            ptr = child(pointer, name)
            subject = self.subject(ptr)
            # A `false` schema (`{"not": {}}`) admits no value: the field may not appear.
            old_never, new_never = is_never(os_), is_never(ns_)
            if (old_never or os_ is None) and (new_never or ns_ is None):
                # Neither side documents a value for this field.
                continue
            if new_never and self.request and name in nreq:
                # Required yet impossible: no request can be valid any more.
                self.compare(os_, ns_, ptr, component)
                continue
            if new_never:
                kind = self._dir("request-field-removed", "response-field-removed")
                message = f"{subject} removed (schema is now false)"
                self._emit(kind, ptr, strip_internal(os_), False, message, component)
                continue
            if old_never:
                os_ = None
            # Field-level changes belong to the enclosing schema (the serializer or
            # model that declares the field), not to the field's own type.
            comp = component
            if os_ is None:
                if self.request:
                    required = name in nreq
                    kind = (
                        "required-request-field-added"
                        if required
                        else "optional-request-field-added"
                    )
                    word = "required" if required else "optional"
                    message = f"new {word} {subject}"
                else:
                    kind, message = "response-field-added", f"new {subject}"
                self._emit(kind, ptr, None, strip_internal(ns_), message, comp)
                continue
            if ns_ is None:
                kind = self._dir("request-field-removed", "response-field-removed")
                self._emit(kind, ptr, strip_internal(os_), None, f"{subject} removed", comp)
                continue
            was, now = name in oreq, name in nreq
            if was != now:
                if self.request:
                    kind = (
                        "request-field-became-required" if now else "request-field-became-optional"
                    )
                else:
                    kind = (
                        "response-field-became-required"
                        if now
                        else "response-field-became-optional"
                    )
                word = "required" if now else "optional"
                self._emit(kind, ptr, was, now, f"{subject} became {word}", comp)
            self.compare(os_, ns_, ptr, component)

    def _additional(self, old, new, pointer, subject, component) -> None:
        oa, na = old.get("additionalProperties"), new.get("additionalProperties")
        if self.same(oa, na):
            return
        if isinstance(oa, dict) and isinstance(na, dict):
            self.compare(oa, na, pointer + "{}", component)
            return
        # absent (anything) < schema (some values) < false (nothing extra)
        rank = {type(None): 0, dict: 1, bool: 2}
        tightened = rank[type(na)] > rank[type(oa)]
        word = "tightened" if tightened else "loosened"
        self._emit(
            f"{self.direction.value}-constraint-{word}",
            pointer,
            strip_internal(oa),
            strip_internal(na),
            f"{subject} additionalProperties {word}",
            component,
            "additionalProperties",
        )

    # -- composition ---------------------------------------------------------

    def _composition(self, old, new, pointer, subject, component) -> None:
        for keyword in ("oneOf", "anyOf", "allOf"):
            ol, nl = old.get(keyword), new.get(keyword)
            if ol is None and nl is None:
                continue
            if ol is None or nl is None:
                self._emit(
                    "composition-changed",
                    pointer,
                    strip_internal(ol),
                    strip_internal(nl),
                    f"{subject} {keyword} {'added' if ol is None else 'removed'}",
                    component,
                    keyword,
                )
                continue
            pairs, gone, added = _match(ol, nl, self.same)
            for om, nm in pairs:
                label = member_name(nm) or member_name(om) or keyword
                self.compare(om, nm, f"{pointer}<{label}>", component)
            if keyword == "allOf":
                # Every allOf member applies, so an added member is a set of new
                # constraints and a removed one a set of dropped ones: compare each
                # with "no constraint" to see the fields it brings or takes away.
                for member in gone:
                    label = member_name(member) or keyword
                    empty = self._unconstrained(member, nl, self.recursive.old)
                    self.compare(member, empty, f"{pointer}<{label}>", component)
                for member in added:
                    label = member_name(member) or keyword
                    empty = self._unconstrained(member, ol, self.recursive.new)
                    self.compare(empty, member, f"{pointer}<{label}>", component)
                continue
            # Named leftovers (distinct components) are clearly separate variants;
            # anonymous ones on both sides could be edits we failed to pair.
            anon_gone = [m for m in gone if not member_name(m)]
            anon_added = [m for m in added if not member_name(m)]
            if anon_gone and anon_added:
                self._emit(
                    "composition-changed",
                    pointer,
                    [strip_internal(m) for m in anon_gone],
                    [strip_internal(m) for m in anon_added],
                    f"{subject} {keyword} members changed",
                    component,
                    keyword,
                )
                gone = [m for m in gone if member_name(m)]
                added = [m for m in added if member_name(m)]
            for members, word, kind in (
                (gone, "removed", self._dir("request-variant-removed", "response-variant-removed")),
                (added, "added", self._dir("request-variant-added", "response-variant-added")),
            ):
                details = _variant_details(members)
                for member, detail in zip(members, details, strict=True):
                    name = member_name(member)
                    described = name or detail
                    self._emit(
                        kind,
                        pointer,
                        strip_internal(member) if word == "removed" else None,
                        strip_internal(member) if word == "added" else None,
                        f"{subject} {keyword} variant {word}: {described}",
                        component,
                        detail,
                    )
        for keyword in ("not", "discriminator"):
            if not same(old.get(keyword), new.get(keyword)):
                self._emit(
                    "composition-changed",
                    pointer,
                    strip_internal(old.get(keyword)),
                    strip_internal(new.get(keyword)),
                    f"{subject} {keyword} changed",
                    component,
                    keyword,
                )

    def _unconstrained(self, member, others, defs) -> dict[str, Any]:
        """``{}`` standing in for an allOf ``member`` that the other side lacks.

        It keeps the member's type when a member on the other side still has it,
        so dropping one of several object members isn't read as "object -> any".
        """
        types = schema_types(self._definition(member, defs) or member)
        defs_other = self.recursive.new if defs is self.recursive.old else self.recursive.old
        for other in others:
            if types and schema_types(self._definition(other, defs_other) or other) == types:
                return {"type": sorted(types)[0] if len(types) == 1 else sorted(types)}
        return {}

    def _unknown(self, old, new, pointer, subject, component) -> None:
        for key in sorted(set(old) | set(new)):
            if key in _HANDLED or key in _ANNOTATIONS or key.startswith(INTERNAL_PREFIX):
                continue
            if not same(old.get(key), new.get(key)):
                self._emit(
                    "schema-changed",
                    pointer,
                    strip_internal(old.get(key)),
                    strip_internal(new.get(key)),
                    f"{subject} schema keyword {key!r} changed",
                    component,
                    key,
                )


def _match(
    old: list[dict[str, Any]], new: list[dict[str, Any]], equal: Callable[[Any, Any], bool]
) -> tuple[list[tuple[dict, dict]], list[dict], list[dict]]:
    """Pair up composition members: identical first, then by component name,
    then a lone anonymous leftover on each side is assumed to be the same member edited."""
    old_left, new_left = list(old), list(new)
    pairs: list[tuple[dict, dict]] = []
    for o in list(old_left):
        for n in new_left:
            if equal(o, n):
                old_left.remove(o)
                new_left.remove(n)
                break
    for o in list(old_left):
        name = member_name(o)
        if not name:
            continue
        for n in new_left:
            if member_name(n) == name:
                pairs.append((o, n))
                old_left.remove(o)
                new_left.remove(n)
                break
    if len(old_left) == 1 and len(new_left) == 1:
        o, n = old_left[0], new_left[0]
        if member_name(o) and member_name(n):
            # Two differently named components are two different variants.
            return pairs, old_left, new_left
        pairs.append((old_left.pop(), new_left.pop()))
    return pairs, old_left, new_left


def _bare_all_of(schema: dict[str, Any]) -> bool:
    """Only an ``allOf`` (normalization merges it away whenever it can)."""
    return "allOf" in schema and all(
        k == "allOf" or k.startswith(INTERNAL_PREFIX) and k not in _MARKERS for k in schema
    )


def _variant_details(members: list[dict[str, Any]]) -> list[str]:
    """Readable, deterministic id details for unpaired composition members.

    A named member is its component name. An anonymous one is its type
    (``integer``), or that plus a short hash of its schema when the type alone
    is missing or shared with another member on the same side.
    """
    names = {member_name(m) for m in members}
    types = ["|".join(sorted(schema_types(m))) for m in members]
    details = []
    for member, type_ in zip(members, types, strict=True):
        name = member_name(member)
        if name:
            details.append(name)
            continue
        if type_ and types.count(type_) == 1 and type_ not in names:
            details.append(type_)
            continue
        digest = hashlib.sha1(canonical_json(strip_internal(member)).encode()).hexdigest()[:8]
        details.append(f"{type_ or 'schema'}#{digest}")
    return details
