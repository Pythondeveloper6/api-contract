import json

import pytest

from api_contract import diff
from api_contract.cli import main
from api_contract.core import CheckResult
from api_contract.model import Severity
from api_contract.report import FORMATS
from api_contract.report.grouping import group_changes, split_location

MEDIA = ("application/json", "application/x-www-form-urlencoded", "multipart/form-data")


def _spec(with_note):
    props = {"id": {"type": "integer"}}
    if with_note:
        props["note"] = {"type": "string"}
    schema = {"type": "object", "properties": props}
    body = {mt: {"schema": schema} for mt in MEDIA}
    ops = {
        "requestBody": {"content": body},
        "responses": {"200": {"description": "OK", "content": body}},
    }
    return {
        "openapi": "3.0.3",
        "paths": {"/api/a/": {"post": ops}, "/api/b/": {"put": ops}},
    }


@pytest.fixture
def specs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "old.json").write_text(json.dumps(_spec(True)))
    (tmp_path / "new.json").write_text(json.dumps(_spec(False)))
    return tmp_path


def _result():
    changes = diff(_spec(True), _spec(False))
    return CheckResult(changes=changes, fail_on=Severity.BREAKING, expired=[], stale=[])


def test_split_location():
    assert split_location("response:200:multipart/form-data") == (
        "response:200",
        "multipart/form-data",
    )
    assert split_location("request:application/json") == ("request", "application/json")
    assert split_location("param:query:limit") == ("param:query:limit", None)


def test_one_field_removal_is_one_group_per_direction():
    changes = diff(_spec(True), _spec(False))
    removed = [c for c in changes if c.pointer == "note"]
    assert len(removed) >= 2 * 3 * 2 - 6  # fanned out over endpoints and media types
    groups = group_changes(removed)
    assert len(groups) < len(removed)
    for group in groups:
        assert group.endpoints == ["POST /api/a/", "PUT /api/b/"]
        assert group.media_types == sorted(MEDIA)
    assert len(group_changes(removed, group=False)) == len(removed)


def test_text_report_groups_and_no_group_restores_every_line():
    result = _result()
    grouped = FORMATS["text"](result, command="api-contract")
    flat = FORMATS["text"](result, command="api-contract", group=False)
    assert len(grouped.splitlines()) < len(flat.splitlines())
    assert "2 endpoints" in grouped
    assert "media types:" in grouped
    assert "POST /api/a/" in grouped and "PUT /api/b/" in grouped
    for change in result.changes:
        assert change.id in flat


def test_markdown_report_groups():
    result = _result()
    grouped = FORMATS["markdown"](result, command="api-contract")
    flat = FORMATS["markdown"](result, command="api-contract", group=False)
    assert len(grouped.splitlines()) < len(flat.splitlines())
    assert "(2 endpoints)" in grouped
    assert "`POST /api/a/`" in grouped and "`PUT /api/b/`" in grouped


def test_json_report_is_never_grouped():
    result = _result()
    data = json.loads(FORMATS["json"](result, command="api-contract", group=True))
    assert [c["id"] for c in data["changes"]] == [c.id for c in result.changes]
    assert data["summary"]["total"] == len(result.changes)


def test_cli_grouping_does_not_change_exit_code_or_json(specs, capsys):
    code = main(["diff", "old.json", "new.json"])
    grouped = capsys.readouterr().out
    assert code == main(["diff", "old.json", "new.json", "--no-group"]) == 1
    flat = capsys.readouterr().out
    assert len(grouped.splitlines()) < len(flat.splitlines())

    main(["diff", "old.json", "new.json", "--format", "json"])
    plain = capsys.readouterr().out
    main(["diff", "old.json", "new.json", "--format", "json", "--no-group"])
    assert capsys.readouterr().out == plain


def test_check_accepts_no_group(specs, capsys):
    (specs / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:new.json"\n')
    assert main(["snapshot", "--source", "file:old.json"]) == 0
    assert main(["check", "--no-group"]) == 1
    assert "BREAKING" in capsys.readouterr().out
