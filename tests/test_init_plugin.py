import json
import logging

import pytest
import yaml

from api_contract.cli import main
from api_contract.init import detect

pytest_plugins = ["pytester"]


def test_detect_fastapi_in_src_layout(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\ndependencies = ["fastapi"]\n')
    pkg = tmp_path / "src" / "shop"
    pkg.mkdir(parents=True)
    (pkg / "main.py").write_text("from fastapi import FastAPI\n\napi = FastAPI(title='x')\n")
    venv = tmp_path / ".venv" / "lib"
    venv.mkdir(parents=True)
    (venv / "other.py").write_text("app = FastAPI()\n")
    found = detect(tmp_path)
    assert (found.framework, found.source, found.extra) == (
        "fastapi",
        "fastapi:shop.main:api",
        "fastapi",
    )


@pytest.mark.parametrize(
    "code, source, extra",
    [
        ("from apiflask import APIFlask\napp = APIFlask(__name__)\n", "flask:wsgi:app", "apiflask"),
        (
            "from flask import Flask\nfrom flask_smorest import Api\n"
            "def create_app():\n    app = Flask(__name__)\n    return app\n"
            "app = Flask(__name__)\n",
            "flask:wsgi:create_app",
            "smorest",
        ),
        ("from flask import Flask\napp = Flask(__name__)\n", "flask-routes:wsgi:app", "flask"),
    ],
)
def test_detect_flask_variants(tmp_path, code, source, extra):
    (tmp_path / "wsgi.py").write_text(code)
    found = detect(tmp_path)
    assert (found.source, found.extra) == (source, extra)


def test_detect_django_and_file(tmp_path):
    (tmp_path / "requirements.txt").write_text("Django>=4.2\ndjango-ninja\n")
    assert (detect(tmp_path).source, detect(tmp_path).extra) == ("django", "ninja")
    other = tmp_path / "other"
    other.mkdir()
    (other / "openapi.yaml").write_text("openapi: 3.0.3\npaths: {}\n")
    assert detect(other).source == "file:openapi.yaml"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect(empty).source is None


def test_init_end_to_end(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n')
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.3\npaths: {}\n")
    assert main(["init", "--pre-commit"]) == 0
    out = capsys.readouterr().out
    assert "Source: file:openapi.yaml (detected file)" in out
    assert (
        '[tool.api-contract]\nsource = "file:openapi.yaml"'
        in (tmp_path / "pyproject.toml").read_text()
    )
    assert (tmp_path / "api-contract.json").exists()
    workflow = yaml.safe_load((tmp_path / ".github/workflows/api-contract.yml").read_text())
    steps = workflow["jobs"]["api-contract"]["steps"]
    assert "--against" in steps[-1]["run"]
    assert "id: api-contract" in (tmp_path / ".pre-commit-config.yaml").read_text()
    # Running it again changes nothing.
    assert main(["init", "--pre-commit"]) == 0
    out = capsys.readouterr().out
    assert out.count("Kept existing") == 3 and "Hook already in" in out
    assert (tmp_path / "pyproject.toml").read_text().count("[tool.api-contract]") == 1


def test_init_without_pyproject_and_failures(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 2  # nothing to detect
    assert "--source" in capsys.readouterr().err
    assert main(["init", "--source", "file:missing.json", "--no-workflow"]) == 2
    assert (tmp_path / "api-contract.toml").exists()
    assert not (tmp_path / ".github").exists()
    (tmp_path / ".pre-commit-config.yaml").write_text("default_stages: [commit]\n")
    assert main(["init", "--no-snapshot", "--no-workflow", "--pre-commit"]) == 2


def test_verbose_logs_timings(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "openapi.json").write_text(json.dumps({"openapi": "3.0.3", "paths": {}}))
    assert main(["snapshot", "--source", "openapi.json", "-v"]) == 0
    err = capsys.readouterr().err
    assert "api-contract: loading 'openapi.json' took" in err
    logging.getLogger("api_contract").setLevel(logging.WARNING)


def test_expiring_command(tmp_path, monkeypatch, capsys):
    import datetime as dt

    monkeypatch.chdir(tmp_path)
    soon = (dt.date.today() + dt.timedelta(days=3)).isoformat()
    (tmp_path / "api-contract-allow.yml").write_text(
        "allow:\n"
        "  - {id: 'GET /a:endpoint-removed', reason: old, expires: 2000-01-01}\n"
        f"  - {{id: 'GET /b:endpoint-removed', reason: soon, expires: {soon}}}\n"
        "  - {id: 'GET /c:endpoint-removed', reason: later, expires: 2999-01-01}\n"
    )
    assert main(["expiring"]) == 0
    out = capsys.readouterr().out
    assert "GET /a:endpoint-removed EXPIRED 2000-01-01" in out
    assert "(in 3 days)" in out and "GET /c" not in out
    assert main(["expiring", "--format", "json", "--fail"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [e["id"] for e in data["expiring"]] == ["GET /b:endpoint-removed"]
    assert main(["expiring", "--format", "slack", "--within", "1w"]) == 0
    assert "`GET /b:endpoint-removed`" in json.loads(capsys.readouterr().out)["text"]
    assert main(["expiring", "--within", "soon"]) == 2
    (tmp_path / "api-contract-allow.yml").write_text("allow: []\n")
    assert main(["expiring", "--fail"]) == 0
    assert "No allowlist entries" in capsys.readouterr().out


SPEC = {"openapi": "3.0.3", "paths": {"/a": {"get": {"responses": {"204": {"description": ""}}}}}}


@pytest.fixture
def contract_project(pytester):
    pytester.makefile(".toml", pyproject='[tool.api-contract]\nsource = "file:openapi.json"\n')
    pytester.makefile(".json", openapi=json.dumps(SPEC))
    pytester.chdir()
    assert main(["snapshot"]) == 0
    pytester.makepyfile(test_ok="def test_ok():\n    pass\n")
    return pytester


def test_pytest_option_passes_and_fails(contract_project):
    result = contract_project.runpytest_inprocess("--api-contract")
    result.assert_outcomes(passed=1)
    result.stdout.fnmatch_lines(["*api-contract*", "API contract: no changes"])
    (contract_project.path / "openapi.json").write_text(json.dumps({**SPEC, "paths": {}}))
    result = contract_project.runpytest_inprocess("--api-contract")
    assert result.ret == 1
    result.stdout.fnmatch_lines(["*endpoint removed*"])
    assert contract_project.runpytest_inprocess().ret == 0  # inert without the flag


def test_pytest_fixture(contract_project):
    contract_project.makepyfile(
        test_contract="def test_contract(api_contract_check):\n    api_contract_check()\n"
    )
    contract_project.runpytest_inprocess().assert_outcomes(passed=2)
    (contract_project.path / "openapi.json").write_text(json.dumps({**SPEC, "paths": {}}))
    result = contract_project.runpytest_inprocess()
    result.assert_outcomes(passed=1, failed=1)
    result.stdout.fnmatch_lines(["*AssertionError*", "*BREAKING*"])
