from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

APPS = Path(__file__).parent / "apps"
sys.path.insert(0, str(APPS))

from api_contract.loaders.base import LoaderError  # noqa: E402
from api_contract.loaders.fastapi import FastAPILoader  # noqa: E402


def def_line(file: str, name: str) -> int:
    for i, text in enumerate((APPS / file).read_text().splitlines(), 1):
        if text.lstrip().startswith(f"def {name}("):
            return i
    raise AssertionError(name)


def test_load_returns_orders_paths():
    spec = FastAPILoader("fastapi_app:create_app").load()
    assert spec["openapi"].startswith("3.")
    assert set(spec["paths"]) == {"/orders", "/orders/{order_id}"}
    assert "total" in spec["components"]["schemas"]["Order"]["properties"]


def test_accepts_app_instance_and_factory(monkeypatch):
    import fastapi_app

    monkeypatch.setattr(fastapi_app, "instance", fastapi_app.create_app(), raising=False)
    assert FastAPILoader("fastapi_app:instance").load()["paths"]
    assert FastAPILoader("fastapi_app:create_changed_app").load()["paths"]


def test_attribute_points_at_handler(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    loader = FastAPILoader("fastapi_app:create_app")
    line = def_line("fastapi_app.py", "get_order")
    assert loader.attribute("GET", "/orders/{order_id}") == (
        f"fastapi_app.get_order (tests/apps/fastapi_app.py:{line})"
    )
    assert "create_order" in loader.attribute("POST", "/orders")
    assert loader.attribute("DELETE", "/orders") is None
    assert loader.attribute("GET", "/nope") is None


def test_attribute_schema(monkeypatch):
    monkeypatch.chdir(Path(__file__).parent.parent)
    loader = FastAPILoader("fastapi_app:create_app")
    assert loader.attribute_schema("Order-Output").startswith(
        "fastapi_app.Order (tests/apps/fastapi_app.py:"
    )
    assert loader.attribute_schema("Missing") is None


def test_not_a_fastapi_app_raises():
    with pytest.raises(LoaderError, match="not a FastAPI app"):
        FastAPILoader("os:sep").load()


def run_cli(*argv: str) -> int:
    from api_contract import cli

    return cli.main(list(argv))


def test_end_to_end_breaking_change_is_attributed(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    base, changed = "fastapi:fastapi_app:create_app", "fastapi:fastapi_app:create_changed_app"
    assert run_cli("snapshot", "--source", base) == 0

    assert run_cli("check", "--source", base) == 0
    capsys.readouterr()

    assert run_cli("check", "--source", changed) == 1
    out = capsys.readouterr().out
    assert "total" in out
    assert "fastapi_app.Order" in out  # attributed to the response model


def test_end_to_end_new_required_request_field(tmp_path, monkeypatch, capsys):
    import fastapi_app

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        fastapi_app, "stricter", lambda: fastapi_app.create_app(require_note=True), raising=False
    )
    assert run_cli("snapshot", "--source", "fastapi:fastapi_app:create_app") == 0
    assert run_cli("check", "--source", "fastapi:fastapi_app:stricter") == 1
    assert "note" in capsys.readouterr().out


def test_mounted_sub_apps_are_merged():
    spec = FastAPILoader("fastapi_mounted_app:create_app").load()
    assert set(spec["paths"]) == {"/orders", "/v1/orders/{order_id}", "/v1/admin/stats"}
    schemas = spec["components"]["schemas"]
    # The parent's Order and the admin app's identical Order share one component;
    # v1's different Order is renamed and its $ref follows.
    assert {"Order", "Order__v1"} <= set(schemas)
    assert "currency" in schemas["Order__v1"]["properties"]
    assert "currency" not in schemas["Order"]["properties"]
    ref = spec["paths"]["/v1/orders/{order_id}"]["get"]["responses"]["200"]["content"]
    assert ref["application/json"]["schema"]["$ref"] == "#/components/schemas/Order__v1"
    stats = spec["paths"]["/v1/admin/stats"]["get"]["responses"]["200"]["content"]
    assert stats["application/json"]["schema"]["$ref"] == "#/components/schemas/Order"


def test_mounted_sub_app_changes_are_found_and_attributed():
    from api_contract import diff

    old = FastAPILoader("fastapi_mounted_app:create_app").load()
    loader = FastAPILoader("fastapi_mounted_app:create_changed_app")
    changes = diff(old, loader.load(), loader=loader)
    [change] = [c for c in changes if c.kind == "type-changed"]
    assert change.path == "/v1/orders/{}"
    assert "get_v1_order" in loader.attribute("GET", "/v1/orders/{order_id}")
    assert "stats" in loader.attribute("GET", "/v1/admin/stats")
    assert "Order" in (loader.attribute_schema("Order__v1") or "")
