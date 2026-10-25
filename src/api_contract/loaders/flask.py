"""Flask loader: APIFlask, flask-smorest and flask-openapi3 (auto-detected).

Blueprints are covered because attribution goes through ``app.url_map``, which
includes every registered blueprint. Apps that serve several flask-smorest
``Api`` objects only load the first one registered.
"""

from __future__ import annotations

import re
from typing import Any

from api_contract.loaders.base import BaseLoader, LoaderError, describe_callable, import_string

_CONVERTER = re.compile(r"<(?:[^:<>]+:)?([^<>]+)>")

SUPPORTED = "APIFlask, flask-smorest, flask-openapi3"


class FlaskLoader(BaseLoader):
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
            from flask import Flask
        except ImportError as exc:
            raise LoaderError(
                "The Flask loader needs Flask: pip install 'api-contract[flask]'"
            ) from exc
        obj = import_string(self.target)
        if not isinstance(obj, Flask) and callable(obj):
            obj = obj()
        if not isinstance(obj, Flask):
            raise LoaderError(
                f"{self.target!r} is not a Flask app (got {type(obj).__name__}). "
                "Use 'flask:module:app' with a Flask instance or a create_app factory."
            )
        return obj

    # -- loading -----------------------------------------------------------

    def load(self) -> dict:
        app = self.app
        with app.app_context(), app.test_request_context():
            spec = self._find_spec(app)
        if spec is None:
            raise LoaderError(
                f"Could not find an OpenAPI source on the Flask app {self.target!r}. "
                f"Supported libraries: {SUPPORTED}. Install one with "
                "pip install 'api-contract[apiflask]', 'api-contract[smorest]' or "
                "'api-contract[flask-openapi3]' (the 'flask' extra installs only Flask). "
                "For anything else, export the spec "
                "with 'file:module:callable' (a callable returning the OpenAPI dict)."
            )
        return spec

    def _find_spec(self, app: Any) -> dict | None:
        # 1. APIFlask: ``app.spec`` is a dict (or a YAML string if configured so).
        try:
            from apiflask import APIFlask
        except ImportError:
            APIFlask = None  # noqa: N806
        if APIFlask is not None and isinstance(app, APIFlask):
            spec = app.spec
            if isinstance(spec, str):
                import yaml

                spec = yaml.safe_load(spec)
            return dict(spec)

        # 2. flask-smorest registers ``{"apis": {prefix: {"ext_obj": Api}}}``.
        ext = getattr(app, "extensions", {}).get("flask-smorest")
        if ext:
            for entry in ext.get("apis", {}).values():
                return entry["ext_obj"].spec.to_dict()

        # 3. flask-openapi3: ``api_doc`` is a property (older versions: a method).
        try:
            from flask_openapi3 import OpenAPI
        except ImportError:
            OpenAPI = None  # noqa: N806
        if OpenAPI is not None and isinstance(app, OpenAPI):
            doc = app.api_doc
            if callable(doc):
                doc = doc()
            return dict(doc)
        return None

    # -- attribution -------------------------------------------------------

    def _rule_for(self, method: str, path: str) -> Any:
        for rule in self.app.url_map.iter_rules():
            if method not in (rule.methods or ()):
                continue
            if rule.rule == path or _CONVERTER.sub(r"{\1}", rule.rule) == path:
                return rule
        return None

    def attribute(self, method: str, path: str) -> str | None:
        method = method.upper()
        rule = self._rule_for(method, path)
        if rule is None:
            return None
        view = self.app.view_functions.get(rule.endpoint)
        if view is None:
            return None
        view_class = getattr(view, "view_class", None)
        if view_class is not None:  # MethodView: resolve to the method on the class
            handler = getattr(view_class, method.lower(), None)
            if handler is not None:
                return describe_callable(handler)
        return describe_callable(view)
