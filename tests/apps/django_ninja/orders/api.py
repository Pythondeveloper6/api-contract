import os
from decimal import Decimal

from ninja import NinjaAPI, Schema

api = NinjaAPI(title="Orders", version="1.0.0")


class OrderOut(Schema):
    id: int
    status: str
    note: str = ""
    if not os.environ.get("API_CONTRACT_TEST_REMOVE_TOTAL"):
        total: Decimal


class OrderIn(Schema):
    status: str
    note: str = ""


@api.get("/orders/", response=list[OrderOut])
def list_orders(request):
    return []


@api.get("/orders/{order_id}", response=OrderOut)
def get_order(request, order_id: int):
    raise NotImplementedError


@api.post("/orders/", response=OrderOut)
def create_order(request, payload: OrderIn):
    raise NotImplementedError
