import shutil
import subprocess

import pytest
import yaml

from api_contract import load_spec
from api_contract.cli import main
from api_contract.loaders.base import LoaderError

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def spec(total="number"):
    schema = {"type": "object", "properties": {"total": {"type": total}}, "required": ["total"]}
    return {
        "openapi": "3.0.3",
        "paths": {
            "/orders": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {"application/json": {"schema": schema}},
                        }
                    }
                }
            }
        },
    }


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    git(tmp_path, "init", "-q", "-b", "main")
    (tmp_path / "pyproject.toml").write_text('[tool.api-contract]\nsource = "file:openapi.yaml"\n')
    (tmp_path / "openapi.yaml").write_text(yaml.safe_dump(spec()))
    assert main(["snapshot"]) == 0
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-q", "-m", "base")
    return tmp_path


def test_against_reads_the_snapshot_from_the_revision(repo, capsys):
    # A branch that breaks the API and regenerates the snapshot to hide it.
    git(repo, "checkout", "-q", "-b", "feature")
    (repo / "openapi.yaml").write_text(yaml.safe_dump(spec(total="string")))
    assert main(["snapshot", "--force"]) == 0
    assert main(["check"]) == 0  # the working-tree snapshot was regenerated
    capsys.readouterr()
    assert main(["check", "--against", "main"]) == 1
    assert "type changed" in capsys.readouterr().out


def test_against_works_from_a_subdirectory(repo, monkeypatch):
    sub = repo / "pkg"
    sub.mkdir()
    monkeypatch.chdir(sub)
    assert main(["check", "--against", "HEAD"]) == 0


def test_changelog_against(repo, capsys):
    (repo / "openapi.yaml").write_text(yaml.safe_dump(spec(total="string")))
    capsys.readouterr()
    assert main(["changelog", "--against", "HEAD"]) == 0
    assert "Breaking changes" in capsys.readouterr().out


def test_against_errors(repo, capsys):
    assert main(["check", "--against", "no-such-branch"]) == 2
    assert "fetch" in capsys.readouterr().err
    (repo / "api-contract.toml").write_text('source = "file:openapi.yaml"\nsnapshot = "x.json"\n')
    assert main(["check", "--config", "api-contract.toml", "--against", "HEAD"]) == 2
    assert main(["check", "--against", "--bad"]) == 2


def test_git_source_reads_a_file_at_a_revision(repo):
    (repo / "openapi.yaml").write_text(yaml.safe_dump(spec(total="string")))
    old = load_spec("git:HEAD:openapi.yaml")
    assert (
        old["paths"]["/orders"]["get"]["responses"]["200"]["content"]["application/json"]["schema"][
            "properties"
        ]["total"]["type"]
        == "number"
    )
    assert main(["diff", "git:HEAD:openapi.yaml", "openapi.yaml"]) == 1
    with pytest.raises(LoaderError, match="git:<revision>:<path>"):
        load_spec("git:HEAD")
