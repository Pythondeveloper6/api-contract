"""Large and deeply referenced specs: no false positives, no blow-up."""

import copy
import sys
import time
from pathlib import Path

import pytest

from api_contract import diff, normalize
from api_contract.normalize import RECURSIVE, REF

sys.path.insert(0, str(Path(__file__).parent.parent / "benchmarks"))
import bench  # noqa: E402


def test_large_31_spec_has_no_false_positives():
    spec = bench.build_spec(200)
    assert diff(spec, copy.deepcopy(spec)) == []
    # The same contract written the 3.0 way (nullable: true) is equal too.
    as_30 = copy.deepcopy(spec)
    as_30["openapi"] = "3.0.3"
    for schema in as_30["components"]["schemas"].values():
        for name, prop in list(schema.get("properties", {}).items()):
            variants = prop.get("anyOf")
            if variants and {"type": "null"} in variants:
                [real] = [v for v in variants if v != {"type": "null"}]
                if "$ref" in real:
                    schema["properties"][name] = {"allOf": [real], "nullable": True}
                else:
                    schema["properties"][name] = {**real, "nullable": True}
    assert diff(spec, as_30) == []


def test_large_spec_reports_exactly_the_real_changes():
    spec = bench.build_spec(200)
    changes = diff(spec, bench.changed(spec))
    kinds = sorted({c.kind for c in changes})
    assert kinds == ["endpoint-added", "type-changed"]
    assert all(c.path.startswith(("/api/r0/", "/api/new/")) for c in changes)


def test_deep_reference_dag_does_not_blow_up():
    # Each component references the next three: inlining it fully would be
    # exponential in the chain length.
    count = 14
    schemas = {
        f"M{i}": {
            "type": "object",
            "properties": {
                f"p{j}": {"$ref": f"#/components/schemas/M{i + j}"}
                for j in (1, 2, 3)
                if i + j < count
            },
        }
        for i in range(count)
    }
    spec = {
        "openapi": "3.0.3",
        "paths": {
            "/m": {
                "get": {
                    "responses": {
                        "200": {
                            "description": "",
                            "content": {
                                "application/json": {"schema": {"$ref": "#/components/schemas/M0"}}
                            },
                        }
                    }
                }
            }
        },
        "components": {"schemas": schemas},
    }
    start = time.perf_counter()
    snap = normalize(spec)
    assert time.perf_counter() - start < 10
    assert snap[RECURSIVE]  # some components are stored once
    changed = copy.deepcopy(spec)
    changed["components"]["schemas"][f"M{count - 1}"]["properties"] = {"x": {"type": "string"}}
    assert {c.kind for c in diff(spec, changed)} == {"response-field-added"}


@pytest.mark.parametrize("length", [300])
def test_long_reference_chain_stays_under_the_recursion_limit(length):
    schemas = {
        f"C{i}": {
            "type": "object",
            "properties": {"next": {"$ref": f"#/components/schemas/C{i + 1}"}}
            if i + 1 < length
            else {"leaf": {"type": "integer"}},
        }
        for i in range(length)
    }
    response = {
        "description": "",
        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/C0"}}},
    }
    spec = {
        "openapi": "3.0.3",
        "paths": {"/c": {"get": {"responses": {"200": response}}}},
        "components": {"schemas": schemas},
    }
    snap = normalize(spec)
    # Unused components are not stored; used ones are reachable from a marker.
    markers = str(snap["paths"])
    assert REF in markers or "leaf" in markers
    leaf_changed = copy.deepcopy(spec)
    leaf_changed["components"]["schemas"][f"C{length - 1}"]["properties"]["leaf"]["type"] = "string"
    [change] = diff(spec, leaf_changed)
    assert change.kind == "type-changed"


def test_small_specs_are_inlined_as_before():
    spec = bench.build_spec(8)
    assert normalize(spec)[RECURSIVE].keys() == {"Tree"}


def test_stored_components_do_not_depend_on_docs_only_edits():
    spec = bench.build_spec(200)
    edited = copy.deepcopy(spec)
    for schema in edited["components"]["schemas"].values():
        schema["description"] = "x" * 50
        for prop in schema.get("properties", {}).values():
            prop["title"] = "t"
    assert normalize(spec)[RECURSIVE].keys() == normalize(edited)[RECURSIVE].keys()
    assert diff(spec, edited) == []
