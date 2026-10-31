"""A FastAPI app with mounted sub-apps (one nested) and a static mount."""

from __future__ import annotations

import tempfile

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel


class Order(BaseModel):
    id: int
    total: float


ParentOrder = Order


def create_app(v1_total_type: type = float) -> FastAPI:
    app = FastAPI(title="Shop")

    @app.get("/orders", response_model=list[ParentOrder])
    def list_orders():
        return []

    v1 = FastAPI(title="v1")

    # Same component name as the parent's Order, different schema.
    class Order(BaseModel):  # noqa: F811
        id: int
        total: v1_total_type  # type: ignore[valid-type]
        currency: str

    @v1.get("/orders/{order_id}", response_model=Order)
    def get_v1_order(order_id: int):
        return {"id": order_id, "total": 1, "currency": "EUR"}

    admin = FastAPI(title="admin")

    @admin.get("/stats", response_model=ParentOrder)
    def stats():
        return {"id": 1, "total": 1.0}

    v1.mount("/admin", admin)
    app.mount("/v1/", v1)
    app.mount("/static", StaticFiles(directory=tempfile.gettempdir()), name="static")
    return app


def create_changed_app() -> FastAPI:
    return create_app(v1_total_type=str)
