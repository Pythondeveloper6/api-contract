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
        LoaderError, match=r"APIFlask.*flask-smorest.*flask-openapi3.*file:module:callable"
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
