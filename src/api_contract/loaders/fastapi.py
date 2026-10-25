"""FastAPI loader: import an app (or app factory) and read ``app.openapi()``.

Mounted sub-applications (``app.mount("/v1", sub_app)``) are not followed:
their routes are absent from the parent's OpenAPI document, so they are
neither loaded nor attributed. Point a separate source at the sub-app.
"""

from __future__ import annotations

import inspect
import os
import typing
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
        return self.app.openapi()

    def attribute(self, method: str, path: str) -> str | None:
        from fastapi.routing import APIRoute

        method = method.upper()
        for route in self.app.routes:
            if (
                isinstance(route, APIRoute)
                and route.path_format == path
                and method in route.methods
            ):
                return describe_callable(route.endpoint)
        return None

    def attribute_schema(self, component_name: str) -> str | None:
        from fastapi.routing import APIRoute

        base = component_name.removesuffix("-Input").removesuffix("-Output")
        for route in self.app.routes:
            if not isinstance(route, APIRoute):
                continue
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
