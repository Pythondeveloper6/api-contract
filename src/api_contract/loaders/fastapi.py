"""FastAPI loader: import an app (or app factory) and read ``app.openapi()``.

Mounted FastAPI sub-applications (``app.mount("/v1", sub_app)``) are absent
from the parent's OpenAPI document, so the loader merges them in: their paths
get the mount prefix, and their components join the parent's. A component
whose name is already taken by a *different* schema is renamed
``<Name>__<prefix>`` (``Order__v1``) and its references follow. Other mounted
ASGI apps (static files, ...) are skipped.
"""

from __future__ import annotations

import copy
import inspect
import os
import re
import typing
from collections.abc import Iterator
from typing import Any

from api_contract.loaders.base import BaseLoader, LoaderError, describe_callable, import_string


def _model_classes(tp: Any, seen: set[int] | None = None) -> typing.Iterator[type]:
    """Yield pydantic model classes reachable from a type annotation."""
    seen = set() if seen is None else seen
    if id(tp) in seen:
        return
    seen.add(id(tp))
    for arg in typing.get_args(tp):
        yield from _model_classes(arg, seen)
    fields = getattr(tp, "model_fields", None)
    if inspect.isclass(tp) and isinstance(fields, dict):
        yield tp
        for field in fields.values():
            yield from _model_classes(field.annotation, seen)


class FastAPILoader(BaseLoader):
    def __init__(self, target: str) -> None:
        super().__init__(target)
        self._app: Any = None

    @property
    def app(self) -> Any:
        if self._app is None:
            self._app = self._resolve()
        return self._app

    def _resolve(self) -> Any:
        try:
            from fastapi import FastAPI
        except ImportError as exc:
            raise LoaderError(
                "The FastAPI loader needs FastAPI: pip install 'api-contract[fastapi]'"
            ) from exc
        obj = import_string(self.target)
        if not isinstance(obj, FastAPI) and callable(obj):
            obj = obj()
        if not isinstance(obj, FastAPI):
            raise LoaderError(
                f"{self.target!r} is not a FastAPI app (got {type(obj).__name__}). "
                "Use 'fastapi:module:app' with a FastAPI instance or a factory returning one."
            )
        return obj

    def load(self) -> dict:
        doc = copy.deepcopy(self.app.openapi())
        for prefix, sub_app in _mounted_apps(self.app):
            _merge(doc, copy.deepcopy(sub_app.openapi()), prefix)
        return doc

    def _routes(self) -> Iterator[tuple[str, Any]]:
        """``(mount prefix, APIRoute)`` for the app and every mounted FastAPI app."""
        from fastapi.routing import APIRoute

        apps = [("", self.app), *_mounted_apps(self.app)]
        for prefix, app in apps:
            for route in app.routes:
                if isinstance(route, APIRoute):
                    yield prefix, route

    def attribute(self, method: str, path: str) -> str | None:
        method = method.upper()
        for prefix, route in self._routes():
            if prefix + route.path_format == path and method in route.methods:
                return describe_callable(route.endpoint)
        return None

    def attribute_schema(self, component_name: str) -> str | None:
        base = component_name.removesuffix("-Input").removesuffix("-Output")
        base = re.sub(r"__[A-Za-z0-9_]+$", "", base)  # Order__v1: renamed on merge
        for _, route in self._routes():
            roots = [route.response_model]
            roots += [p.field_info.annotation for p in route.dependant.body_params]
            for root in roots:
                for model in _model_classes(root):
                    if model.__name__ == base:
                        try:
                            file = inspect.getsourcefile(model)
                            _, line = inspect.getsourcelines(model)
                        except (TypeError, OSError):
                            return model.__module__ + "." + model.__qualname__
                        name = model.__qualname__.split("<locals>.")[-1]
                        return f"{model.__module__}.{name} ({os.path.relpath(file)}:{line})"
        return None


def _mounted_apps(app: Any, prefix: str = "") -> list[tuple[str, Any]]:
    """Every FastAPI app mounted under ``app`` (recursively), with its full prefix."""
    from fastapi import FastAPI
    from starlette.routing import Mount

    found = []
    for route in getattr(app, "routes", ()):
        if isinstance(route, Mount) and isinstance(route.app, FastAPI):
            full = prefix + route.path.rstrip("/")
            found.append((full, route.app))
            found += _mounted_apps(route.app, full)
    return found


def _merge(doc: dict[str, Any], sub: dict[str, Any], prefix: str) -> None:
    """Add ``sub``'s paths (under ``prefix``) and components to ``doc``."""
    tag = re.sub(r"[^A-Za-z0-9]+", "_", prefix).strip("_") or "root"
    components = doc.setdefault("components", {})
    renames: dict[str, str] = {}
    for section, items in (sub.get("components") or {}).items():
        target = components.setdefault(section, {})
        for name, value in items.items():
            if name in target and target[name] != value:
                renames[f"#/components/{section}/{name}"] = f"#/components/{section}/{name}__{tag}"
    if renames:
        sub = _rewrite_refs(sub, renames)
    for section, items in (sub.get("components") or {}).items():
        target = components.setdefault(section, {})
        for name, value in items.items():
            new_name = renames.get(f"#/components/{section}/{name}", "").rpartition("/")[2]
            target[new_name or name] = value
    top_security = sub.get("security")
    paths = doc.setdefault("paths", {})
    for path, item in (sub.get("paths") or {}).items():
        if top_security is not None:
            for key, op in item.items():
                if isinstance(op, dict) and key != "parameters" and "security" not in op:
                    op["security"] = top_security
        paths[prefix + (path if path.startswith("/") else "/" + path)] = item


def _rewrite_refs(node: Any, renames: dict[str, str]) -> Any:
    if isinstance(node, dict):
        out = {k: _rewrite_refs(v, renames) for k, v in node.items()}
        if isinstance(out.get("$ref"), str) and out["$ref"] in renames:
            out["$ref"] = renames[out["$ref"]]
        return out
    if isinstance(node, list):
        return [_rewrite_refs(v, renames) for v in node]
    return node
