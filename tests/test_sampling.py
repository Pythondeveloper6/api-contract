import json

import pytest
import yaml

from api_contract import ApiContractError
from api_contract.cli import main
from api_contract.normalize import normalize
from api_contract.sampling import Sample, read_samples, verify_samples

ORDER = {
    "type": "object",
    "required": ["id", "total"],
    "additionalProperties": False,
    "properties": {
        "id": {"type": "integer"},
        "total": {"type": "number"},
        "status": {"type": "string", "enum": ["new", "paid"]},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "lines": {"type": "array", "items": {"$ref": "#/components/schemas/Line"}},
    },
}
SPEC = {
    "openapi": "3.1.0",
    "paths": {
        "/orders/{id}": {
            "get": {
                "responses": {
                    "200": {
                        "description": "",
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Order"}}
                        },
                    },
                    "404": {"description": ""},
                }
            }
        }
    },
    "components": {
        "schemas": {
            "Order": ORDER,
            "Line": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Line"}},
                },
            },
        }
    },
}


def check(body, status="200", path="/orders/7"):
    return verify_samples(normalize(SPEC), [Sample("GET", path, status, body)])


def test_matching_response_passes():
    body = {
        "id": 1,
        "total": 2.5,
        "status": "new",
        "note": None,
        "lines": [{"sku": "a", "children": [{"sku": "b"}]}],
    }
    report = check(body)
    assert report.ok and report.checked == 1


@pytest.mark.parametrize(
    "body, problem",
    [
        ({"id": 1}, "$.total: required field missing"),
        ({"id": 1, "total": "2"}, "$.total: expected number, got string"),
        ({"id": 1, "total": 2, "status": "lost"}, "$.status: 'lost' is not one of"),
        ({"id": 1, "total": 2, "extra": 1}, "$.extra: field not declared"),
        ({"id": None, "total": 2}, "$.id: null is not allowed"),
        (
            {"id": 1, "total": 2, "lines": [{"children": [{"sku": 5}]}]},
            "$.lines[0].children[0].sku: expected string",
        ),
        ({"id": 1, "total": 2, "note": 3}, "$.note: expected string, got integer"),
        ([], "$: expected object, got array"),
    ],
)
def test_mismatches_are_reported(body, problem):
    report = check(body)
    assert not report.ok
    assert any(problem in p for p in report.problems), report.problems


def test_status_and_endpoint_checks():
    assert check(None, status="404").ok
    report = check({"id": 1, "total": 1}, status="500")
    assert report.problems == ["GET /orders/{id}: status 500 is not in the contract"]
    report = check({}, path="/nope")
    assert report.ok and report.unmatched == ["GET /nope -> 200"]


def test_read_jsonl_and_har(tmp_path):
    jsonl = tmp_path / "s.jsonl"
    jsonl.write_text(
        json.dumps(
            {"method": "get", "url": "https://x/orders/1?a=b", "status": 200, "body": '{"id": 1}'}
        )
        + "\n\n"
        + json.dumps({"method": "GET", "path": "/orders/2", "status": 404})
        + "\n"
    )
    samples = read_samples(jsonl)
    assert [(s.method, s.path, s.status, s.body, s.has_body) for s in samples] == [
        ("GET", "/orders/1", "200", {"id": 1}, True),
        ("GET", "/orders/2", "404", None, False),
    ]
    har = tmp_path / "s.har"
    entry = {
        "request": {"method": "GET", "url": "https://x/orders/3"},
        "response": {
            "status": 200,
            "content": {"mimeType": "application/json", "text": '{"id": 3, "total": 1}'},
        },
    }
    image = {
        "request": {"method": "GET", "url": "https://x/a.png"},
        "response": {"status": 200, "content": {"mimeType": "image/png"}},
    }
    har.write_text(json.dumps({"log": {"entries": [entry, image]}}))
    [sample] = read_samples(har)
    assert sample.body == {"id": 3, "total": 1}
    (tmp_path / "bad.jsonl").write_text("not json\n")
    with pytest.raises(ApiContractError, match="bad.jsonl:1"):
        read_samples(tmp_path / "bad.jsonl")


def test_verify_samples_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:openapi.yaml"\n')
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump(SPEC))
    assert main(["snapshot"]) == 0
    good = json.dumps(
        {"method": "GET", "path": "/orders/1", "status": 200, "body": {"id": 1, "total": 1}}
    )
    bad = json.dumps(
        {"method": "GET", "path": "/orders/1", "status": 200, "body": {"id": "1", "total": 1}}
    )
    other = json.dumps({"method": "GET", "path": "/other", "status": 200})
    (tmp_path / "good.jsonl").write_text(good + "\n" + other + "\n")
    (tmp_path / "bad.jsonl").write_text(bad + "\n")
    capsys.readouterr()
    assert main(["verify-samples", "good.jsonl"]) == 0
    assert "1 checked, 0 problem(s), 1 not in the contract" in capsys.readouterr().out
    assert main(["verify-samples", "good.jsonl", "--fail-undocumented"]) == 1
    capsys.readouterr()
    assert main(["verify-samples", "bad.jsonl", "--format", "json"]) == 1
    assert "expected integer, got string" in json.loads(capsys.readouterr().out)["problems"][0]
    assert main(["verify-samples", "bad.jsonl", "--source", "file:openapi.yaml"]) == 1
