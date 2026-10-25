import datetime as dt
import json

import pytest

from api_contract import ApiContractError, diff
from api_contract.allowlist import AllowEntry, add_entry, apply_allowlist, load_allowlist

OLD = {
    "openapi": "3.0.3",
    "paths": {"/a/{id}": {"get": {"responses": {}}}, "/b": {"get": {"responses": {}}}},
}
NEW = {"openapi": "3.0.3", "paths": {}}
TODAY = dt.date(2026, 10, 25)


def entry(id_, expires=dt.date(2026, 12, 1)):
    return AllowEntry(id=id_, reason="client migrated", expires=expires)


def test_allowed_expired_and_stale():
    changes = diff(OLD, NEW)
    entries = [
        entry("GET /a/{id}:endpoint-removed"),  # named param still matches
        entry("GET /b:endpoint-removed", expires=dt.date(2026, 10, 24)),
        entry("GET /gone:endpoint-removed"),
    ]
    result = apply_allowlist(changes, entries, TODAY)
    by_id = {c.id: c for c in changes}
    assert by_id["GET /a/{}:endpoint-removed"].allowed
    assert not by_id["GET /b:endpoint-removed"].allowed
    assert [e.id for e in result.expired] == ["GET /b:endpoint-removed"]
    assert [e.id for e in result.stale] == ["GET /gone:endpoint-removed"]


def test_expiry_day_itself_is_still_valid():
    changes = diff(OLD, NEW)
    result = apply_allowlist(changes, [entry("GET /b:endpoint-removed", TODAY)], TODAY)
    assert not result.expired


def test_wildcards():
    changes = diff(OLD, NEW)
    apply_allowlist(changes, [entry("GET *:endpoint-removed")], TODAY)
    assert all(c.allowed for c in changes)


def test_add_entry_appends_and_keeps_comments(tmp_path):
    path = tmp_path / "allow.yml"
    add_entry(path, entry("GET /a/{}:endpoint-removed"))
    path.write_text("# keep me\n" + path.read_text())
    add_entry(path, entry("GET /b:endpoint-removed"))
    text = path.read_text()
    assert "# keep me" in text
    assert [e.id for e in load_allowlist(path)] == [
        "GET /a/{}:endpoint-removed",
        "GET /b:endpoint-removed",
    ]
    # Same id again replaces rather than duplicates.
    add_entry(path, AllowEntry(id="GET /b:endpoint-removed", reason="new reason", expires=TODAY))
    entries = load_allowlist(path)
    assert len(entries) == 2 and entries[1].reason == "new reason"


def test_flow_style_file_falls_back_to_rewrite(tmp_path):
    path = tmp_path / "allow.yml"
    path.write_text("allow: []\n")
    add_entry(path, entry("GET /b:endpoint-removed"))
    assert len(load_allowlist(path)) == 1


@pytest.mark.parametrize(
    "text, message",
    [
        ("allow:\n  - id: x\n    expires: 2026-01-01\n", "reason"),
        ("allow:\n  - id: x\n    reason: r\n", "expires"),
        ("allow:\n  - id: x\n    reason: r\n    expires: soon\n", "date"),
        ("allow: 3\n", "list"),
    ],
)
def test_invalid_files(tmp_path, text, message):
    path = tmp_path / "allow.yml"
    path.write_text(text)
    with pytest.raises(ApiContractError, match=message):
        load_allowlist(path)


def test_missing_file_is_empty(tmp_path):
    assert load_allowlist(tmp_path / "nope.yml") == []


def test_duplicate_allow_keys_are_rejected(tmp_path):
    path = tmp_path / "allow.yml"
    path.write_text(
        "allow:\n  - id: 'GET /a:endpoint-removed'\n    reason: one\n    expires: 2026-12-01\n"
        "allow:\n  - id: 'GET /b:endpoint-removed'\n    reason: two\n    expires: 2026-12-01\n"
    )
    with pytest.raises(ApiContractError, match=r"duplicate key 'allow'"):
        load_allowlist(path)


def test_duplicate_keys_inside_an_entry_are_rejected(tmp_path):
    path = tmp_path / "allow.yml"
    path.write_text(
        "allow:\n  - id: 'GET /a:endpoint-removed'\n    reason: one\n    reason: two\n"
        "    expires: 2026-12-01\n"
    )
    with pytest.raises(ApiContractError, match=r"duplicate key 'reason'"):
        load_allowlist(path)


def test_duplicate_allow_keys_exit_2_from_the_cli(tmp_path, monkeypatch, capsys):
    from api_contract.cli import main

    monkeypatch.chdir(tmp_path)
    (tmp_path / "old.json").write_text(json.dumps(OLD))
    (tmp_path / "new.json").write_text(json.dumps(NEW))
    (tmp_path / "allow.yml").write_text("allow: []\nallow: []\n")
    code = main(["diff", "old.json", "new.json", "--allowlist", "allow.yml"])
    assert code == 2
    assert "duplicate key" in capsys.readouterr().err
