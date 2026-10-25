"""Machine-readable report."""

from __future__ import annotations

import json
from typing import Any

from ..core import CheckResult
from ..model import Severity

REPORT_VERSION = 1


def as_dict(result: CheckResult) -> dict[str, Any]:
    return {
        "version": REPORT_VERSION,
        "ok": result.ok,
        "fail_on": result.fail_on.value,
        "summary": {
            "total": len(result.changes),
            **{s.value: result.count(s) for s in Severity},
            "allowed": sum(1 for c in result.changes if c.allowed),
            "failing": len(result.failing),
        },
        "changes": [c.to_dict() for c in result.changes],
        "allowlist": {
            "expired": [e.to_dict() for e in result.expired],
            "stale": [e.to_dict() for e in result.stale],
        },
    }


def render(result: CheckResult, **_: Any) -> str:
    return json.dumps(as_dict(result), indent=2, ensure_ascii=False, default=str) + "\n"
