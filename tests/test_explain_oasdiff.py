import datetime as dt
import sys

import pytest
import yaml

from api_contract import ApiContractError, Rules
from api_contract.allowlist import load_allowlist
from api_contract.cli import main
from api_contract.explain import explain, explain_kinds, resolve
from api_contract.oasdiff import (
    OASDIFF_CHECKS,
    import_err_ignore,
    import_severity_levels,
    render_allowlist_yaml,
    render_rules_toml,
)
from api_contract.rules import DEFAULT_RULES

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib


@pytest.mark.parametrize("kind", sorted(DEFAULT_RULES))
def test_every_kind_is_explained(kind):
    text = explain(kind)
    assert text.startswith(kind)
    assert "What it means:" in text and "How to ship it compatibly:" in text
    assert "  1. " in text
    assert explain_kinds()[kind]


def test_explain_change_id_with_detail_and_colon_path():
    kinds, where = resolve(
        'POST /v1/things:cancel:response:200:status:response-enum-value-added:"x"'
    )
    assert kinds == ["response-enum-value-added"]
    assert where == "POST /v1/things:cancel:response:200:status"
    assert "Where:      GET /a\n" in explain("GET /a:endpoint-removed")


def test_explain_alias_and_override():
    kinds, _ = resolve("enum-value-added")
    assert kinds == ["request-enum-value-added", "response-enum-value-added"]
    text = explain("response-enum-value-added", rules=Rules({"enum-value-added": "breaking"}))
    assert "breaking (this project; the default is potentially-breaking)" in text


def test_explain_unknown_suggests():
    with pytest.raises(ApiContractError, match="did you mean.*response-field-removed"):
        explain("response-feild-removed")


def test_explain_cli(capsys):
    assert main(["explain", "type-changed"]) == 0
    assert "type-changed" in capsys.readouterr().out
    assert main(["explain", "nonsense-kind"]) == 2


def test_import_err_ignore():
    text = (
        "# comment\n\n"
        "GET /api/orders/{order_id} removed the success response property 'total'\n"
        "get /api/orders/{id} another message on the same endpoint\n"
        "POST /api/coupons added required request property 'code'\n"
        "not a valid line\n"
    )
    entries, skipped = import_err_ignore(text, reason="from oasdiff", expires=dt.date(2999, 1, 1))
    assert [e.id for e in entries] == ["GET /api/orders/{}:*", "POST /api/coupons:*"]
    assert entries[0].reason.startswith("from oasdiff (oasdiff: removed")
    assert skipped == [6]
    with pytest.raises(ApiContractError):
        import_err_ignore("GET /a x", reason=" ", expires=dt.date(2999, 1, 1))


def test_import_severity_levels():
    text = (
        "response-property-removed WARN\n"
        "response-required-property-removed ERR\n"
        "request-property-max-length-decreased INFO\n"
        "some-unknown-check ERR\n"
    )
    rules, unmapped = import_severity_levels(text)
    assert rules == {
        "request-constraint-tightened": "safe",
        "response-field-removed": "breaking",  # strictest wins
    }
    assert unmapped == ["some-unknown-check"]
    with pytest.raises(ApiContractError, match="line 1"):
        import_severity_levels("only-one-token\n")
    assert all(k in DEFAULT_RULES for kinds in OASDIFF_CHECKS.values() for k in kinds)


def test_renderers_round_trip(tmp_path):
    toml = render_rules_toml({"type-changed": "potentially-breaking"})
    assert tomllib.loads(toml)["tool"]["api-contract"]["rules"] == {
        "type-changed": "potentially-breaking"
    }
    Rules(tomllib.loads(toml)["tool"]["api-contract"]["rules"])  # valid kinds
    entries, _ = import_err_ignore("GET /a x\n", reason="r", expires=dt.date(2999, 1, 1))
    path = tmp_path / "allow.yml"
    path.write_text(render_allowlist_yaml(entries))
    assert [e.id for e in load_allowlist(path)] == ["GET /a:*"]


def test_import_oasdiff_cli(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "ignore.txt").write_text("GET /a msg\nbad\n")
    (tmp_path / "levels.txt").write_text("response-property-removed WARN\nzzz ERR\n")
    rc = main(["import-oasdiff", "--severity-levels", "levels.txt"])
    out, err = capsys.readouterr()
    assert rc == 0 and 'response-field-removed = "potentially-breaking"' in out
    assert "zzz" in err
    args = [
        "import-oasdiff",
        "--err-ignore",
        "ignore.txt",
        "--reason",
        "r",
        "--expires",
        "2999-01-01",
    ]
    assert main(args) == 0
    assert "GET /a:*" in capsys.readouterr().out
    assert main([*args, "--write"]) == 0
    allow = yaml.safe_load((tmp_path / "api-contract-allow.yml").read_text())
    assert allow["allow"][0]["id"] == "GET /a:*"
    assert main(["import-oasdiff"]) == 2
    assert main(["import-oasdiff", "--err-ignore", "ignore.txt"]) == 2
