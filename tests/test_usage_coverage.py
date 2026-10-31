import json

import pytest
import yaml

from api_contract import Severity, diff
from api_contract.cli import main
from api_contract.coverage import measure, warnings_for
from api_contract.normalize import normalize
from api_contract.policy import apply_usage
from api_contract.usage import read_usage

TEMPLATES = ["/orders", "/orders/{}", "/orders/new", "/users/{}/orders/{}"]


def test_read_usage_access_log_json_and_otel(tmp_path):
    log = tmp_path / "access.log"
    log.write_text(
        '10.0.0.1 - - [01/Jun/2026:10:00:00 +0000] "GET /orders/42?x=1 HTTP/1.1" 200 12\n'
        '10.0.0.1 - - [01/Jun/2026:10:00:01 +0000] "GET /orders/new HTTP/1.1" 200 12\n'
        '10.0.0.1 - - [01/Jun/2026:10:00:02 +0000] "POST /orders/ HTTP/1.1" 201 1\n'
        "garbage line\n"
        '{"method": "get", "path": "/users/7/orders/9", "count": 5}\n'
        '{"attributes": {"http.method": "DELETE", "http.target": "/orders/1"}}\n'
        '{"request": "GET /orders/3 HTTP/1.1", "method": "GET"}\n'
        '{"method": "GET", "url": "https://api.example.com/unknown"}\n'
    )
    sample = read_usage([log], TEMPLATES)
    assert sample.hits[("GET", "/orders/{}")] == 2
    assert sample.hits[("GET", "/orders/new")] == 1  # static beats {}
    assert sample.hits[("POST", "/orders")] == 1  # trailing slash tolerated
    assert sample.hits[("GET", "/users/{}/orders/{}")] == 5
    assert sample.hits[("DELETE", "/orders/{}")] == 1
    assert sample.lines == 7
    assert sample.unmatched == 1


def test_apply_usage_downgrades_unused_endpoints():
    old = {"openapi": "3.0.3", "paths": {"/a": {"get": {}}, "/b": {"get": {}}}}
    changes = diff(old, {"openapi": "3.0.3", "paths": {}})
    apply_usage(changes, {("GET", "/a"): 3}, unused_severity=Severity.POTENTIALLY_BREAKING)
    by_path = {c.path: c for c in changes}
    assert by_path["/a"].hits == 3 and by_path["/a"].severity is Severity.BREAKING
    assert by_path["/b"].hits == 0
    assert by_path["/b"].severity is Severity.POTENTIALLY_BREAKING
    assert "no traffic" in by_path["/b"].message


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:openapi.yaml"\n')
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/used": {"get": {"responses": {"204": {"description": "ok"}}}},
            "/unused": {"get": {"responses": {"204": {"description": "ok"}}}},
        },
    }
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump(spec))
    assert main(["snapshot"]) == 0
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump({"openapi": "3.0.3", "paths": {}}))
    (tmp_path / "access.log").write_text('1.2.3.4 - - [x] "GET /used HTTP/1.1" 200 1\n')
    return tmp_path


def test_check_with_usage(project, capsys):
    capsys.readouterr()
    assert main(["check", "--usage", "access.log"]) == 1
    out = capsys.readouterr().out
    assert "traffic: 1 request in the usage sample" in out
    assert "traffic: 0 requests" in out
    rc = main(["check", "--usage", "access.log", "--unused-severity", "safe", "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    severities = {c["path"]: (c["severity"], c["hits"]) for c in data["changes"]}
    assert severities == {"/used": ("breaking", 1), "/unused": ("safe", 0)}
    assert rc == 1


def test_usage_errors(project, capsys):
    (project / "empty.log").write_text("nothing here\n")
    assert main(["check", "--usage", "empty.log"]) == 2
    assert main(["check", "--usage", "missing.log"]) == 2
    assert main(["check", "--unused-severity", "safe"]) == 2


def _op(responses, security=None):
    out = {"responses": responses}
    if security is not None:
        out["security"] = security
    return out


def test_coverage_measure():
    typed = {"application/json": {"schema": {"type": "object"}}}
    doc = normalize(
        {
            "openapi": "3.0.3",
            "paths": {
                "/typed": {
                    "get": _op(
                        {"200": {"description": "", "content": typed}, "404": {"description": ""}},
                        [{"k": []}],
                    )
                },
                "/empty": {"get": _op({"200": {"description": ""}})},
                "/nobody": {
                    "delete": _op({"204": {"description": ""}, "default": {"description": ""}})
                },
                "/anything": {
                    "get": _op(
                        {
                            "200": {
                                "description": "",
                                "content": {"application/json": {"schema": {}}},
                            }
                        }
                    )
                },
            },
        }
    )
    cov = measure(doc)
    assert cov.total == 4
    assert cov.typed_pct == 50.0
    assert cov.errors_pct == 50.0
    assert cov.auth_pct == 25.0
    assert sorted(cov.to_dict()["untyped"]) == ["GET /anything", "GET /empty"]


def test_coverage_warnings():
    assert "no operations" in warnings_for(normalize({"openapi": "3.0.3", "paths": {}}))[0]
    untyped = normalize(
        {"openapi": "3.0.3", "paths": {"/a": {"get": _op({"200": {"description": ""}})}}}
    )
    assert "typed success response" in warnings_for(untyped)[0]


def test_check_warns_about_an_empty_schema(project, capsys):
    capsys.readouterr()
    main(["check"])
    out, err = capsys.readouterr()
    assert "WARNING: the schema has no operations" in out
    assert "warning:" in err


def test_coverage_command(project, capsys):
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/a": {
                "get": _op(
                    {
                        "200": {
                            "description": "",
                            "content": {"application/json": {"schema": {"type": "string"}}},
                        }
                    }
                )
            },
            "/b": {"get": _op({"200": {"description": ""}, "400": {"description": ""}})},
        },
    }
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec))
    capsys.readouterr()
    assert main(["coverage"]) == 0
    out = capsys.readouterr().out
    assert "typed success response   50.0%" in out
    assert "GET /b" in out
    assert main(["coverage", "--format", "json", "--min-typed", "60"]) == 1
    captured = capsys.readouterr()
    assert json.loads(captured.out)["operations"] == 2
    assert "coverage too low" in captured.err
    assert main(["coverage", "--min-errors", "50", "--min-typed", "50"]) == 0
