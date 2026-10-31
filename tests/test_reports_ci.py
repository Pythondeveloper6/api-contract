import datetime as dt
import json
import xml.etree.ElementTree as ET

import pytest

from api_contract import __version__
from api_contract.allowlist import AllowEntry
from api_contract.cli import main
from api_contract.core import CheckResult
from api_contract.model import Change, Direction, Severity
from api_contract.report import FORMATS
from api_contract.report.github import escape_data, escape_property
from api_contract.report.sarif import parse_location


def orders_spec(total_type="number"):
    schema = {"type": "object", "properties": {"total": {"type": total_type}}}
    ok = {"description": "OK", "content": {"application/json": {"schema": schema}}}
    return {
        "openapi": "3.0.3",
        "info": {"title": "Shop", "version": "1"},
        "paths": {"/orders": {"get": {"responses": {"200": ok}}}},
    }


ENTRY = AllowEntry("GET /legacy:endpoint-removed", "clients migrated", dt.date(2026, 12, 1))
EXPIRED = AllowEntry("GET /old:endpoint-removed", "long gone", dt.date(2026, 1, 1))


def make(kind, severity, path="/orders/{id}", method="GET", attribution=None, message="msg"):
    return Change(
        kind=kind,
        severity=severity,
        direction=Direction.RESPONSE,
        method=method,
        path=path.replace("{id}", "{}"),
        raw_path=path,
        message=message,
        attribution=attribution,
    )


def result(**kwargs):
    breaking = make("type-changed", Severity.BREAKING, attribution="app.main.Order (app/main.py:7)")
    allowed = make("endpoint-removed", Severity.BREAKING, path="/legacy")
    allowed.allowed_by = ENTRY
    potential = make("response-enum-value-added", Severity.POTENTIALLY_BREAKING)
    safe = make("endpoint-added", Severity.SAFE, path="/coupons", method="POST")
    return CheckResult([breaking, allowed, potential, safe], **kwargs)


def sarif(res):
    return json.loads(FORMATS["sarif"](res))


def test_sarif_levels_suppressions_fingerprints():
    res = result()
    text = FORMATS["sarif"](res)
    assert text.endswith("}\n")
    doc = json.loads(text)
    assert doc["version"] == "2.1.0"
    driver = doc["runs"][0]["tool"]["driver"]
    assert driver["name"] == "api-contract" and driver["version"] == __version__
    assert [r["id"] for r in driver["rules"]] == [
        "endpoint-added",
        "endpoint-removed",
        "response-enum-value-added",
        "type-changed",
    ]
    by_rule = {r["ruleId"]: r for r in doc["runs"][0]["results"]}
    assert by_rule["type-changed"]["level"] == "error"
    assert by_rule["response-enum-value-added"]["level"] == "warning"
    assert by_rule["endpoint-added"]["level"] == "note"
    removed = by_rule["endpoint-removed"]
    assert removed["level"] == "warning"
    assert removed["suppressions"] == [{"kind": "external", "justification": "clients migrated"}]
    assert "suppressions" not in by_rule["type-changed"]
    assert by_rule["type-changed"]["partialFingerprints"] == {"apiContractId/v1": res.changes[0].id}
    assert by_rule["type-changed"]["message"]["text"] == "GET /orders/{id} msg"


def test_sarif_locations():
    by_rule = {r["ruleId"]: r for r in sarif(result())["runs"][0]["results"]}
    loc = by_rule["type-changed"]["locations"][0]
    assert loc["physicalLocation"] == {
        "artifactLocation": {"uri": "app/main.py"},
        "region": {"startLine": 7},
    }
    bare = by_rule["response-enum-value-added"]["locations"][0]
    assert "physicalLocation" not in bare
    assert bare["logicalLocations"] == [{"name": "GET /orders/{id}", "kind": "resource"}]


def test_sarif_expired_entries_and_empty():
    doc = sarif(CheckResult([], expired=[EXPIRED]))
    [only] = doc["runs"][0]["results"]
    assert only["ruleId"] == "allowlist-entry-expired" and only["level"] == "error"
    assert [r["id"] for r in doc["runs"][0]["tool"]["driver"]["rules"]] == [
        "allowlist-entry-expired"
    ]
    empty = sarif(CheckResult([]))
    assert empty["runs"][0]["results"] == [] and empty["runs"][0]["tool"]["driver"]["rules"] == []


def test_sarif_is_deterministic():
    assert FORMATS["sarif"](result()) == FORMATS["sarif"](result())


@pytest.mark.parametrize(
    ("attribution", "expected"),
    [
        ("app.main.Order (app/main.py:7)", ("app/main.py", 7)),
        ("x (.\\pkg\\mod.py:12)", ("pkg/mod.py", 12)),
        ("app.main.Order", None),
        (None, None),
    ],
)
def test_parse_location(attribution, expected):
    assert parse_location(attribution) == expected


def test_github_commands():
    lines = FORMATS["github"](result()).splitlines()
    assert lines[0].startswith(
        "::error file=app/main.py,line=7,title=api-contract%3A type-changed::"
    )
    assert "GET /orders/{id} msg (id: GET /orders/{}:type-changed)" in lines[0]
    assert lines[1].startswith("::warning title=api-contract%3A endpoint-removed::")
    assert lines[2].startswith("::warning title=api-contract%3A response-enum-value-added::")
    assert len(lines) == 4  # safe change skipped; summary line last
    assert lines[-1] == "API contract: 4 changes (2 breaking, 1 allowed)"


def test_github_expired_and_empty():
    lines = FORMATS["github"](CheckResult([], expired=[EXPIRED])).splitlines()
    assert lines[0].startswith("::error title=api-contract%3A allowlist-entry-expired::")
    assert "expired 2026-01-01: long gone" in lines[0]
    assert FORMATS["github"](CheckResult([])) == "API contract: no changes\n"


def test_github_escaping():
    assert escape_data("a%b\r\nc:d,e") == "a%25b%0D%0Ac:d,e"
    assert escape_property("a%b\nc:d,e") == "a%25b%0Ac%3Ad%2Ce"
    change = make("type-changed", Severity.BREAKING, message="line1\nline2 100%")
    out = FORMATS["github"](CheckResult([change]))
    assert "line1%0Aline2 100%25" in out
    assert len(out.splitlines()) == 2


def test_junit_structure_and_counts():
    text = FORMATS["junit"](result(expired=[EXPIRED]))
    assert text.startswith('<?xml version="1.0" encoding="utf-8"?>')
    root = ET.fromstring(text.encode())
    counts = {"tests": "5", "failures": "2", "skipped": "1"}
    assert {k: root.get(k) for k in counts} == counts
    [suite] = root.findall("testsuite")
    assert suite.get("name") == "api-contract"
    assert {k: suite.get(k) for k in counts} == counts
    cases = {c.get("name"): c for c in suite.findall("testcase")}
    failing = cases["GET /orders/{}:type-changed"]
    assert failing.get("classname") == "GET /orders/{id}"
    assert failing.find("failure").get("type") == "type-changed"
    skipped = cases["GET /legacy:endpoint-removed"].find("skipped")
    assert skipped.get("message") == "allowed until 2026-12-01: clients migrated"
    for name in ("GET /orders/{}:response-enum-value-added", "POST /coupons:endpoint-added"):
        assert len(cases[name]) == 0
    expired = cases["GET /old:endpoint-removed"]
    assert expired.find("failure").get("type") == "allowlist-entry-expired"


def test_junit_empty():
    root = ET.fromstring(FORMATS["junit"](CheckResult([])).encode())
    assert root.get("tests") == "0" and root.find("testsuite").get("failures") == "0"


@pytest.mark.parametrize("fmt", ["sarif", "github", "junit"])
def test_cli_diff_formats(tmp_path, capsys, fmt):
    old, new = tmp_path / "old.json", tmp_path / "new.json"
    old.write_text(json.dumps(orders_spec()))
    new.write_text(json.dumps(orders_spec(total_type="string")))
    code = main(["diff", str(old), str(new), "--format", fmt])
    out = capsys.readouterr().out
    assert code in (0, 1)
    if fmt == "sarif":
        results = json.loads(out)["runs"][0]["results"]
        assert any(r["ruleId"] == "type-changed" for r in results)
    elif fmt == "github":
        assert "::error " in out and "type-changed" in out
    else:
        assert ET.fromstring(out.encode()).find("testsuite").get("failures") == "1"
