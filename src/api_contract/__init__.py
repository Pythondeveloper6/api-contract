"""api-contract: catch breaking API changes by diffing OpenAPI documents.

Public API (the CLI is a thin layer over it)::

    from api_contract import load_spec, normalize, diff, check

    changes = diff(load_spec("file:old.json"), load_spec("file:new.json"))
    result = check()            # snapshot vs configured source, allowlist applied
    result.exit_code            # 0 ok, 1 failing changes
"""

from .allowlist import AllowEntry
from .config import Config, load_config
from .core import (
    CheckResult,
    SnapshotRefused,
    attribute,
    check,
    diff,
    load_spec,
    normalize,
    snapshot,
    upgrade_snapshot,
)
from .loaders.base import BaseLoader, Loader, LoaderError, get_loader
from .model import ApiContractError, Change, Direction, Severity
from .rules import DEFAULT_RULES, Rules

__version__ = "0.1.0a1"

__all__ = [
    "DEFAULT_RULES",
    "AllowEntry",
    "ApiContractError",
    "BaseLoader",
    "Change",
    "CheckResult",
    "Config",
    "Direction",
    "Loader",
    "LoaderError",
    "Rules",
    "Severity",
    "SnapshotRefused",
    "__version__",
    "attribute",
    "check",
    "diff",
    "get_loader",
    "load_config",
    "load_spec",
    "normalize",
    "snapshot",
    "upgrade_snapshot",
]
