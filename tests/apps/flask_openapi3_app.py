"""Tiny flask-openapi3 orders app."""

from flask_openapi3 import Info, OpenAPI
from pydantic import BaseModel


class OrderPath(BaseModel):
    order_id: int


def create_app(remove_total: bool = False, require_note: bool = False) -> OpenAPI:
    app = OpenAPI(__name__, info=Info(title="Orders", version="1.0"))

    class Order(BaseModel):
        id: int
        status: str
        if not remove_total:
            total: float

    class OrderIn(BaseModel):
        sku: str
        if require_note:
            note: str
        else:
            note: str | None = None

    @app.get("/orders", responses={200: Order})
    def list_orders():
        return []

    @app.get("/orders/<int:order_id>", responses={200: Order})
    def get_order(path: OrderPath):
        return {"id": path.order_id, "status": "new", "total": 1.0}

    @app.post("/orders", responses={201: Order})
    def create_order(body: OrderIn):
        return {"id": 1, "status": "new", "total": 1.0}, 201

    return app


def create_changed_app() -> OpenAPI:
    return create_app(remove_total=True)
