import os

from rest_framework import serializers

from .models import Order

# Test switch: API_CONTRACT_TEST_REMOVE_TOTAL=1 drops `total` from the contract.
_FIELDS = (
    ["id", "status", "note"]
    if os.environ.get("API_CONTRACT_TEST_REMOVE_TOTAL")
    else [
        "id",
        "status",
        "total",
        "note",
    ]
)


class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = _FIELDS
