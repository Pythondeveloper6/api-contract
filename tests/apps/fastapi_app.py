"""Tiny FastAPI orders app. ``create_app`` flags build a "changed" variant."""

from fastapi import FastAPI
from pydantic import BaseModel


def create_app(remove_total: bool = False, require_note: bool = False) -> FastAPI:
    app = FastAPI(title="Orders", version="1.0")

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

    @app.get("/orders", response_model=list[Order])
    def list_orders():
        return []

    @app.get("/orders/{order_id}", response_model=Order)
    def get_order(order_id: int):
        return {"id": order_id, "status": "new", "total": 1.0}

    @app.post("/orders", response_model=Order, status_code=201)
    def create_order(body: OrderIn):
        return {"id": 1, "status": "new", "total": 1.0}

    return app


def create_changed_app() -> FastAPI:
    return create_app(remove_total=True)
