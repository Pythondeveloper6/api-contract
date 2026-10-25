"""Tiny flask-smorest orders app (MethodView resources on a Blueprint)."""

from __future__ import annotations

import marshmallow as ma
from flask import Flask
from flask.views import MethodView
from flask_smorest import Api, Blueprint


def create_app(remove_total: bool = False, require_note: bool = False) -> Flask:
    app = Flask(__name__)
    app.config.update(
        API_TITLE="Orders",
        API_VERSION="1.0",
        OPENAPI_VERSION="3.0.3",
    )
    api = Api(app)
    blp = Blueprint("orders", __name__, url_prefix="/orders")

    fields = {"id": ma.fields.Int(), "status": ma.fields.Str()}
    if not remove_total:
        fields["total"] = ma.fields.Float()
    OrderSchema = ma.Schema.from_dict(fields, name="Order")  # noqa: N806

    class OrderInSchema(ma.Schema):
        sku = ma.fields.Str(required=True)
        note = ma.fields.Str(required=require_note)

    @blp.route("/")
    class Orders(MethodView):
        @blp.response(200, OrderSchema(many=True))
        def get(self):
            return []

        @blp.arguments(OrderInSchema)
        @blp.response(201, OrderSchema)
        def post(self, data):
            return {"id": 1, "status": "new", "total": 1.0}

    @blp.route("/<int:order_id>")
    class OrderById(MethodView):
        @blp.response(200, OrderSchema)
        def get(self, order_id):
            return {"id": order_id, "status": "new", "total": 1.0}

    api.register_blueprint(blp)
    return app


def create_changed_app() -> Flask:
    return create_app(remove_total=True)
