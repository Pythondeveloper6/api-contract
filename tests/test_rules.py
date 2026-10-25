import pytest

from api_contract import ApiContractError, Change, Direction, Rules, Severity, diff
from api_contract.model import canonical_id


def test_override_by_exact_kind_and_by_alias():
    rules = Rules({"enum-value-added": "breaking", "request-enum-value-added": "safe"})
    assert rules.severity("response-enum-value-added") is Severity.BREAKING
    assert rules.severity("request-enum-value-added") is Severity.SAFE
    assert rules.severity("endpoint-removed") is Severity.BREAKING


def test_unknown_kind_and_bad_severity_are_errors():
    with pytest.raises(ApiContractError, match="unknown change kind"):
        Rules({"no-such-kind": "safe"})
    with pytest.raises(ApiContractError, match="invalid severity"):
        Rules({"endpoint-added": "fatal"})


def test_rules_feed_through_diff():
    old = {"openapi": "3.0.3", "paths": {"/a": {"get": {"responses": {}}}}}
    new = {"openapi": "3.0.3", "paths": {}}
    [change] = diff(old, new, rules={"endpoint-removed": "safe"})
    assert change.severity is Severity.SAFE


def test_change_id_format():
    change = Change(
        kind="type-changed",
        severity=Severity.BREAKING,
        direction=Direction.RESPONSE,
        method="GET",
        path="/api/orders/{}",
        raw_path="/api/orders/{id}",
        location="response:200:application/json",
        pointer="total",
    )
    assert change.id == "GET /api/orders/{}:response:200:total:type-changed"
    change.location = "response:200:application/xml"
    assert change.id == "GET /api/orders/{}:response:200:application/xml:total:type-changed"
    assert change.endpoint == "GET /api/orders/{id}"


def test_canonical_id_accepts_named_params():
    assert canonical_id("get /a/{id}/b:x") == "GET /a/{}/b:x"


def test_canonical_id_handles_colons_in_the_path():
    raw = "post /v1/{p}/things:cancel/{t}:response:200:a:type-changed"
    assert canonical_id(raw) == "POST /v1/{}/things:cancel/{}:response:200:a:type-changed"
    assert canonical_id("get /v1/{p}/x:cancel:endpoint-removed") == (
        "GET /v1/{}/x:cancel:endpoint-removed"
    )
    assert canonical_id("get /v1/{p}/x:cancel:*") == "GET /v1/{}/x:cancel:*"
