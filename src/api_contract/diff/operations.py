"""Compare two normalized documents operation by operation.

Endpoints, methods, parameters, request bodies, responses and security are
handled here; schemas are handed to :class:`~api_contract.diff.schemas.SchemaDiff`
with the direction (request or response) that decides how they're judged.
"""

from __future__ import annotations

from typing import Any

from ..model import Change, Direction
from ..normalize import METHODS, PARAM_NAME, RAW_PATH, RECURSIVE, canonical_json
from ..rules import Rules
from .schemas import Recursive, SchemaDiff, fmt

_SERIALIZATION_KEYS = ("style", "explode", "allowReserved", "allowEmptyValue")
_JSON = "application/json"


class _Collector:
    def __init__(self, rules: Rules) -> None:
        self.rules = rules
        self.changes: list[Change] = []

    def add(
        self,
        kind: str,
        direction: Direction,
        method: str,
        path: str,
        raw_path: str,
        *,
        location: str = "",
        pointer: str = "",
        old: Any = None,
        new: Any = None,
        message: str = "",
        detail: str | None = None,
        component: str | None = None,
    ) -> None:
        self.changes.append(
            Change(
                kind=kind,
                severity=self.rules.severity(kind),
                direction=direction,
                method=method,
                path=path,
                raw_path=raw_path,
                location=location,
                pointer=pointer,
                detail=detail,
                old=old,
                new=new,
                message=message,
                component=component,
            )
        )


def diff_documents(
    old: dict[str, Any], new: dict[str, Any], rules: Rules | None = None
) -> list[Change]:
    """Diff two *normalized* documents. Changes come back sorted, worst first."""
    out = _Collector(rules or Rules())
    recursive = Recursive.build(old.get(RECURSIVE) or {}, new.get(RECURSIVE) or {})
    old_paths, new_paths = old.get("paths") or {}, new.get("paths") or {}
    for path in sorted(set(old_paths) | set(new_paths)):
        old_item, new_item = old_paths.get(path), new_paths.get(path)
        old_raw = (old_item or {}).get(RAW_PATH, path)
        new_raw = (new_item or {}).get(RAW_PATH, path)
        for method in METHODS:
            old_op = (old_item or {}).get(method)
            new_op = (new_item or {}).get(method)
            verb = method.upper()
            if old_op is None and new_op is None:
                continue
            if old_op is None:
                kind = "endpoint-added" if old_item is None else "method-added"
                out.add(kind, Direction.NONE, verb, path, new_raw, message="new endpoint")
            elif new_op is None:
                if new_item is None:
                    kind, raw, message = "endpoint-removed", old_raw, "endpoint removed"
                else:
                    kind, raw, message = "method-removed", new_raw, "method removed"
                out.add(kind, Direction.NONE, verb, path, raw, message=message)
            else:
                _Operation(out, verb, path, new_raw, recursive).compare(old_op, new_op)
    return sorted(out.changes, key=Change.sort_key)


class _Operation:
    def __init__(
        self, out: _Collector, method: str, path: str, raw_path: str, recursive: Recursive
    ) -> None:
        self.out = out
        self.recursive = recursive
        self.method = method
        self.path = path
        self.raw_path = raw_path

    def add(self, kind: str, direction: Direction, **kwargs: Any) -> None:
        self.out.add(kind, direction, self.method, self.path, self.raw_path, **kwargs)

    def schemas(
        self,
        direction: Direction,
        location: str,
        subject_of,
        old: dict[str, Any],
        new: dict[str, Any],
    ) -> None:
        def emit(kind, pointer, o, n, message, detail, component):
            self.add(
                kind,
                direction,
                location=location,
                pointer=pointer,
                old=o,
                new=n,
                message=message,
                detail=detail,
                component=component,
            )

        SchemaDiff(direction, emit, subject_of, self.recursive).compare(old, new)

    def compare(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        if new.get("deprecated") is True and old.get("deprecated") is not True:
            self.add("endpoint-deprecated", Direction.NONE, new=True, message="endpoint deprecated")
        self.parameters(old.get("parameters") or {}, new.get("parameters") or {})
        self.request_body(old.get("requestBody"), new.get("requestBody"))
        self.responses(old.get("responses") or {}, new.get("responses") or {})
        self.security(old.get("security") or [], new.get("security") or [])

    # -- parameters ----------------------------------------------------------

    def parameters(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        req = Direction.REQUEST
        for key in sorted(set(old) | set(new)):
            op, np_ = old.get(key), new.get(key)
            label = _param_label(key, np_ or op)
            location = f"param:{key}"
            if op is None:
                required = np_.get("required") is True
                kind = "required-param-added" if required else "optional-param-added"
                word = "required" if required else "optional"
                self.add(kind, req, location=location, message=f"new {word} {label}")
                continue
            if np_ is None:
                self.add("param-removed", req, location=location, message=f"{label} removed")
                continue
            was, now = op.get("required") is True, np_.get("required") is True
            if was != now:
                kind = "param-became-required" if now else "param-became-optional"
                word = "required" if now else "optional"
                self.add(
                    kind, req, location=location, old=was, new=now, message=f"{label} became {word}"
                )
            for name in _SERIALIZATION_KEYS:
                if op.get(name) != np_.get(name):
                    self.add(
                        "param-serialization-changed",
                        req,
                        location=location,
                        old=op.get(name),
                        new=np_.get(name),
                        detail=name,
                        message=f"{label} {name} changed: {fmt(op.get(name))} -> "
                        f"{fmt(np_.get(name))}",
                    )
            if np_.get("deprecated") is True and op.get("deprecated") is not True:
                self.add(
                    "param-deprecated",
                    req,
                    location=location,
                    new=True,
                    message=f"{label} deprecated",
                )

            def subject(pointer: str, label: str = label) -> str:
                return f'{label} field "{pointer}"' if pointer else label

            self.schemas(req, location, subject, op.get("schema", {}), np_.get("schema", {}))

    # -- request body --------------------------------------------------------

    def request_body(self, old: dict[str, Any] | None, new: dict[str, Any] | None) -> None:
        req = Direction.REQUEST
        if old is None and new is None:
            return
        if old is None:
            required = new.get("required") is True
            kind = "required-request-body-added" if required else "optional-request-body-added"
            word = "required" if required else "optional"
            self.add(kind, req, location="request", message=f"new {word} request body")
            return
        if new is None:
            self.add(
                "request-body-removed", req, location="request", message="request body removed"
            )
            return
        was, now = old.get("required") is True, new.get("required") is True
        if was != now:
            kind = "request-body-became-required" if now else "request-body-became-optional"
            word = "required" if now else "optional"
            self.add(
                kind,
                req,
                location="request",
                old=was,
                new=now,
                message=f"request body became {word}",
            )
        old_content, new_content = old.get("content") or {}, new.get("content") or {}
        for media_type in sorted(set(old_content) | set(new_content)):
            location = f"request:{media_type}"
            if media_type not in new_content:
                self.add(
                    "request-content-type-removed",
                    req,
                    location=location,
                    old=media_type,
                    message=f"request content type {media_type} removed",
                )
            elif media_type not in old_content:
                self.add(
                    "request-content-type-added",
                    req,
                    location=location,
                    new=media_type,
                    message=f"request content type {media_type} added",
                )
            else:
                suffix = "" if media_type == _JSON else f" ({media_type})"

                def subject(pointer: str, suffix: str = suffix) -> str:
                    return (f'request field "{pointer}"' if pointer else "request body") + suffix

                self.schemas(
                    req,
                    location,
                    subject,
                    old_content[media_type].get("schema", {}),
                    new_content[media_type].get("schema", {}),
                )

    # -- responses -----------------------------------------------------------

    def responses(self, old: dict[str, Any], new: dict[str, Any]) -> None:
        res = Direction.RESPONSE
        for code in sorted(set(old) | set(new)):
            success = code.startswith("2")
            location = f"response:{code}"
            if code not in new:
                kind = "response-success-removed" if success else "response-status-removed"
                self.add(kind, res, location=location, old=code, message=f"response {code} removed")
                continue
            if code not in old:
                kind = "response-success-added" if success else "response-status-added"
                self.add(kind, res, location=location, new=code, message=f"response {code} added")
                continue
            prefix = "response" if success else f"{code} response"
            self.response_content(code, prefix, old[code], new[code])
            self.response_headers(code, prefix, old[code], new[code])

    def response_content(self, code: str, prefix: str, old: dict, new: dict) -> None:
        res = Direction.RESPONSE
        old_content, new_content = old.get("content") or {}, new.get("content") or {}
        for media_type in sorted(set(old_content) | set(new_content)):
            location = f"response:{code}:{media_type}"
            if media_type not in new_content:
                self.add(
                    "response-content-type-removed",
                    res,
                    location=location,
                    old=media_type,
                    message=f"response {code} content type {media_type} removed",
                )
            elif media_type not in old_content:
                self.add(
                    "response-content-type-added",
                    res,
                    location=location,
                    new=media_type,
                    message=f"response {code} content type {media_type} added",
                )
            else:
                suffix = "" if media_type == _JSON else f" ({media_type})"

                def subject(pointer: str, prefix: str = prefix, suffix: str = suffix) -> str:
                    base = f'{prefix} field "{pointer}"' if pointer else f"{prefix} body"
                    return base + suffix

                self.schemas(
                    res,
                    location,
                    subject,
                    old_content[media_type].get("schema", {}),
                    new_content[media_type].get("schema", {}),
                )

    def response_headers(self, code: str, prefix: str, old: dict, new: dict) -> None:
        res = Direction.RESPONSE
        old_headers, new_headers = old.get("headers") or {}, new.get("headers") or {}
        for name in sorted(set(old_headers) | set(new_headers)):
            location = f"response:{code}:header:{name}"
            if name not in new_headers:
                self.add(
                    "response-header-removed",
                    res,
                    location=location,
                    message=f'{prefix} header "{name}" removed',
                )
            elif name not in old_headers:
                self.add(
                    "response-header-added",
                    res,
                    location=location,
                    message=f'{prefix} header "{name}" added',
                )
            else:
                was = old_headers[name].get("required") is True
                now = new_headers[name].get("required") is True
                if was != now:
                    word = "required" if now else "optional"
                    self.add(
                        f"response-header-became-{word}",
                        res,
                        location=location,
                        old=was,
                        new=now,
                        message=f'{prefix} header "{name}" became {word}',
                    )

                def subject(pointer: str, name: str = name) -> str:
                    base = f'{prefix} header "{name}"'
                    return f'{base} field "{pointer}"' if pointer else base

                self.schemas(
                    res,
                    location,
                    subject,
                    old_headers[name].get("schema", {}),
                    new_headers[name].get("schema", {}),
                )

    # -- security ------------------------------------------------------------

    def security(self, old: list[dict], new: list[dict]) -> None:
        """Alternatives are OR-ed; schemes inside one alternative are AND-ed.

        A client keeps working as long as the alternative it uses is still
        accepted with no extra scopes.
        """
        none = Direction.NONE
        old_anon = not old or {} in old
        new_anon = not new or {} in new
        if old_anon and new_anon:
            return
        if old_anon:
            self.add(
                "auth-added",
                none,
                location="security",
                old=old,
                new=new,
                message=f"authentication now required: {_alternatives(new)}",
            )
            return
        if new_anon:
            self.add(
                "auth-removed",
                none,
                location="security",
                old=old,
                new=new,
                message="authentication no longer required",
            )
            return
        # Identical alternatives (same schemes *and* scopes) are unchanged. What's
        # left is paired by scheme names when that's unambiguous, so a scope edit
        # reads as one; otherwise each leftover alternative was removed or added.
        new_keys = {canonical_json(alt) for alt in new}
        old_keys = {canonical_json(alt) for alt in old}
        gone = [alt for alt in old if canonical_json(alt) not in new_keys]
        added = [alt for alt in new if canonical_json(alt) not in old_keys]
        groups: dict[frozenset, tuple[list[dict], list[dict]]] = {}
        for side, alts in ((0, gone), (1, added)):
            for alt in alts:
                groups.setdefault(frozenset(alt), ([], []))[side].append(alt)
        names_old = {frozenset(alt) for alt in old}
        names_new = {frozenset(alt) for alt in new}
        for key in sorted(groups, key=lambda k: sorted(k)):
            removed, appeared = groups[key]
            if len(removed) == 1 and len(appeared) == 1:
                self._scopes(key, removed[0], appeared[0])
                continue
            for alt in removed:
                # Name the scopes too when the same schemes still appear elsewhere.
                verbose = len(removed) > 1 or key in names_new
                name = _alternative(alt, scopes=verbose)
                self.add(
                    "auth-alternative-removed",
                    none,
                    location="security",
                    detail=name,
                    old=alt,
                    message=f"authentication option {name} no longer accepted",
                )
            for alt in appeared:
                verbose = len(appeared) > 1 or key in names_old
                name = _alternative(alt, scopes=verbose)
                self.add(
                    "auth-alternative-added",
                    none,
                    location="security",
                    detail=name,
                    new=alt,
                    message=f"authentication option {name} added",
                )

    def _scopes(self, key: frozenset, old: dict, new: dict) -> None:
        for scheme in sorted(key):
            was, now = set(old[scheme]), set(new[scheme])
            for kind, scopes, word in (
                ("auth-scopes-added", now - was, "now requires"),
                ("auth-scopes-removed", was - now, "no longer requires"),
            ):
                if scopes:
                    self.add(
                        kind,
                        Direction.NONE,
                        location="security",
                        detail=scheme,
                        old=sorted(was),
                        new=sorted(now),
                        message=f"{scheme} {word} scopes: {', '.join(sorted(scopes))}",
                    )


def _alternative(alt: dict, *, scopes: bool = False) -> str:
    """``oauth+apiKey``, or ``oauth[read,write]+apiKey`` with ``scopes``."""
    if not scopes:
        return "+".join(sorted(alt))
    return "+".join(f"{k}[{','.join(sorted(alt[k]))}]" for k in sorted(alt))


def _alternatives(alternatives: list[dict]) -> str:
    return " or ".join("+".join(sorted(alt)) for alt in alternatives) or "none"


def _param_label(key: str, param: dict[str, Any]) -> str:
    location, _, name = key.partition(":")
    if location == "path":
        name = param.get(PARAM_NAME, name)
    return f'{location} parameter "{name}"'
