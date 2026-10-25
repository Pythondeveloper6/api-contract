"""Golden pairs: tests/golden/<case>/{old.json,new.json,expected.json}.

``expected.json`` lists the changes as ``{id, severity, message}``; cases whose
name starts with ``noise-`` must produce no changes at all.
"""

import json
from pathlib import Path

import pytest

from api_contract import DEFAULT_RULES, diff

GOLDEN = Path(__file__).parent / "golden"
CASES = sorted(p.name for p in GOLDEN.iterdir() if (p / "old.json").exists())


def _run(case: str) -> list[dict]:
    old = json.loads((GOLDEN / case / "old.json").read_text())
    new = json.loads((GOLDEN / case / "new.json").read_text())
    return [
        {"id": c.id, "severity": c.severity.value, "message": c.message} for c in diff(old, new)
    ]


@pytest.mark.parametrize("case", CASES)
def test_golden(case: str, request: pytest.FixtureRequest) -> None:
    actual = _run(case)
    expected_path = GOLDEN / case / "expected.json"
    if request.config.getoption("--update-golden"):
        expected_path.write_text(json.dumps(actual, indent=2) + "\n")
    expected = json.loads(expected_path.read_text())
    assert actual == expected
    if case.startswith("noise-"):
        assert actual == []


def test_golden_cases_cover_every_rule() -> None:
    seen = set()
    for case in CASES:
        for change in json.loads((GOLDEN / case / "expected.json").read_text()):
            seen.update(part for part in change["id"].split(":") if part in DEFAULT_RULES)
    assert sorted(set(DEFAULT_RULES) - seen) == []


def test_reversed_pairs_are_mirror_images() -> None:
    # Diffing new -> old must not crash and must find something wherever old -> new did.
    for case in CASES:
        old = json.loads((GOLDEN / case / "old.json").read_text())
        new = json.loads((GOLDEN / case / "new.json").read_text())
        assert bool(diff(new, old)) == bool(diff(old, new)), case
