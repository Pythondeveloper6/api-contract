"""Regression tests for the security review (see docs/security.md)."""

import json
import time

import pytest
import yaml

from api_contract import ApiContractError, diff, load_spec
from api_contract.allowlist import load_allowlist
from api_contract.cli import main
from api_contract.core import CheckResult
from api_contract.report import FORMATS

BILLION_LAUGHS = """
openapi: 3.0.3
a: &a ["x", "x", "x", "x", "x", "x", "x", "x", "x", "x"]
b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a]
c: &c [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b]
d: &d [*c, *c, *c, *c, *c, *c, *c, *c, *c, *c]
e: &e [*d, *d, *d, *d, *d, *d, *d, *d, *d, *d]
f: &f [*e, *e, *e, *e, *e, *e, *e, *e, *e, *e]
g: &g [*f, *f, *f, *f, *f, *f, *f, *f, *f, *f]
h: &h [*g, *g, *g, *g, *g, *g, *g, *g, *g, *g]
paths:
  /a:
    get:
      responses:
        "200":
          description: ok
          content:
            application/json:
              schema:
                type: object
                x-bomb: *h
"""


def test_yaml_alias_bomb_is_rejected_quickly(tmp_path):
    path = tmp_path / "bomb.yaml"
    path.write_text(BILLION_LAUGHS)
    start = time.perf_counter()
    with pytest.raises(ApiContractError, match="too large"):
        load_spec(f"file:{path}")
    assert time.perf_counter() - start < 5


def test_recursive_yaml_alias_is_rejected(tmp_path):
    path = tmp_path / "loop.yaml"
    path.write_text("openapi: 3.0.3\npaths: &p\n  /a: *p\n")
    with pytest.raises(ApiContractError, match="refers to itself"):
        load_spec(f"file:{path}")


def test_ordinary_yaml_anchors_still_work(tmp_path):
    path = tmp_path / "ok.yaml"
    path.write_text(
        "openapi: 3.0.3\npaths:\n  /a:\n    get: &op\n      responses: {}\n  /b:\n    get: *op\n"
    )
    assert set(load_spec(f"file:{path}")["paths"]) == {"/a", "/b"}


def test_allowlist_alias_bomb_is_rejected(tmp_path):
    path = tmp_path / "allow.yml"
    path.write_text(BILLION_LAUGHS.replace("openapi: 3.0.3", "allow: []"))
    with pytest.raises(ApiContractError, match="too large"):
        load_allowlist(path)


def _spec(path="/a", enum=("a",)):
    schema = {"type": "string", "enum": list(enum)}
    return {
        "openapi": "3.0.3",
        "paths": {
            path: {
                "get": {
                    "responses": {
                        "200": {
                            "description": "",
                            "content": {"application/json": {"schema": schema}},
                        }
                    }
                }
            }
        },
    }


def test_text_report_cannot_inject_workflow_commands_or_terminal_escapes():
    hostile = "x\n::error::forged\x1b[31m"
    changes = diff(_spec(), _spec(enum=("a", hostile)))
    changes += diff(_spec(path="/a\n::warning::y"), {"openapi": "3.0.3", "paths": {}})
    for fmt in ("text", "markdown"):
        out = FORMATS[fmt](CheckResult(changes))
        assert "\x1b" not in out
        assert not any(line.startswith("::") for line in out.splitlines())
        assert "\\n::error::forged" in out


def test_markdown_report_neutralizes_mentions_and_html():
    changes = diff(_spec(), _spec(enum=("a", "@org/everyone <img src=x onerror=alert(1)>")))
    out = FORMATS["markdown"](CheckResult(changes))
    # Inside code spans and fences nothing is rendered or notified; check the rest.
    import re

    prose = re.sub(r"`[^`\n]*`", "", re.sub(r"```.*?```", "", out, flags=re.S))
    assert "@org/everyone" not in prose
    assert not re.search(r"(?<!\\)<img", prose)  # only escaped, so shown as text
    assert "@\u200dorg/everyone" in out


def test_deeply_nested_input_is_a_clean_error(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    nested = {"type": "object"}
    for _ in range(5000):
        nested = {"type": "array", "items": nested}
    spec = _spec()
    spec["paths"]["/a"]["get"]["responses"]["200"]["content"]["application/json"]["schema"] = nested
    (tmp_path / "deep.json").write_text(json.dumps(spec))
    assert main(["snapshot", "--source", "file:deep.json"]) == 2
    assert "nested too deeply" in capsys.readouterr().err


def test_init_workflow_passes_github_context_through_env(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "openapi.yaml").write_text("openapi: 3.0.3\npaths: {}\n")
    assert main(["init", "--no-snapshot"]) == 0
    workflow = yaml.safe_load((tmp_path / ".github/workflows/api-contract.yml").read_text())
    for step in workflow["jobs"]["api-contract"]["steps"]:
        assert "${{" not in step.get("run", "")
    assert workflow["permissions"] == {"contents": "read"}
