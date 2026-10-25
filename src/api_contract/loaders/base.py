"""The loader contract, and the registry that maps a ``source`` string to a loader.

A *source* is ``"<kind>:<target>"``: ``file:openapi.yaml``,
``fastapi:app.main:app``, ``flask:wsgi:app``, ``django`` (no target),
``django:ninja:proj.api:api``. The kind picks a loader class from
:data:`LOADERS`; the target (everything after the first colon, possibly ``""``)
is passed to its constructor untouched. A source with no known kind is treated
as a file path, so ``openapi.json`` works on its own.

Implementing a loader::

    class MyLoader(BaseLoader):
        def load(self) -> dict:
            app = import_string(self.target)
            return app.openapi()            # raw, un-normalized OpenAPI

        def attribute(self, method, path):  # "GET", "/orders/{id}/" as in the raw spec
            return "orders.views.OrderView (orders/views.py:42)"

Loaders should raise :class:`LoaderError` for anything the user must fix; the
CLI turns it into exit code 2. A missing framework (``ModuleNotFoundError``) is
turned into an ``pip install api-contract[<extra>]`` hint by the registry, at
import time and when ``load()`` runs. ``attribute()`` and
``attribute_schema()`` are best-effort: the core swallows their exceptions,
because attribution must never fail a check.
"""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from typing import Any, Protocol, runtime_checkable

from ..model import ApiContractError


class LoaderError(ApiContractError):
    """A user-facing failure to load a schema (bad target, import error...)."""


@runtime_checkable
class Loader(Protocol):
    def __init__(self, target: str) -> None: ...

    def load(self) -> dict:
        """Return the raw (un-normalized) OpenAPI document."""
        ...

    def attribute(self, method: str, path: str) -> str | None:
        """Name the code behind an operation, e.g. ``orders.views.OrderView (orders/views.py:42)``.

        ``method`` is upper-case; ``path`` is the template from the raw spec,
        with its original parameter names (``/orders/{order_id}/``).
        """
        ...

    def attribute_schema(self, component_name: str) -> str | None:
        """Name the code behind ``#/components/schemas/<component_name>``, if known."""
        ...


def describe_callable(func: Any) -> str | None:
    """Return ``"module.func (relative/file.py:LINE)"`` for ``func``, or None."""
    try:
        func = inspect.unwrap(func)
        file = inspect.getsourcefile(func)
        lines, start = inspect.getsourcelines(func)
    except (TypeError, OSError):
        return None
    if file is None:
        return None
    # Point at the ``def`` line rather than the first decorator.
    line = start
    for offset, text in enumerate(lines):
        if text.lstrip().startswith(("def ", "async def ")):
            line = start + offset
            break
    try:
        rel = os.path.relpath(file)
    except ValueError:  # different drive on Windows
        rel = file
    name = getattr(func, "__qualname__", getattr(func, "__name__", "?")).split("<locals>.")[-1]
    return f"{func.__module__}.{name} ({rel}:{line})"


class BaseLoader:
    """Convenience base: stores ``target`` and attributes nothing."""

    def __init__(self, target: str) -> None:
        self.target = target

    def load(self) -> dict:  # pragma: no cover - abstract
        raise NotImplementedError

    def attribute(self, method: str, path: str) -> str | None:
        return None

    def attribute_schema(self, component_name: str) -> str | None:
        return None

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.target!r})"


# Imported lazily so the core never imports a web framework it doesn't need.
LOADERS: dict[str, str] = {
    "file": "api_contract.loaders.file:FileLoader",
    "fastapi": "api_contract.loaders.fastapi:FastAPILoader",
    "flask": "api_contract.loaders.flask:FlaskLoader",
    "django": "api_contract.loaders.django:DjangoLoader",
}

# kind -> extra name, for the "pip install api-contract[<extra>]" hint.
EXTRAS: dict[str, str] = {"fastapi": "fastapi", "flask": "flask", "django": "django"}


# Missing top-level module -> the extra that installs it. Wins over EXTRAS,
# because one loader kind can need modules from different extras (the django
# loader covers DRF and django-ninja).
MODULE_EXTRAS: dict[str, str] = {
    "drf_spectacular": "django",
    "rest_framework": "django",
    "ninja": "ninja",
    "apiflask": "apiflask",
    "flask_smorest": "smorest",
    "flask_openapi3": "flask-openapi3",
}


def install_hint(kind: str, module: str | None = None) -> str:
    top = (module or "").partition(".")[0]
    extra = MODULE_EXTRAS.get(top) or EXTRAS.get(kind)
    return f"pip install 'api-contract[{extra}]'" if extra else "pip install api-contract"


def missing_dependency(kind: str, exc: ModuleNotFoundError) -> LoaderError:
    """The error to raise when a loader's framework isn't installed."""
    return LoaderError(
        f"the {kind!r} loader needs {exc.name or 'a missing module'!r}, which is not installed. "
        f"Install it with: {install_hint(kind, exc.name)}"
    )


def _ensure_cwd_on_path() -> None:
    # Console scripts don't put the working directory on sys.path, but users
    # expect "app.main:app" to resolve relative to where they run the command.
    cwd = os.getcwd()
    if cwd not in sys.path and "" not in sys.path:
        sys.path.insert(0, cwd)


def import_string(dotted: str) -> Any:
    """Import ``"pkg.mod:attr"`` (or ``"pkg.mod.attr"``); ``attr`` may be dotted.

    The working directory is added to ``sys.path`` first. Failures raise
    ``ImportError`` with a message that names what could not be found.
    """
    _ensure_cwd_on_path()
    if ":" in dotted:
        module_name, _, attr_path = dotted.partition(":")
    else:
        module_name, _, attr_path = dotted.rpartition(".")
    if not module_name or not attr_path:
        raise ImportError(f"{dotted!r} is not an import path like 'package.module:attribute'")
    try:
        obj: Any = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and module_name.startswith(exc.name):
            raise ImportError(
                f"cannot import module {module_name!r} (looked in {os.getcwd()} and sys.path)"
            ) from exc
        raise
    for part in attr_path.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError:
            raise ImportError(f"module {module_name!r} has no attribute {attr_path!r}") from None
    return obj


def parse_source(source: str) -> tuple[str, str]:
    """``"fastapi:app.main:app"`` -> ``("fastapi", "app.main:app")``.

    A source without a known kind is a file: ``"openapi.json"`` -> ``("file", "openapi.json")``.
    """
    source = source.strip()
    kind, sep, target = source.partition(":")
    if kind in LOADERS:
        return kind, target if sep else ""
    return "file", source


def register_loader(kind: str, target: str) -> None:
    """Register a loader class (as ``"module:Class"``) for ``<kind>:...`` sources."""
    LOADERS[kind] = target


def get_loader(source: str) -> Loader:
    """Instantiate the loader for a source string. Raises :class:`LoaderError`."""
    if not source or not source.strip():
        raise LoaderError("no source configured (set [tool.api-contract] source, or pass --source)")
    kind, target = parse_source(source)
    module_name, _, class_name = LOADERS[kind].partition(":")
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name == module_name or (exc.name and module_name.startswith(exc.name + ".")):
            raise LoaderError(
                f"the {kind!r} loader is not available in this install of api-contract "
                f"({module_name} not found). Try: {install_hint(kind)}"
            ) from exc
        raise missing_dependency(kind, exc) from exc
    except ImportError as exc:
        raise LoaderError(f"cannot import the {kind!r} loader: {exc}") from exc
    cls = getattr(module, class_name, None)
    if cls is None:
        raise LoaderError(f"{module_name} has no loader class {class_name!r}")
    try:
        return cls(target)
    except ModuleNotFoundError as exc:
        raise missing_dependency(kind, exc) from exc
