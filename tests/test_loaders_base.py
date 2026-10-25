import json
import sys

import pytest

from api_contract import BaseLoader, LoaderError, diff, get_loader, load_spec
from api_contract.core import attribute
from api_contract.loaders import base
from api_contract.loaders.base import import_string, parse_source
from api_contract.loaders.file import FileLoader

SPEC = {"openapi": "3.0.3", "paths": {"/a/{id}": {"get": {"responses": {}}}}}


def test_parse_source():
    assert parse_source("fastapi:app.main:app") == ("fastapi", "app.main:app")
    assert parse_source("django") == ("django", "")
    assert parse_source("django:ninja:proj.api:api") == ("django", "ninja:proj.api:api")
    assert parse_source("openapi.json") == ("file", "openapi.json")
    assert parse_source("file:openapi.json") == ("file", "openapi.json")


def test_file_loader_json_yaml_and_callable(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "spec.json").write_text(json.dumps(SPEC))
    (tmp_path / "spec.yaml").write_text("openapi: 3.0.3\npaths: {}\n")
    (tmp_path / "make_spec.py").write_text(f"SPEC = {SPEC!r}\ndef build():\n    return SPEC\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    assert load_spec("file:spec.json") == SPEC
    assert load_spec("spec.yaml")["paths"] == {}
    assert load_spec("file:make_spec:build") == SPEC
    assert load_spec("file:make_spec:SPEC") == SPEC
    assert isinstance(get_loader("file:spec.json"), FileLoader)


@pytest.mark.parametrize(
    "target, message",
    [
        ("missing.json", "not found"),
        ("no_such_module_xyz:build", "cannot import module"),
        ("json:nope", "has no attribute"),
        ("os:getcwd", "did not produce a dict"),
        ("", "needs a path"),
    ],
)
def test_file_loader_errors(target, message, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(LoaderError, match=message):
        FileLoader(target).load()


def test_invalid_file_contents(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    with pytest.raises(LoaderError, match="not valid JSON"):
        FileLoader(str(bad)).load()
    listy = tmp_path / "list.yaml"
    listy.write_text("- 1\n")
    with pytest.raises(LoaderError, match="expected a mapping"):
        FileLoader(str(listy)).load()


def test_import_string_forms():
    assert import_string("json:dumps") is json.dumps
    assert import_string("json.dumps") is json.dumps
    assert import_string("os:path.join") is __import__("os").path.join
    with pytest.raises(ImportError, match="import path"):
        import_string("nodots")


def test_missing_loader_module_and_missing_framework(tmp_path, monkeypatch):
    monkeypatch.setitem(base.LOADERS, "ghost", "api_contract.loaders.ghost:GhostLoader")
    monkeypatch.setitem(base.EXTRAS, "ghost", "ghost")
    with pytest.raises(LoaderError, match=r"not available.*api-contract\[ghost\]"):
        get_loader("ghost:app")

    (tmp_path / "needs_framework.py").write_text(
        "import framework_that_is_not_installed\nclass L: pass\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(base.LOADERS, "ghost", "needs_framework:L")
    with pytest.raises(
        LoaderError, match=r"framework_that_is_not_installed.*api-contract\[ghost\]"
    ):
        get_loader("ghost:app")
    sys.modules.pop("needs_framework", None)


def test_framework_missing_at_load_time(monkeypatch):
    class Lazy(BaseLoader):
        def load(self):
            import framework_that_is_not_installed  # noqa: F401

    monkeypatch.setitem(base.LOADERS, "ghost", f"{__name__}:Lazy")
    monkeypatch.setitem(base.EXTRAS, "ghost", "ghost")
    monkeypatch.setitem(globals(), "Lazy", Lazy)
    with pytest.raises(LoaderError, match=r"api-contract\[ghost\]"):
        load_spec("ghost:x")


def test_unknown_source_without_kind_is_a_file():
    with pytest.raises(LoaderError, match="not found"):
        load_spec("nope.json")


class Attributing(BaseLoader):
    def __init__(self, target=""):
        super().__init__(target)
        self.calls = []

    def load(self):
        return SPEC

    def attribute(self, method, path):
        self.calls.append((method, path))
        if path == "/boom":
            raise RuntimeError("loader bug")
        return f"views.handler for {method} {path}"

    def attribute_schema(self, component_name):
        return f"serializers.{component_name}Serializer" if component_name == "Order" else None


def test_attribution_uses_raw_path_component_and_swallows_errors():
    order = {"type": "object", "properties": {"total": {"type": "number"}}}
    old = {
        "openapi": "3.0.3",
        "paths": {
            "/orders/{order_id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Order"}
                                }
                            },
                        }
                    }
                }
            },
            "/boom": {"get": {"responses": {}}},
            "/gone": {"get": {"responses": {}}},
        },
        "components": {"schemas": {"Order": order}},
    }
    new = json.loads(json.dumps(old))
    new["paths"]["/orders/{id}"] = new["paths"].pop("/orders/{order_id}")
    new["components"]["schemas"]["Order"]["properties"]["total"]["type"] = "string"
    new["paths"]["/boom"]["get"]["deprecated"] = True
    del new["paths"]["/gone"]

    loader = Attributing()
    changes = {c.kind: c for c in diff(old, new, loader=loader)}
    assert changes["type-changed"].attribution == "serializers.OrderSerializer"
    assert changes["endpoint-deprecated"].attribution is None  # attribute() raised
    assert changes["endpoint-removed"].attribution is None
    assert ("GET", "/gone") not in loader.calls

    # Without a component attribution, the operation handler is used, with the raw path.
    loader.attribute_schema = lambda name: None
    attribute(list(changes.values()), loader)
    assert changes["type-changed"].attribution == "views.handler for GET /orders/{id}"


@pytest.mark.parametrize(
    ("kind", "module", "extra"),
    [
        ("django", "drf_spectacular", "django"),
        ("django", "rest_framework", "django"),
        ("django", "ninja", "ninja"),
        ("django", "ninja.errors", "ninja"),
        ("django", "django", "django"),
        ("flask", "flask", "flask"),
        ("flask", "apiflask", "apiflask"),
        ("flask", "flask_smorest", "smorest"),
        ("flask", "flask_openapi3", "flask-openapi3"),
    ],
)
def test_install_hint_follows_the_missing_module(kind, module, extra):
    exc = ModuleNotFoundError(f"No module named {module!r}", name=module)
    assert f"api-contract[{extra}]" in str(base.missing_dependency(kind, exc))
