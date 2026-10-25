"""Tiny APIFlask orders app."""

from __future__ import annotations

from apiflask import APIFlask, Schema
from apiflask.fields import Float, Integer, String


def create_app(remove_total: bool = False, require_note: bool = False) -> APIFlask:
    app = APIFlask(__name__, title="Orders", version="1.0")

    class OrderOut(Schema):
        id = Integer()
        status = String()
        if not remove_total:
            total = Float()

    class OrderIn(Schema):
        sku = String(required=True)
        note = String(required=require_note)

    @app.get("/orders")
    @app.output(OrderOut(many=True))
    def list_orders():
        return []

    @app.get("/orders/<int:order_id>")
    @app.output(OrderOut)
    def get_order(order_id):
        return {"id": order_id, "status": "new", "total": 1.0}

    @app.post("/orders")
    @app.input(OrderIn)
    @app.output(OrderOut, status_code=201)
    def create_order(json_data):
        return {"id": 1, "status": "new", "total": 1.0}

    return app


def create_changed_app() -> APIFlask:
    return create_app(remove_total=True)
