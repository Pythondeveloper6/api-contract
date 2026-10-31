from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

APPS = Path(__file__).parent / "apps"
sys.path.insert(0, str(APPS))

from api_contract.loaders.base import LoaderError  # noqa: E402
from api_contract.loaders.flask import FlaskLoader  # noqa: E402

# module, library to skip on, collection path, handler for GET by id, handler for POST
CASES = [
    ("apiflask_app", "apiflask", "/orders", "get_order", "create_order"),
    ("smorest_app", "flask_smorest", "/orders/", "OrderById.get", "Orders.post"),
    ("flask_openapi3_app", "flask_openapi3", "/orders", "get_order", "create_order"),
]


@pytest.fixture(params=CASES, ids=[c[0] for c in CASES])
def case(request):
    module, lib, *rest = request.param
    pytest.importorskip(lib)
    return module, *rest


def def_line(file: str, name: str) -> int:
    *owner, name = name.split(".")
    seen_owner = not owner
    for i, text in enumerate((APPS / file).read_text().splitlines(), 1):
        if owner and text.lstrip().startswith(f"class {owner[0]}("):
            seen_owner = True
        if seen_owner and text.lstrip().startswith(f"def {name}("):
            return i
    raise AssertionError(name)


def test_load_returns_orders_paths(case):
    module, collection, *_ = case
    spec = FlaskLoader(f"{module}:create_app").load()
    assert spec["openapi"].startswith("3.")
    assert set(spec["paths"]) == {collection, "/orders/{order_id}"}
    schemas = spec["components"]["schemas"].values()
    assert any("total" in s.get("properties", {}) for s in schemas)


def test_attribute_points_at_handler(case, monkeypatch):
    module, collection, by_id, post = case
    monkeypatch.chdir(Path(__file__).parent.parent)
    loader = FlaskLoader(f"{module}:create_app")
    got = loader.attribute("GET", "/orders/{order_id}")
    assert got == f"{module}.{by_id} (tests/apps/{module}.py:{def_line(f'{module}.py', by_id)})"
    got = loader.attribute("post", collection)
    assert got == f"{module}.{post} (tests/apps/{module}.py:{def_line(f'{module}.py', post)})"
    assert loader.attribute("DELETE", collection) is None
    assert loader.attribute("GET", "/nope") is None


def test_no_supported_library_raises(tmp_path, monkeypatch):
    (tmp_path / "plain_flask_app.py").write_text(
        "from flask import Flask\n\ndef create_app():\n    return Flask(__name__)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(
        LoaderError,
        match=r"APIFlask.*flask-smorest.*flask-openapi3.*file:module:callable.*flask-routes:",
    ):
        FlaskLoader("plain_flask_app:create_app").load()


def test_not_a_flask_app_raises():
    with pytest.raises(LoaderError, match="not a Flask app"):
        FlaskLoader("os:sep").load()


def run_cli(*argv: str) -> int:
    from api_contract import cli

    return cli.main(list(argv))


def test_end_to_end_breaking_change_is_attributed(case, tmp_path, monkeypatch, capsys):
    module, *_ = case
    monkeypatch.chdir(tmp_path)
    base, changed = f"flask:{module}:create_app", f"flask:{module}:create_changed_app"
    assert run_cli("snapshot", "--source", base) == 0

    assert run_cli("check", "--source", base) == 0
    capsys.readouterr()

    assert run_cli("check", "--source", changed) == 1
    out = capsys.readouterr().out
    assert "total" in out
    assert f"{module}." in out  # attributed to a handler in the example app


def test_attribute_schema_finds_the_schema_class(case, monkeypatch):
    module, *_ = case
    monkeypatch.chdir(Path(__file__).parent.parent)
    loader = FlaskLoader(f"{module}:create_app")
    loader.load()
    found = loader.attribute_schema("OrderIn")
    assert found is not None and found.startswith(f"{module}.OrderIn")
    assert f"(tests/apps/{module}.py:" in found
    assert loader.attribute_schema("NoSuchComponent") is None


ROUTES_APP = """
from flask import Flask
from flask.views import MethodView


def create_app(with_delete=True):
    app = Flask(__name__)

    @app.get("/items")
    def list_items():
        return []

    @app.route("/items/<int:item_id>", methods=["GET", "PUT"])
    def item(item_id):
        return {}

    @app.get("/files/<path:name>/<uuid:key>/<x>")
    def files(name, key, x):
        return {}

    if with_delete:
        @app.delete("/items/<int:item_id>")
        def delete_item(item_id):
            return "", 204

    return app


def create_smaller_app():
    return create_app(with_delete=False)


app = create_app()
"""


@pytest.fixture
def routes_app(tmp_path, monkeypatch):
    (tmp_path / "routes_app.py").write_text(ROUTES_APP)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    yield
    sys.modules.pop("routes_app", None)


def test_flask_routes_inventory(routes_app):
    from api_contract import get_loader

    loader = get_loader("flask-routes:routes_app:app")
    doc = loader.load()
    assert doc["x-api-contract-inventory"] is True
    assert set(doc["paths"]) == {"/items", "/items/{item_id}", "/files/{name}/{key}/{x}"}
    assert set(doc["paths"]["/items/{item_id}"]) == {"get", "put", "delete"}
    params = doc["paths"]["/files/{name}/{key}/{x}"]["get"]["parameters"]
    assert [p["schema"] for p in params] == [
        {"type": "string"},
        {"type": "string", "format": "uuid"},
        {"type": "string"},
    ]
    assert doc["paths"]["/items/{item_id}"]["get"]["parameters"][0]["schema"] == {"type": "integer"}
    assert not any("static" in p for p in doc["paths"])
    assert loader.attribute("PUT", "/items/{item_id}").startswith("routes_app.item (")


def test_flask_routes_detects_removed_methods(routes_app, capsys):
    assert run_cli("snapshot", "--source", "flask-routes:routes_app:create_app") == 0
    capsys.readouterr()
    assert run_cli("check", "--source", "flask-routes:routes_app:create_smaller_app") == 1
    out = capsys.readouterr().out
    assert "DELETE /items/{item_id}  method removed" in out
