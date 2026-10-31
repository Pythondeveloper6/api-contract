"""Time and memory for normalize + diff on generated specs of growing size.

    python benchmarks/bench.py                 # 100, 300, 1000 operations
    python benchmarks/bench.py --ops 2000 --repeat 5

Each spec is OpenAPI 3.1 with shared components, nested $refs, 3.1-style
nullables (``anyOf: [..., {type: null}]``), enums and a recursive component,
which is the shape a large FastAPI or DRF app produces. The "new" spec
changes one field type and adds one endpoint, so the diff has work to do.
Results go to stdout as a Markdown table; publish them in docs/performance.md.
"""

from __future__ import annotations

import argparse
import copy
import gc
import platform
import statistics
import sys
import time
import tracemalloc
from typing import Any

from api_contract import __version__, diff, normalize


def component(index: int, total: int) -> dict[str, Any]:
    props: dict[str, Any] = {
        "id": {"type": "integer"},
        "name": {"type": "string", "maxLength": 200},
        "note": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "status": {"type": "string", "enum": ["new", "active", "closed"]},
        "amount": {"type": "number", "format": "double"},
        "tags": {"type": "array", "items": {"type": "string"}},
    }
    # A chain of references into other components (a deep $ref graph).
    for hop in (1, 7, 31):
        target = (index + hop) % total
        if target > index:
            props[f"rel{hop}"] = {
                "anyOf": [{"$ref": f"#/components/schemas/Model{target}"}, {"type": "null"}]
            }
    return {"type": "object", "required": ["id", "name"], "properties": props}


def build_spec(operations: int) -> dict[str, Any]:
    resources = max(1, operations // 4)
    schemas = {f"Model{i}": component(i, resources) for i in range(resources)}
    schemas["Tree"] = {
        "type": "object",
        "properties": {
            "children": {"type": "array", "items": {"$ref": "#/components/schemas/Tree"}}
        },
    }
    paths: dict[str, Any] = {}
    for i in range(resources):
        ref = {"$ref": f"#/components/schemas/Model{i}"}
        ok = {"description": "ok", "content": {"application/json": {"schema": ref}}}
        many = {
            "description": "ok",
            "content": {"application/json": {"schema": {"type": "array", "items": ref}}},
        }
        error = {
            "description": "error",
            "content": {"application/json": {"schema": {"type": "object"}}},
        }
        body = {"required": True, "content": {"application/json": {"schema": ref}}}
        page = [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}}]
        item = [{"name": "item_id", "in": "path", "required": True, "schema": {"type": "integer"}}]
        paths[f"/api/r{i}/"] = {
            "get": {"parameters": page, "responses": {"200": many, "422": error}},
            "post": {"requestBody": body, "responses": {"201": ok, "422": error}},
        }
        paths[f"/api/r{i}/{{item_id}}/"] = {
            "get": {"parameters": item, "responses": {"200": ok, "404": error}},
            "patch": {"parameters": item, "requestBody": body, "responses": {"200": ok}},
        }
    paths["/api/tree/"] = {
        "get": {
            "responses": {
                "200": {
                    "description": "ok",
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Tree"}}
                    },
                }
            }
        }
    }
    return {
        "openapi": "3.1.0",
        "info": {"title": "bench", "version": "1"},
        "paths": paths,
        "components": {"schemas": schemas},
    }


def changed(spec: dict[str, Any]) -> dict[str, Any]:
    new = copy.deepcopy(spec)
    new["components"]["schemas"]["Model0"]["properties"]["amount"] = {"type": "string"}
    new["paths"]["/api/new/"] = {"get": {"responses": {"204": {"description": "ok"}}}}
    return new


def measure(operations: int, repeat: int) -> dict[str, Any]:
    old = build_spec(operations)
    new = changed(old)
    normalize_times, diff_times = [], []
    peak = 0
    changes: list[Any] = []
    for _ in range(repeat):
        gc.collect()
        tracemalloc.start()
        start = time.perf_counter()
        normalize(old)
        normalize_times.append(time.perf_counter() - start)
        start = time.perf_counter()
        changes = diff(old, new)
        diff_times.append(time.perf_counter() - start)
        peak = max(peak, tracemalloc.get_traced_memory()[1])
        tracemalloc.stop()
    real_ops = sum(len(item) for item in old["paths"].values())
    return {
        "operations": real_ops,
        "components": len(old["components"]["schemas"]),
        "normalize_s": statistics.median(normalize_times),
        "diff_s": statistics.median(diff_times),
        "peak_mib": peak / 2**20,
        "changes": len(changes),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ops", type=int, action="append", help="operations (repeatable)")
    parser.add_argument("--repeat", type=int, default=3)
    args = parser.parse_args(argv)
    sizes = args.ops or [100, 300, 1000]
    print(
        f"api-contract {__version__}, Python {platform.python_version()}, "
        f"{platform.system()} {platform.machine()}; median of {args.repeat} runs; "
        "peak memory measured with tracemalloc (adds overhead to the timings)\n"
    )
    print(
        "| Operations | Components | normalize (s) | diff incl. normalize (s) "
        "| Peak MiB | Changes |"
    )
    print("|---:|---:|---:|---:|---:|---:|")
    for size in sizes:
        r = measure(size, args.repeat)
        print(
            f"| {r['operations']} | {r['components']} | {r['normalize_s']:.3f} | "
            f"{r['diff_s']:.3f} | {r['peak_mib']:.1f} | {r['changes']} |"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
