import json

import pytest

from api_contract import ApiContractError, normalize
from api_contract.normalize import COMPONENT, RAW_PATH, RECURSIVE, REF, dump_snapshot


def spec(paths, schemas=None, **extra):
    doc = {"openapi": "3.0.3", "paths": paths, **extra}
    if schemas:
        doc["components"] = {"schemas": schemas}
    return doc


def response_schema(doc, path="/x", method="get", code="200"):
    op = doc["paths"][path][method]
    return op["responses"][code]["content"]["application/json"]["schema"]


def ok(schema):
    return {"200": {"description": "OK", "content": {"application/json": {"schema": schema}}}}


def test_property_named_like_a_docs_key_survives():
    doc = normalize(
        spec(
            {
                "/x": {
                    "get": {
                        "responses": ok(
                            {
                                "type": "object",
                                "properties": {
                                    "description": {
                                        "type": "string",
                                        "description": "the description",
                                    },
                                    "title": {"type": "string"},
                                },
                            }
                        )
                    }
                }
            }
        )
    )
    props = response_schema(doc)["properties"]
    assert props == {"description": {"type": "string"}, "title": {"type": "string"}}


def test_example_data_is_not_walked_or_stripped():
    doc = normalize(
        spec(
            {
                "/x": {
                    "get": {"responses": ok({"type": "object", "default": {"description": "kept"}})}
                }
            }
        )
    )
    assert response_schema(doc)["default"] == {"description": "kept"}


def test_recursive_schema_terminates_with_cycle_marker():
    schemas = {
        "A": {"type": "object", "properties": {"b": {"$ref": "#/components/schemas/B"}}},
        "B": {"type": "object", "properties": {"a": {"$ref": "#/components/schemas/A"}}},
    }
    doc = normalize(
        spec({"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/A"})}}}, schemas)
    )
    # Recursive components are stored once; every use is a marker (the cycle point).
    assert response_schema(doc) == {REF: "A"}
    a, b = doc[RECURSIVE]["A"], doc[RECURSIVE]["B"]
    assert a[COMPONENT] == "A"
    assert a["properties"]["b"] == {REF: "B"}
    assert b["properties"]["a"] == {REF: "A"}


def test_self_reference_through_array():
    schemas = {"N": {"type": "array", "items": {"$ref": "#/components/schemas/N"}}}
    doc = normalize(
        spec({"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/N"})}}}, schemas)
    )
    assert doc[RECURSIVE]["N"]["items"] == {REF: "N"}


def test_nullable_forms_are_unified():
    forms = [
        {"type": "string", "nullable": True},
        {"type": ["string", "null"]},
        {"type": ["null", "string"]},
        {"anyOf": [{"type": "string"}, {"type": "null"}]},
        {"oneOf": [{"type": "null"}, {"type": "string"}]},
    ]
    results = {
        json.dumps(response_schema(normalize(spec({"/x": {"get": {"responses": ok(f)}}}))))
        for f in forms
    }
    assert results == {json.dumps({"nullable": True, "type": "string"})}


def test_positional_paths_keep_raw_template():
    doc = normalize(
        spec(
            {
                "/orders/{order_id}/": {
                    "get": {
                        "parameters": [
                            {
                                "in": "path",
                                "name": "order_id",
                                "required": True,
                                "schema": {"type": "integer"},
                            }
                        ],
                        "responses": ok({}),
                    }
                }
            }
        )
    )
    item = doc["paths"]["/orders/{}/"]
    assert item[RAW_PATH] == "/orders/{order_id}/"
    assert "path:0" in item["get"]["parameters"]


def test_parameter_refs_and_path_level_parameters():
    doc = spec(
        {
            "/x": {
                "parameters": [{"$ref": "#/components/parameters/Limit"}],
                "get": {
                    "parameters": [{"in": "query", "name": "limit", "required": True}],
                    "responses": {},
                },
            }
        },
    )
    doc["components"] = {
        "parameters": {"Limit": {"in": "query", "name": "limit", "schema": {"type": "integer"}}}
    }
    params = normalize(doc)["paths"]["/x"]["get"]["parameters"]
    # The operation-level definition overrides the path-level one.
    assert params["query:limit"]["required"] is True


def test_normalize_is_idempotent_and_snapshot_round_trips():
    doc = spec(
        {"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/A"})}}},
        {"A": {"type": "object", "properties": {"me": {"$ref": "#/components/schemas/A"}}}},
    )
    once = normalize(doc)
    assert normalize(once) == once
    assert normalize(json.loads(dump_snapshot(once))) == once


def test_snapshot_is_sorted_pretty_json():
    text = dump_snapshot(
        normalize(spec({"/b": {"get": {"responses": {}}}, "/a": {"get": {"responses": {}}}}))
    )
    assert text.index('"/a"') < text.index('"/b"')
    assert text.endswith("}\n")


def test_ignore_keys_is_configurable():
    doc = spec(
        {"/x": {"get": {"responses": ok({"type": "string", "x-flag": 1, "description": "d"})}}}
    )
    kept = response_schema(normalize(doc, ignore_keys=["description"]))
    assert kept == {"type": "string", "x-flag": 1}


def test_external_and_missing_refs():
    doc = spec({"/x": {"get": {"responses": ok({"$ref": "other.yaml#/Foo"})}}})
    assert response_schema(normalize(doc)) == {"x-api-contract-external-ref": "other.yaml#/Foo"}
    with pytest.raises(ApiContractError, match="unresolvable"):
        normalize(spec({"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/Nope"})}}}))


def test_converts_swagger_2_and_rejects_older_versions():
    assert normalize({"swagger": "2.0", "paths": {}})["paths"] == {}
    with pytest.raises(ApiContractError, match="2.0"):
        normalize({"swagger": "1.2", "paths": {}})


def test_changed_external_ref_is_reported():
    from api_contract import diff

    def doc(ref):
        return spec({"/x": {"get": {"responses": ok({"$ref": ref})}}})

    [change] = diff(doc("a.yaml#/A"), doc("b.yaml#/B"))
    assert change.kind == "schema-changed"
    assert diff(doc("a.yaml#/A"), doc("a.yaml#/A")) == []


def test_mutual_recursion_does_not_blow_up():
    import time

    names = [f"S{i}" for i in range(30)]
    props = {b.lower(): {"$ref": f"#/components/schemas/{b}"} for b in names}
    schemas = {a: {"type": "object", "properties": props} for a in names}
    started = time.perf_counter()
    doc = normalize(
        spec({"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/S0"})}}}, schemas)
    )
    assert time.perf_counter() - started < 2
    assert set(doc[RECURSIVE]) == set(names)


def test_non_recursive_components_are_still_inlined():
    node = {
        "type": "object",
        "properties": {
            "leaf": {"$ref": "#/components/schemas/Leaf"},
            "next": {"$ref": "#/components/schemas/Node"},
        },
    }
    schemas = {"Leaf": {"type": "string"}, "Node": node}
    doc = normalize(
        spec({"/x": {"get": {"responses": ok({"$ref": "#/components/schemas/Node"})}}}, schemas)
    )
    assert set(doc[RECURSIVE]) == {"Node"}
    assert doc[RECURSIVE]["Node"]["properties"]["leaf"]["type"] == "string"


def test_integer_yaml_keys_become_strings():
    # YAML reads `200:` as an int; mixing it with string keys must not break sorting.
    import yaml

    doc = yaml.safe_load(
        """
openapi: 3.0.3
paths:
  /x:
    get:
      responses:
        200:
          description: ok
          content:
            application/json:
              schema:
                type: object
                properties:
                  200: {type: string}
                  name: {type: string}
        "404": {description: nf}
"""
    )
    out = normalize(doc)
    assert set(out["paths"]["/x"]["get"]["responses"]) == {"200", "404"}
    assert list(response_schema(out)["properties"]) == ["200", "name"]
    # JSON (which always has string keys) gives the same result.
    assert normalize(json.loads(json.dumps(doc))) == out
