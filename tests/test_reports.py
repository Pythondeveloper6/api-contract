import datetime as dt
import json
import shlex

from api_contract import diff
from api_contract.allowlist import AllowEntry, apply_allowlist
from api_contract.changelog import render_changelog
from api_contract.core import CheckResult
from api_contract.model import Severity
from api_contract.report import FORMATS
from api_contract.report import json as json_report

TODAY = dt.date(2026, 10, 25)


def _changes():
    old = {
        "openapi": "3.0.3",
        "paths": {
            "/orders/{id}": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "total": {"type": "number"},
                                            "status": {"type": "string", "enum": ["new"]},
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            },
            "/legacy": {"get": {"responses": {}}},
        },
    }
    new = json.loads(json.dumps(old))
    props = new["paths"]["/orders/{id}"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["properties"]
    props["total"]["type"] = "string"
    props["status"]["enum"].append("on_hold")
    new["paths"]["/coupons"] = {"post": {"responses": {}}}
    del new["paths"]["/legacy"]
    changes = diff(old, new)
    for c in changes:
        if c.kind == "type-changed":
            c.attribution = "orders.serializers.OrderSerializer"
    return changes


def _result():
    changes = _changes()
    entries = [
        AllowEntry("GET /legacy:endpoint-removed", "clients migrated", dt.date(2026, 12, 1)),
        AllowEntry("GET /old:endpoint-removed", "long gone", dt.date(2026, 1, 1)),
        AllowEntry("GET /never:endpoint-removed", "typo", dt.date(2026, 12, 1)),
    ]
    outcome = apply_allowlist(changes, entries, TODAY)
    return CheckResult(changes, expired=outcome.expired, stale=outcome.stale)


def test_text_report_shape():
    text = FORMATS["text"](_result(), today=TODAY)
    lines = text.splitlines()
    assert lines[0] == "API contract: 4 changes (2 breaking, 1 allowed)"
    assert lines.index("BREAKING") < lines.index("POTENTIALLY BREAKING") < lines.index("SAFE")
    assert '  GET /orders/{id}  response field "total" type changed: number -> string' in lines
    assert "      at: orders.serializers.OrderSerializer" in lines
    assert "      id: GET /orders/{}:response:200:total:type-changed" in lines
    assert "      allowed until 2026-12-01: clients migrated" in lines
    assert any(line.startswith("EXPIRED ALLOWLIST") for line in lines)
    assert any(line.startswith("STALE ALLOWLIST") for line in lines)
    assert lines[-1] == (
        "  api-contract allow 'GET /orders/{}:response:200:total:type-changed' "
        '--reason "..." --expires 2026-11-24'
    )


def test_text_report_command_name_is_configurable():
    text = FORMATS["text"](_result(), command="manage.py api_contract", today=TODAY)
    assert "manage.py api_contract allow '" in text


def _quoted_enum_result():
    old = {
        "paths": {
            "/orders": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {"type": "string", "enum": ["new"]}
                                        },
                                    }
                                }
                            },
                        }
                    }
                }
            }
        }
    }
    new = json.loads(json.dumps(old))
    enum = new["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["properties"]["status"]["enum"]
    enum.append('"on_hold"')
    changes = diff(old, new)
    return CheckResult(changes, fail_on=Severity.POTENTIALLY_BREAKING)


def test_hint_is_shell_safe_for_ids_with_double_quotes():
    result = _quoted_enum_result()
    expected_id = result.failing[0].id
    assert '"' in expected_id
    for report in ("text", "markdown"):
        text = FORMATS[report](result, today=TODAY)
        line = next(line for line in text.splitlines() if " allow " in line)
        argv = shlex.split(line.strip().removeprefix("```").strip())
        assert argv[:3] == ["api-contract", "allow", expected_id]
        assert argv[3:] == ["--reason", "...", "--expires", "2026-11-24"]


def test_markdown_report_shape():
    md = FORMATS["markdown"](_result(), today=TODAY)
    assert md.startswith("### API contract: 4 changes (2 breaking, 1 allowed) — failed\n")
    assert "#### Breaking (2)" in md
    assert "#### Potentially breaking (1)" in md
    assert "<details><summary>Safe (1)</summary>" in md
    assert '- **GET** `/orders/{id}` — response field "total" type changed: number -> string' in md
    assert "```sh" in md


def test_json_report_shape():
    data = json.loads(FORMATS["json"](_result()))
    assert data == json_report.as_dict(_result()) | {"changes": data["changes"]}
    assert set(data) == {"version", "ok", "fail_on", "summary", "changes", "allowlist", "warnings"}
    assert data["summary"] == {
        "total": 4,
        "breaking": 2,
        "potentially-breaking": 1,
        "safe": 1,
        "allowed": 1,
        "failing": 1,
    }
    first = data["changes"][0]
    assert set(first) >= {
        "id",
        "kind",
        "severity",
        "direction",
        "method",
        "path",
        "raw_path",
        "location",
        "pointer",
        "old",
        "new",
        "message",
        "attribution",
        "allowed",
    }
    assert [e["id"] for e in data["allowlist"]["expired"]] == ["GET /old:endpoint-removed"]
    assert [e["id"] for e in data["allowlist"]["stale"]] == ["GET /never:endpoint-removed"]


def test_empty_report():
    result = CheckResult([])
    assert FORMATS["text"](result) == "API contract: no changes\n"
    assert result.ok and result.exit_code == 0


def test_changelog_sections():
    md = render_changelog(_changes(), title="Release 2.0")
    assert md.startswith("## Release 2.0\n")
    assert "### Breaking changes" in md
    assert "### Changes that may affect you" in md
    assert "- New endpoint `POST /coupons`" in md
    assert "- `GET /legacy`: endpoint removed" in md
    assert "id:" not in md
    assert "No changes" in render_changelog([])
