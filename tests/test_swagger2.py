"""Swagger 2.0 -> OpenAPI 3.0.3 conversion."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from api_contract import ApiContractError, diff
from api_contract.normalize import normalize
from api_contract.swagger2 import convert_swagger2


def swagger(**extra: Any) -> dict[str, Any]:
    doc: dict[str, Any] = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "paths": {},
    }
    doc.update(extra)
    return doc


def op_of(doc: dict[str, Any], path: str = "/x", method: str = "post") -> dict[str, Any]:
    return convert_swagger2(doc)["paths"][path][method]


def with_op(operation: dict[str, Any], **extra: Any) -> dict[str, Any]:
    operation.setdefault("responses", {"200": {"description": "ok"}})
    return swagger(paths={"/x": {"post": operation}}, **extra)


def test_top_level_shape() -> None:
    doc = swagger(
        host="api.example.com",
        schemes=["https"],
        basePath="/",
        consumes=["application/json"],
        produces=["application/json"],
        tags=[{"name": "pets"}],
        security=[{"k": []}],
    )
    out = convert_swagger2(doc)
    assert out["openapi"] == "3.0.3"
    assert out["info"] == {"title": "t", "version": "1"}
    assert out["tags"] == [{"name": "pets"}]
    assert out["security"] == [{"k": []}]
    assert out["servers"] == [{"url": "https://api.example.com"}]
    for dropped in ("swagger", "host", "schemes", "basePath", "consumes", "produces"):
        assert dropped not in out


@pytest.mark.parametrize("version", ["3.0.0", "1.2", None])
def test_non_2_0_raises(version: Any) -> None:
    doc = swagger()
    if version is None:
        del doc["swagger"]
        doc["openapi"] = "3.0.3"
    else:
        doc["swagger"] = version
    with pytest.raises(ApiContractError):
        convert_swagger2(doc)


def test_definitions_and_refs_are_moved_everywhere() -> None:
    doc = swagger(
        definitions={
            "Pet": {"type": "object", "properties": {"owner": {"$ref": "#/definitions/Owner"}}},
            "Owner": {"type": "object"},
        },
        parameters={"Limit": {"name": "limit", "in": "query", "type": "integer"}},
        responses={"NotFound": {"description": "nope", "schema": {"$ref": "#/definitions/Pet"}}},
        paths={
            "/x": {
                "parameters": [{"$ref": "#/parameters/Limit"}],
                "get": {
                    "parameters": [{"$ref": "#/parameters/Limit"}],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "schema": {
                                "type": "array",
                                "items": {"$ref": "#/definitions/Pet"},
                            },
                        },
                        "404": {"$ref": "#/responses/NotFound"},
                    },
                },
            }
        },
    )
    out = convert_swagger2(doc)
    assert set(out["components"]["schemas"]) == {"Pet", "Owner"}
    owner = out["components"]["schemas"]["Pet"]["properties"]["owner"]
    assert owner == {"$ref": "#/components/schemas/Owner"}
    assert "definitions" not in out and "parameters" not in out
    assert out["components"]["parameters"]["Limit"]["schema"] == {"type": "integer"}
    shared = out["paths"]["/x"]
    assert shared["parameters"] == [{"$ref": "#/components/parameters/Limit"}]
    assert shared["get"]["parameters"] == [{"$ref": "#/components/parameters/Limit"}]
    ok = shared["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert ok["items"] == {"$ref": "#/components/schemas/Pet"}
    assert shared["get"]["responses"]["404"] == {"$ref": "#/components/responses/NotFound"}
    not_found = out["components"]["responses"]["NotFound"]
    assert not_found["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/Pet"
    }


def test_base_path_is_prefixed_onto_paths() -> None:
    doc = swagger(
        basePath="/v1/",
        paths={"/pets": {"get": {"responses": {}}}, "/": {"get": {"responses": {}}}},
    )
    assert set(convert_swagger2(doc)["paths"]) == {"/v1/pets", "/v1/"}


def test_root_base_path_leaves_paths_alone() -> None:
    doc = swagger(basePath="/", paths={"/pets": {}})
    assert set(convert_swagger2(doc)["paths"]) == {"/pets"}


def test_body_parameter_becomes_request_body() -> None:
    doc = with_op(
        {
            "parameters": [
                {
                    "name": "body",
                    "in": "body",
                    "required": True,
                    "schema": {"$ref": "#/definitions/Pet"},
                }
            ]
        }
    )
    op = op_of(doc)
    assert "parameters" not in op
    assert op["requestBody"] == {
        "required": True,
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Pet"}}},
    }


def test_body_media_types_prefer_operation_consumes_over_global() -> None:
    body = {"name": "b", "in": "body", "schema": {"type": "string"}}
    doc = with_op({"consumes": ["text/plain"], "parameters": [body]}, consumes=["application/xml"])
    assert set(op_of(doc)["requestBody"]["content"]) == {"text/plain"}
    doc = with_op({"parameters": [body]}, consumes=["application/xml", "application/json"])
    body_out = op_of(doc)["requestBody"]
    assert set(body_out["content"]) == {"application/xml", "application/json"}
    assert body_out["required"] is False


def test_form_data_becomes_urlencoded_object() -> None:
    doc = with_op(
        {
            "parameters": [
                {"name": "a", "in": "formData", "type": "string", "required": True},
                {"name": "b", "in": "formData", "type": "integer", "format": "int32"},
            ]
        }
    )
    body = op_of(doc)["requestBody"]
    assert body["required"] is True
    assert body["content"] == {
        "application/x-www-form-urlencoded": {
            "schema": {
                "type": "object",
                "properties": {
                    "a": {"type": "string"},
                    "b": {"type": "integer", "format": "int32"},
                },
                "required": ["a"],
            }
        }
    }


def test_form_data_file_makes_multipart_binary() -> None:
    doc = with_op(
        {
            "parameters": [
                {"name": "f", "in": "formData", "type": "file"},
                {"name": "n", "in": "formData", "type": "string"},
            ]
        }
    )
    body = op_of(doc)["requestBody"]
    assert list(body["content"]) == ["multipart/form-data"]
    props = body["content"]["multipart/form-data"]["schema"]["properties"]
    assert props["f"] == {"type": "string", "format": "binary"}
    assert body["required"] is False


def test_form_data_follows_multipart_consumes() -> None:
    doc = with_op(
        {
            "consumes": ["multipart/form-data"],
            "parameters": [{"name": "n", "in": "formData", "type": "string"}],
        }
    )
    assert list(op_of(doc)["requestBody"]["content"]) == ["multipart/form-data"]


def test_referenced_body_and_form_parameters_are_inlined() -> None:
    doc = swagger(
        parameters={
            "PetBody": {
                "name": "pet",
                "in": "body",
                "required": True,
                "schema": {"type": "object"},
            },
            "Upload": {"name": "file", "in": "formData", "type": "file", "required": True},
        },
        paths={
            "/x": {
                "post": {
                    "parameters": [{"$ref": "#/parameters/PetBody"}],
                    "responses": {},
                },
                "put": {
                    "parameters": [{"$ref": "#/parameters/Upload"}],
                    "responses": {},
                },
            }
        },
    )
    out = convert_swagger2(doc)
    post = out["paths"]["/x"]["post"]
    assert "parameters" not in post
    assert post["requestBody"]["required"] is True
    assert "application/json" in post["requestBody"]["content"]
    put = out["paths"]["/x"]["put"]
    assert "multipart/form-data" in put["requestBody"]["content"]
    assert "parameters" not in out.get("components", {})


def test_path_level_body_applies_to_operations() -> None:
    doc = swagger(
        paths={
            "/x": {
                "parameters": [{"name": "b", "in": "body", "schema": {"type": "string"}}],
                "post": {"responses": {}},
                "put": {
                    "parameters": [{"name": "b", "in": "body", "schema": {"type": "integer"}}],
                    "responses": {},
                },
            }
        }
    )
    item = convert_swagger2(doc)["paths"]["/x"]
    assert "parameters" not in item
    post_schema = item["post"]["requestBody"]["content"]["application/json"]["schema"]
    put_schema = item["put"]["requestBody"]["content"]["application/json"]["schema"]
    assert post_schema == {"type": "string"}
    assert put_schema == {"type": "integer"}


def test_plain_parameters_get_a_schema() -> None:
    doc = with_op(
        {
            "parameters": [
                {
                    "name": "id",
                    "in": "path",
                    "type": "integer",
                    "format": "int64",
                    "minimum": 1,
                    "description": "the id",
                },
                {
                    "name": "q",
                    "in": "query",
                    "type": "string",
                    "required": True,
                    "enum": ["a", "b"],
                    "default": "a",
                    "minLength": 1,
                    "maxLength": 5,
                    "pattern": "^[ab]$",
                    "deprecated": True,
                },
            ]
        }
    )
    id_param, q_param = op_of(doc)["parameters"]
    assert id_param == {
        "name": "id",
        "in": "path",
        "required": True,
        "description": "the id",
        "schema": {"type": "integer", "format": "int64", "minimum": 1},
    }
    assert q_param["schema"] == {
        "type": "string",
        "enum": ["a", "b"],
        "default": "a",
        "minLength": 1,
        "maxLength": 5,
        "pattern": "^[ab]$",
    }
    assert q_param["required"] is True and q_param["deprecated"] is True
    for key in ("type", "enum", "minLength"):
        assert key not in q_param


@pytest.mark.parametrize(
    ("location", "fmt", "style", "explode"),
    [
        ("query", "csv", "form", False),
        ("query", None, "form", False),
        ("query", "multi", "form", True),
        ("query", "ssv", "spaceDelimited", False),
        ("query", "pipes", "pipeDelimited", False),
        ("path", "csv", "simple", False),
        ("header", "csv", "simple", False),
    ],
)
def test_collection_format(location: str, fmt: str | None, style: str, explode: bool) -> None:
    param: dict[str, Any] = {
        "name": "p",
        "in": location,
        "type": "array",
        "items": {"type": "string", "enum": ["x"]},
        "required": True,
    }
    if fmt:
        param["collectionFormat"] = fmt
    out = op_of(with_op({"parameters": [param]}))["parameters"][0]
    assert out["style"] == style
    assert out["explode"] is explode
    assert out["schema"] == {"type": "array", "items": {"type": "string", "enum": ["x"]}}
    assert "collectionFormat" not in out


def test_path_level_parameters_are_converted() -> None:
    doc = swagger(
        paths={
            "/x/{id}": {
                "parameters": [{"name": "id", "in": "path", "type": "string"}],
                "get": {"responses": {}},
            }
        }
    )
    item = convert_swagger2(doc)["paths"]["/x/{id}"]
    assert item["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]


def test_responses_use_produces_and_headers() -> None:
    doc = with_op(
        {
            "produces": ["application/xml", "text/plain"],
            "responses": {
                "200": {
                    "description": "ok",
                    "schema": {"type": "string"},
                    "headers": {
                        "X-Rate": {"type": "integer", "description": "left"},
                        "X-Tags": {"type": "array", "items": {"type": "string"}},
                    },
                },
                "204": {"description": "empty"},
                "default": {"description": "err", "schema": {"type": "object"}},
            },
        },
        produces=["application/json"],
    )
    responses = op_of(doc)["responses"]
    assert set(responses["200"]["content"]) == {"application/xml", "text/plain"}
    assert responses["200"]["description"] == "ok"
    assert responses["200"]["headers"] == {
        "X-Rate": {"description": "left", "schema": {"type": "integer"}},
        "X-Tags": {"schema": {"type": "array", "items": {"type": "string"}}},
    }
    assert responses["204"] == {"description": "empty"}
    assert set(responses["default"]["content"]) == {"application/xml", "text/plain"}


def test_responses_fall_back_to_global_produces_then_json() -> None:
    schema_resp = {"200": {"description": "ok", "schema": {"type": "string"}}}
    doc = with_op({"responses": schema_resp}, produces=["text/csv"])
    assert set(op_of(doc)["responses"]["200"]["content"]) == {"text/csv"}
    doc = with_op({"responses": schema_resp})
    assert set(op_of(doc)["responses"]["200"]["content"]) == {"application/json"}


def test_security_definitions() -> None:
    doc = swagger(
        securityDefinitions={
            "b": {"type": "basic"},
            "k": {"type": "apiKey", "name": "X-Key", "in": "header"},
            "imp": {
                "type": "oauth2",
                "flow": "implicit",
                "authorizationUrl": "https://a/auth",
                "scopes": {"read": "r"},
            },
            "pw": {"type": "oauth2", "flow": "password", "tokenUrl": "https://a/t", "scopes": {}},
            "app": {"type": "oauth2", "flow": "application", "tokenUrl": "https://a/t"},
            "code": {
                "type": "oauth2",
                "flow": "accessCode",
                "authorizationUrl": "https://a/auth",
                "tokenUrl": "https://a/t",
                "scopes": {"w": "w"},
            },
        },
        security=[{"k": []}],
        paths={"/x": {"get": {"security": [{"imp": ["read"]}], "responses": {}}}},
    )
    out = convert_swagger2(doc)
    schemes = out["components"]["securitySchemes"]
    assert schemes["b"] == {"type": "http", "scheme": "basic"}
    assert schemes["k"] == {"type": "apiKey", "name": "X-Key", "in": "header"}
    assert schemes["imp"]["flows"] == {
        "implicit": {"authorizationUrl": "https://a/auth", "scopes": {"read": "r"}}
    }
    assert schemes["pw"]["flows"] == {"password": {"tokenUrl": "https://a/t", "scopes": {}}}
    assert schemes["app"]["flows"] == {
        "clientCredentials": {"tokenUrl": "https://a/t", "scopes": {}}
    }
    assert schemes["code"]["flows"] == {
        "authorizationCode": {
            "authorizationUrl": "https://a/auth",
            "tokenUrl": "https://a/t",
            "scopes": {"w": "w"},
        }
    }
    assert out["security"] == [{"k": []}]
    assert out["paths"]["/x"]["get"]["security"] == [{"imp": ["read"]}]


def test_schema_keyword_rewrites() -> None:
    doc = swagger(
        definitions={
            "Pet": {
                "type": "object",
                "discriminator": "kind",
                "properties": {
                    "kind": {"type": "string"},
                    "nick": {"type": "string", "x-nullable": True},
                    "photo": {"type": "file"},
                    "tags": {"type": "array", "items": {"type": "string", "x-nullable": True}},
                    "type": {"type": "string"},
                },
                "allOf": [{"type": "object", "properties": {"n": {"type": "string"}}}],
            }
        }
    )
    pet = convert_swagger2(doc)["components"]["schemas"]["Pet"]
    props = pet["properties"]
    assert pet["discriminator"] == {"propertyName": "kind"}
    assert props["nick"] == {"type": "string", "nullable": True}
    assert props["photo"] == {"type": "string", "format": "binary"}
    assert props["tags"]["items"] == {"type": "string", "nullable": True}
    assert props["type"] == {"type": "string"}
    assert "x-nullable" not in str(pet)


def test_input_is_not_mutated() -> None:
    doc = swagger(
        basePath="/v1",
        definitions={"P": {"type": "object", "properties": {"f": {"type": "file"}}}},
        parameters={"B": {"name": "b", "in": "body", "schema": {"$ref": "#/definitions/P"}}},
        paths={
            "/x": {
                "post": {
                    "parameters": [
                        {"$ref": "#/parameters/B"},
                        {"name": "q", "in": "query", "type": "array", "items": {"type": "string"}},
                    ],
                    "responses": {
                        "200": {"description": "ok", "schema": {"$ref": "#/definitions/P"}}
                    },
                }
            }
        },
    )
    before = copy.deepcopy(doc)
    convert_swagger2(doc)
    assert doc == before


def test_output_does_not_share_structure_with_input() -> None:
    doc = swagger(definitions={"P": {"type": "object", "enum": [{"a": 1}]}})
    out = convert_swagger2(doc)
    out["components"]["schemas"]["P"]["enum"][0]["a"] = 2
    assert doc["definitions"]["P"]["enum"][0]["a"] == 1


PETSTORE_2: dict[str, Any] = {
    "swagger": "2.0",
    "info": {"title": "Petstore", "version": "1.0"},
    "host": "petstore.example.com",
    "basePath": "/v1",
    "schemes": ["https"],
    "consumes": ["application/json"],
    "produces": ["application/json"],
    "securityDefinitions": {"key": {"type": "apiKey", "name": "X-Api-Key", "in": "header"}},
    "security": [{"key": []}],
    "paths": {
        "/pets": {
            "get": {
                "operationId": "listPets",
                "parameters": [
                    {"name": "limit", "in": "query", "type": "integer", "maximum": 100},
                    {
                        "name": "tag",
                        "in": "query",
                        "type": "array",
                        "items": {"type": "string"},
                        "collectionFormat": "multi",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "pets",
                        "schema": {"type": "array", "items": {"$ref": "#/definitions/Pet"}},
                        "headers": {"X-Next": {"type": "string"}},
                    }
                },
            },
            "post": {
                "parameters": [
                    {
                        "name": "pet",
                        "in": "body",
                        "required": True,
                        "schema": {"$ref": "#/definitions/NewPet"},
                    }
                ],
                "responses": {
                    "201": {"description": "created", "schema": {"$ref": "#/definitions/Pet"}}
                },
            },
        },
        "/pets/{petId}": {
            "parameters": [{"name": "petId", "in": "path", "required": True, "type": "integer"}],
            "get": {
                "responses": {
                    "200": {"description": "pet", "schema": {"$ref": "#/definitions/Pet"}},
                    "404": {"$ref": "#/responses/NotFound"},
                }
            },
            "delete": {"security": [], "responses": {"204": {"description": "gone"}}},
        },
    },
    "definitions": {
        "NewPet": {
            "type": "object",
            "required": ["name"],
            "properties": {
                "name": {"type": "string"},
                "tag": {"type": "string", "x-nullable": True},
            },
        },
        "Pet": {
            "allOf": [
                {"$ref": "#/definitions/NewPet"},
                {"type": "object", "properties": {"id": {"type": "integer", "format": "int64"}}},
            ]
        },
    },
    "responses": {
        "NotFound": {"description": "missing", "schema": {"$ref": "#/definitions/Error"}}
    },
}
PETSTORE_2["definitions"]["Error"] = {
    "type": "object",
    "properties": {"message": {"type": "string"}},
}


def _json(schema: dict[str, Any]) -> dict[str, Any]:
    return {"application/json": {"schema": schema}}


PETSTORE_3: dict[str, Any] = {
    "openapi": "3.0.3",
    "info": {"title": "Petstore", "version": "1.0"},
    "security": [{"key": []}],
    "paths": {
        "/v1/pets": {
            "get": {
                "parameters": [
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "maximum": 100}},
                    {
                        "name": "tag",
                        "in": "query",
                        "style": "form",
                        "explode": True,
                        "schema": {"type": "array", "items": {"type": "string"}},
                    },
                ],
                "responses": {
                    "200": {
                        "description": "pets",
                        "headers": {"X-Next": {"schema": {"type": "string"}}},
                        "content": _json(
                            {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}}
                        ),
                    }
                },
            },
            "post": {
                "requestBody": {
                    "required": True,
                    "content": _json({"$ref": "#/components/schemas/NewPet"}),
                },
                "responses": {
                    "201": {
                        "description": "created",
                        "content": _json({"$ref": "#/components/schemas/Pet"}),
                    }
                },
            },
        },
        "/v1/pets/{petId}": {
            "parameters": [
                {"name": "petId", "in": "path", "required": True, "schema": {"type": "integer"}}
            ],
            "get": {
                "responses": {
                    "200": {
                        "description": "pet",
                        "content": _json({"$ref": "#/components/schemas/Pet"}),
                    },
                    "404": {"$ref": "#/components/responses/NotFound"},
                }
            },
            "delete": {"security": [], "responses": {"204": {"description": "gone"}}},
        },
    },
    "components": {
        "securitySchemes": {"key": {"type": "apiKey", "name": "X-Api-Key", "in": "header"}},
        "responses": {
            "NotFound": {
                "description": "missing",
                "content": _json({"$ref": "#/components/schemas/Error"}),
            }
        },
        "schemas": {
            "NewPet": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "tag": {"type": "string", "nullable": True},
                },
            },
            "Pet": {
                "allOf": [
                    {"$ref": "#/components/schemas/NewPet"},
                    {
                        "type": "object",
                        "properties": {"id": {"type": "integer", "format": "int64"}},
                    },
                ]
            },
            "Error": {"type": "object", "properties": {"message": {"type": "string"}}},
        },
    },
}


def test_petstore_normalizes_like_hand_written_openapi3() -> None:
    converted = normalize(convert_swagger2(PETSTORE_2))
    assert converted == normalize(PETSTORE_3)


def test_response_property_type_change_is_detected() -> None:
    old = copy.deepcopy(PETSTORE_2)
    new = copy.deepcopy(PETSTORE_2)
    new["definitions"]["Pet"]["allOf"][1]["properties"]["id"] = {"type": "string"}
    changes = diff(convert_swagger2(old), convert_swagger2(new))
    assert changes
    assert any("type" in c.kind for c in changes)
    assert {c.severity.value for c in changes} == {"breaking"}


def test_new_required_body_field_and_removed_path_are_detected() -> None:
    old = copy.deepcopy(PETSTORE_2)
    new = copy.deepcopy(PETSTORE_2)
    new["definitions"]["NewPet"]["required"] = ["name", "tag"]
    del new["paths"]["/pets/{petId}"]
    changes = diff(convert_swagger2(old), convert_swagger2(new))
    kinds = {c.kind for c in changes}
    assert any("removed" in k for k in kinds)
    assert any("required" in k for k in kinds)


def test_identical_documents_have_no_changes() -> None:
    assert diff(convert_swagger2(PETSTORE_2), convert_swagger2(copy.deepcopy(PETSTORE_2))) == []


def test_base_path_change_is_a_contract_change() -> None:
    old = copy.deepcopy(PETSTORE_2)
    new = copy.deepcopy(PETSTORE_2)
    new["basePath"] = "/v2"
    assert diff(convert_swagger2(old), convert_swagger2(new))


def test_normalize_accepts_swagger2_directly():
    from api_contract import diff, normalize

    old = {
        "swagger": "2.0",
        "info": {"title": "t", "version": "1"},
        "basePath": "/api",
        "paths": {"/pets": {"get": {"responses": {"200": {"description": "ok"}}}}},
    }
    new = {**old, "paths": {}}
    assert "/api/pets" in normalize(old)["paths"]
    assert [c.kind for c in diff(old, new)] == ["endpoint-removed"]
