import json

import pytest
import yaml

from api_contract import SnapshotRefused, check, load_config, snapshot, upgrade_snapshot
from api_contract.cli import main
from api_contract.loaders.base import LOADERS, BaseLoader
from api_contract.model import ApiContractError
from api_contract.normalize import HANDLER, SNAPSHOT_FORMAT


def spec(total="number", with_legacy=True):
    paths = {
        "/orders/{id}": {
            "get": {
                "responses": {
                    "200": {
                        "description": "ok",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "required": ["total"],
                                    "properties": {"total": {"type": total}},
                                }
                            }
                        },
                    }
                }
            }
        }
    }
    if with_legacy:
        paths["/legacy"] = {"get": {"responses": {"204": {"description": "gone"}}}}
    return {"openapi": "3.0.3", "info": {"title": "t", "version": "1"}, "paths": paths}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:openapi.yaml"\n')
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump(spec()))
    assert main(["snapshot"]) == 0
    return tmp_path


def test_snapshot_refuses_to_bless_a_breaking_change(project, capsys):
    before = (project / "api-contract.json").read_text()
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(total="string")))
    capsys.readouterr()
    assert main(["snapshot"]) == 1
    out, err = capsys.readouterr()
    assert "type changed" in out
    assert "--accept" in err
    assert (project / "api-contract.json").read_text() == before


def test_snapshot_accept_records_allowlist_entry(project):
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(total="string")))
    rc = main(["snapshot", "--accept", "v2 clients read total as text", "--expires", "2999-01-01"])
    assert rc == 0
    allow = yaml.safe_load((project / "api-contract-allow.yml").read_text())
    [entry] = allow["allow"]
    assert entry["id"] == "GET /orders/{}:response:200:total:type-changed"
    assert entry["reason"] == "v2 clients read total as text"
    assert str(entry["expires"]) == "2999-01-01"
    snap = json.loads((project / "api-contract.json").read_text())
    schema = snap["paths"]["/orders/{}"]["get"]["responses"]["200"]["content"]
    assert schema["application/json"]["schema"]["properties"]["total"]["type"] == "string"


def test_snapshot_force_and_safe_changes_need_no_flag(project):
    new = spec()
    new["paths"]["/new"] = {"get": {"responses": {"204": {"description": "ok"}}}}
    (project / "openapi.yaml").write_text(yaml.safe_dump(new))
    assert main(["snapshot"]) == 0  # an added endpoint is safe
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(with_legacy=False)))
    assert main(["snapshot", "--force"]) == 0
    assert not (project / "api-contract-allow.yml").exists()


def test_snapshot_already_allowed_change_is_not_refused(project):
    (project / "api-contract-allow.yml").write_text(
        "allow:\n  - id: 'GET /legacy:endpoint-removed'\n    reason: r\n    expires: 2999-01-01\n"
    )
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(with_legacy=False)))
    assert main(["snapshot"]) == 0


def test_python_api_raises_snapshot_refused(project):
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(with_legacy=False)))
    with pytest.raises(SnapshotRefused) as info:
        snapshot(load_config())
    assert [c.kind for c in info.value.result.failing] == ["endpoint-removed"]


def test_expires_without_accept_is_an_error(project):
    assert main(["snapshot", "--expires", "2999-01-01"]) == 2


def test_writes_leave_no_temporary_files(project):
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(with_legacy=False)))
    main(["snapshot", "--accept", "r"])
    leftovers = [p.name for p in project.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_upgrade_rewrites_snapshot_without_loading_the_app(project):
    path = project / "api-contract.json"
    data = json.loads(path.read_text())
    path.write_text(json.dumps(data))  # compact, as an older version might have written it
    (project / "openapi.yaml").unlink()  # the source is not needed
    assert main(["snapshot", "--upgrade"]) == 0
    assert path.read_text().startswith("{\n")
    assert json.loads(path.read_text()) == data
    assert upgrade_snapshot(load_config()) == path


def test_newer_snapshot_format_is_rejected(project, capsys):
    path = project / "api-contract.json"
    data = json.loads(path.read_text())
    data["x-api-contract"]["format"] = SNAPSHOT_FORMAT + 1
    path.write_text(json.dumps(data))
    assert main(["check"]) == 2
    assert "upgrade api-contract" in capsys.readouterr().err
    with pytest.raises(ApiContractError, match="snapshot format"):
        check(load_config())


class _HandlerLoader(BaseLoader):
    """Serves openapi.yaml from the cwd and names a handler for every operation."""

    def load(self):
        return yaml.safe_load(open("openapi.yaml"))

    def attribute(self, method, path):
        return f"views.{method.lower()}_{path.strip('/').split('/')[0]} (views.py:1)"


def test_removed_endpoint_is_attributed_from_the_snapshot(project, monkeypatch, capsys):
    monkeypatch.setitem(LOADERS, "handlers", f"{__name__}:_HandlerLoader")
    (project / "pyproject.toml").write_text('[tool.api-contract]\nsource = "handlers:x"\n')
    assert main(["snapshot", "--force"]) == 0
    snap = json.loads((project / "api-contract.json").read_text())
    assert snap["paths"]["/legacy"]["get"][HANDLER] == "views.get_legacy (views.py:1)"
    (project / "openapi.yaml").write_text(yaml.safe_dump(spec(with_legacy=False)))
    capsys.readouterr()
    assert main(["check"]) == 1
    assert "at: views.get_legacy (views.py:1) (removed)" in capsys.readouterr().out
