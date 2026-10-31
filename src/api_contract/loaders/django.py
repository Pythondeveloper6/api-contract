"""Django loader: drf-spectacular (DRF) or django-ninja.

Source strings (the part after ``django:``):

- ``""`` auto-detect: drf-spectacular if installed, else a single NinjaAPI
  found in the URL patterns.
- ``"drf"`` drf-spectacular.
- ``"ninja"`` the single NinjaAPI found in the URL patterns.
- ``"ninja:pkg.mod:api"`` an explicit NinjaAPI instance.
"""

from __future__ import annotations

import inspect
import os
import sys
from pathlib import Path
from typing import Any

from api_contract.loaders.base import BaseLoader, LoaderError, import_string

_SETTINGS_HINT = (
    "Django is not configured. Set the DJANGO_SETTINGS_MODULE environment variable, "
    "or run it via `manage.py api_contract ...`."
)


def _setup_django() -> None:
    import django
    from django.apps import apps

    if apps.ready:
        return
    cwd = os.getcwd()
    if cwd not in sys.path:
        sys.path.insert(0, cwd)
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        raise LoaderError(_SETTINGS_HINT)
    try:
        django.setup()
    except Exception as exc:  # noqa: BLE001 - surface any settings/app import problem
        raise LoaderError(f"django.setup() failed: {type(exc).__name__}: {exc}") from exc


def _rel(path: str | None) -> str | None:
    if not path:
        return None
    try:
        return str(Path(path).resolve().relative_to(Path.cwd().resolve()))
    except ValueError:
        return None  # outside the project (site-packages etc.)


def _location(obj: Any) -> tuple[str, int] | None:
    """(project-relative file, line) for a function or class, or None if outside the project."""
    try:
        obj = inspect.unwrap(obj)
        if inspect.ismethod(obj):
            obj = obj.__func__
        file = inspect.getsourcefile(obj)
        _, line = inspect.getsourcelines(obj)
    except (TypeError, OSError):
        return None
    rel = _rel(file)
    return (rel, line) if rel else None


def _dotted(obj: Any) -> str:
    return f"{obj.__module__}.{obj.__qualname__}"


def _fmt_loc(loc: tuple[str, int] | None) -> str:
    return f" ({loc[0]}:{loc[1]})" if loc else ""


class DjangoLoader(BaseLoader):
    def __init__(self, target: str = "") -> None:
        super().__init__(target)
        kind, _, rest = (target or "").partition(":")
        if kind not in ("", "drf", "ninja"):
            raise LoaderError(
                f"Unknown django source {target!r}. Use 'django', 'django:drf' or "
                "'django:ninja:pkg.module:api'."
            )
        self._kind = kind
        self._ninja_ref = rest
        self._mode: str | None = None  # "drf" | "ninja", resolved lazily
        self._generator: Any = None
        self._schema: dict | None = None
        self._ninja_api: Any = None
        self._ninja_prefix = ""

    # -- public loader contract ------------------------------------------------

    def load(self) -> dict:
        _setup_django()
        mode = self._resolve_mode()
        if mode == "drf":
            return self._load_drf()
        return self._load_ninja()

    def attribute(self, method: str, path: str) -> str | None:
        try:
            self._ensure_loaded()
            if self._mode == "drf":
                return self._attribute_drf(method, path)
            return self._attribute_ninja(method, path)
        except LoaderError:
            raise
        except Exception:  # noqa: BLE001 - attribution is best-effort
            return None

    def attribute_schema(self, component_name: str) -> str | None:
        try:
            self._ensure_loaded()
            if self._mode == "drf":
                cls = self._drf_components().get(component_name)
            else:
                cls = self._ninja_schema_class(component_name)
            if cls is None:
                return None
            return f"{_dotted(cls)}{_fmt_loc(_location(cls))}"
        except LoaderError:
            raise
        except Exception:  # noqa: BLE001
            return None

    # -- mode selection ---------------------------------------------------------

    def _ensure_loaded(self) -> None:
        if self._schema is None:
            self.load()

    def _resolve_mode(self) -> str:
        if self._mode:
            return self._mode
        if self._kind == "drf":
            self._mode = "drf"
        elif self._kind == "ninja":
            self._mode = "ninja"
        else:
            # drf-spectacular wins when it is importable and DRF is an installed app;
            # a project that only has the packages lying around (ninja-only) falls through.
            from django.apps import apps

            try:
                import drf_spectacular  # noqa: F401

                use_drf = apps.is_installed("rest_framework")
            except ImportError:
                use_drf = False
            self._mode = "drf" if use_drf else "ninja"
        return self._mode

    # -- drf-spectacular --------------------------------------------------------

    def _load_drf(self) -> dict:
        try:
            from drf_spectacular.generators import SchemaGenerator
        except ImportError as exc:
            raise LoaderError(
                "drf-spectacular is not installed. Install it (pip install 'api-contract[django]') "
                "or point at a django-ninja API with 'django:ninja:pkg.module:api'."
            ) from exc
        generator = SchemaGenerator()
        schema = generator.get_schema(request=None, public=True)
        self._generator = generator
        self._schema = dict(schema)
        return self._schema

    def _drf_components(self) -> dict[str, type]:
        """Component name -> serializer class, from the generator's registry."""
        out: dict[str, type] = {}
        registry = getattr(self._generator, "registry", None)
        for (name, ctype), comp in getattr(registry, "_components", {}).items():
            if ctype != "schemas":
                continue
            obj = comp.object
            cls = obj if inspect.isclass(obj) else type(obj)
            if hasattr(cls, "__module__") and cls.__module__ != "builtins":
                out[name] = cls
        return out

    def _attribute_drf(self, method: str, path: str) -> str | None:
        from drf_spectacular.plumbing import build_mock_request

        gen = self._generator
        gen._initialise_endpoints()
        method = method.upper()
        for ep_path, _regex, ep_method, callback in gen.endpoints:
            if ep_method.upper() != method:
                continue
            view = gen.create_view(callback, ep_method)
            if gen.coerce_path(ep_path, ep_method, view) != path:
                continue
            return self._describe_drf_view(callback, view, ep_method, ep_path, build_mock_request)
        return None

    def _describe_drf_view(
        self, callback: Any, view: Any, method: str, path: str, mock: Any
    ) -> str:
        cls = callback.cls
        action = getattr(view, "action", None) or method.lower()
        handler_name = getattr(callback, "actions", {}).get(method.lower(), action)
        if not hasattr(cls, handler_name):
            handler_name = method.lower()
        loc = _location(getattr(cls, handler_name, None)) or _location(cls)
        text = f"{_dotted(cls)}.{handler_name}{_fmt_loc(loc)}"

        serializer = None
        try:
            view.request = mock(method, path, view, None)
            view.format_kwarg = None
            view.args = ()
            view.kwargs = {}
            if hasattr(view, "get_serializer_class"):
                serializer = view.get_serializer_class()
        except Exception:  # noqa: BLE001
            serializer = None
        if serializer is None:
            try:
                ser = view.schema.get_response_serializers()
                if ser is not None:
                    serializer = ser if inspect.isclass(ser) else type(ser)
            except Exception:  # noqa: BLE001
                serializer = None
        if serializer is not None and inspect.isclass(serializer):
            text += f" · serializer: {_dotted(serializer)}"
        return text

    # -- django-ninja -----------------------------------------------------------

    def _load_ninja(self) -> dict:
        api = self._find_ninja_api()
        try:
            self._ninja_prefix = api.get_root_path({})
            schema = api.get_openapi_schema()
        except Exception:  # noqa: BLE001 - API not mounted in the URLconf: no prefix
            self._ninja_prefix = ""
            schema = api.get_openapi_schema(path_prefix="")
        self._ninja_api = api
        self._schema = dict(schema)
        return self._schema

    def _find_ninja_api(self) -> Any:
        if self._ninja_api is not None:
            return self._ninja_api
        if self._ninja_ref:
            try:
                api = import_string(self._ninja_ref)
            except Exception as exc:  # noqa: BLE001
                raise LoaderError(f"Cannot import NinjaAPI {self._ninja_ref!r}: {exc}") from exc
            if not hasattr(api, "get_openapi_schema"):
                raise LoaderError(f"{self._ninja_ref!r} is not a NinjaAPI instance.")
            return api
        try:
            import ninja  # noqa: F401
        except ImportError as exc:
            raise LoaderError(
                "Neither drf-spectacular nor django-ninja is installed. "
                "Install one (pip install 'api-contract[django]' or 'api-contract[ninja]'), "
                "or set the source to 'django:ninja:pkg.module:api'."
            ) from exc
        apis = self._discover_ninja_apis()
        if len(apis) == 1:
            return apis[0]
        if not apis:
            raise LoaderError(
                "No NinjaAPI found in the URL patterns. Set the source explicitly, "
                "e.g. 'django:ninja:myproject.api:api'."
            )
        raise LoaderError(
            f"Found {len(apis)} NinjaAPI instances in the URL patterns; pick one with "
            "'django:ninja:pkg.module:api'."
        )

    @staticmethod
    def _discover_ninja_apis() -> list[Any]:
        from django.urls import URLPattern, URLResolver, get_resolver

        found: list[Any] = []

        def walk(patterns: Any) -> None:
            for p in patterns:
                if isinstance(p, URLResolver):
                    walk(p.url_patterns)
                elif isinstance(p, URLPattern):
                    # Ninja mounts partial(openapi_json/openapi_view/default_home, api=api).
                    api = (getattr(p.callback, "keywords", None) or {}).get("api")
                    if hasattr(api, "get_openapi_schema") and not any(api is f for f in found):
                        found.append(api)

        walk(get_resolver().url_patterns)
        return found

    def _ninja_operation(self, method: str, path: str) -> Any:
        import re

        from ninja.utils import normalize_path

        api = self._ninja_api
        if hasattr(api, "_get_bound_routers"):
            routers = [(b.prefix, b.path_operations) for b in api._get_bound_routers()]
        else:  # django-ninja < 1.4 keeps (prefix, router) pairs
            routers = [(prefix, r.path_operations) for prefix, r in api._routers]
        for prefix, operations in routers:
            for p, path_view in operations.items():
                full = "/".join(i for i in (prefix, p) if i)
                full = normalize_path("/" + self._ninja_prefix + full)
                full = re.sub(r"{[^}:]+:", "{", full)
                if full != path:
                    continue
                for op in path_view.operations:
                    if method.upper() in (m.upper() for m in op.methods):
                        return op
        return None

    def _attribute_ninja(self, method: str, path: str) -> str | None:
        op = self._ninja_operation(method, path)
        if op is None:
            return None
        fn = op.view_func
        return f"{fn.__module__}.{fn.__qualname__}{_fmt_loc(_location(fn))}"

    def _ninja_schema_class(self, name: str) -> type | None:
        try:
            from ninja import Schema
        except ImportError:
            return None
        matches: list[type] = []
        stack = [Schema]
        while stack:
            for sub in stack.pop().__subclasses__():
                stack.append(sub)
                if sub.__name__ == name:
                    matches.append(sub)
        return matches[0] if len(matches) == 1 else None
