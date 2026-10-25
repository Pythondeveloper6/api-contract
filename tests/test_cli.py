import json

import pytest
import yaml

from api_contract.cli import main


def orders_spec(total_type="number", extra_required=False):
    props = {"id": {"type": "integer"}, "total": {"type": total_type}}
    body = {"type": "object", "properties": {"note": {"type": "string"}}}
    if extra_required:
        body["required"] = ["note"]
    return {
        "openapi": "3.0.3",
        "info": {"title": "Shop", "version": "1"},
        "paths": {
            "/api/orders/{id}/": {
                "get": {
                    "parameters": [{"in": "path", "name": "id", "required": True}],
                    "responses": {
                        "200": {
                            "description": "OK",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "required": ["id", "total"],
                                        "properties": props,
                                    }
                                }
                            },
                        }
                    },
                },
                "patch": {
                    "requestBody": {"content": {"application/json": {"schema": body}}},
                    "responses": {"200": {"description": "OK"}},
                },
            }
        },
    }


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:openapi.yaml"\n')
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump(orders_spec()))
    return tmp_path


def test_snapshot_check_allow_roundtrip(project, capsys):
    assert main(["snapshot"]) == 0
    assert (project / "api-contract.json").exists()
    assert main(["check"]) == 0
    assert "no changes" in capsys.readouterr().out

    (project / "openapi.yaml").write_text(yaml.safe_dump(orders_spec(total_type="string")))
    assert main(["check"]) == 1
    out = capsys.readouterr().out
    assert "BREAKING" in out
    assert 'GET /api/orders/{id}/  response field "total" type changed: number -> string' in out
    change_id = "GET /api/orders/{}/:response:200:total:type-changed"
    assert f"api-contract allow '{change_id}'" in out

    # Ids written with the real parameter name are accepted too.
    rc = main(
        [
            "allow",
            "GET /api/orders/{id}/:response:200:total:type-changed",
            "--reason",
            "app 4.2 reads total_display",
            "--expires",
            "2999-01-01",
        ]
    )
    assert rc == 0
    allow = yaml.safe_load((project / "api-contract-allow.yml").read_text())
    assert allow["allow"][0]["id"] == change_id
    capsys.readouterr()
    assert main(["check"]) == 0
    assert "allowed until 2999-01-01" in capsys.readouterr().out


def test_expired_allowlist_entry_fails(project, capsys):
    main(["snapshot"])
    (project / "api-contract-allow.yml").write_text(
        "allow:\n  - id: 'GET /x:endpoint-removed'\n    reason: old\n    expires: 2000-01-01\n"
    )
    assert main(["check"]) == 1
    assert "EXPIRED" in capsys.readouterr().out


def test_fail_on_potentially_breaking(project):
    main(["snapshot"])
    spec = orders_spec()
    body = spec["paths"]["/api/orders/{id}/"]["patch"]["requestBody"]
    # A tighter request limit is potentially breaking, not breaking.
    body["content"]["application/json"]["schema"]["properties"]["note"]["maxLength"] = 10
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec))
    assert main(["check"]) == 0
    assert main(["check", "--fail-on", "potentially-breaking"]) == 1


def test_diff_two_files_with_formats(project, capsys):
    old = project / "old.json"
    new = project / "new.json"
    old.write_text(json.dumps(orders_spec()))
    new.write_text(json.dumps(orders_spec(extra_required=True)))
    assert main(["diff", str(old), str(new), "--format", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False
    assert report["summary"]["breaking"] == 1
    [change] = report["changes"]
    assert change["id"] == "PATCH /api/orders/{}/:request:note:request-field-became-required"
    assert change["raw_path"] == "/api/orders/{id}/"

    assert main(["diff", str(old), str(new), "--format", "markdown"]) == 1
    md = capsys.readouterr().out
    assert md.startswith("### API contract: 1 change (1 breaking)")
    assert "#### Breaking (1)" in md

    assert main(["diff", str(old), str(old)]) == 0


def test_changelog(project, capsys, tmp_path):
    main(["snapshot"])
    spec = orders_spec(total_type="string")
    spec["paths"]["/api/coupons/"] = {"post": {"responses": {"201": {"description": "ok"}}}}
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec))
    capsys.readouterr()
    assert main(["changelog", "--title", "v2"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("## v2")
    assert "### Breaking changes" in out
    assert "- New endpoint `POST /api/coupons/`" in out


def test_errors_exit_2(project, capsys):
    assert main(["check"]) == 2  # no snapshot yet
    assert "snapshot" in capsys.readouterr().err
    assert main(["check", "--source", "file:missing.json"]) == 2
    assert main(["snapshot", "--source", "file:nowhere.module:build"]) == 2
    (project / "pyproject.toml").write_text("[tool.api-contract]\nbogus = 1\n")
    assert main(["check"]) == 2
    assert main(["allow", "x", "--reason", "r", "--expires", "tomorrow"]) == 2
    assert main(["nonsense"]) == 2
