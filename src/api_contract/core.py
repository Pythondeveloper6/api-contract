"""The public Python API the CLI (and the Django management command) are built on."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .allowlist import AllowEntry, apply_allowlist, load_allowlist
from .config import Config, load_config, parse_fail_on
from .diff import diff_documents
from .loaders.base import EXTRAS, Loader, LoaderError, get_loader, missing_dependency, parse_source
from .loaders.file import read_document
from .model import ApiContractError, Change, Severity
from .normalize import dump_snapshot, is_normalized
from .normalize import normalize as _normalize
from .rules import Rules

# Removed operations no longer exist in the new app, so there is nothing to attribute.
_UNATTRIBUTED = {"endpoint-removed", "method-removed"}


@dataclass
class CheckResult:
    changes: list[Change]
    fail_on: Severity = Severity.BREAKING
    expired: list[AllowEntry] = field(default_factory=list)
    stale: list[AllowEntry] = field(default_factory=list)

    @property
    def failing(self) -> list[Change]:
        return [c for c in self.changes if c.severity.rank >= self.fail_on.rank and not c.allowed]

    @property
    def ok(self) -> bool:
        return not self.failing and not self.expired

    @property
    def exit_code(self) -> int:
        return 0 if self.ok else 1

    def count(self, severity: Severity) -> int:
        return sum(1 for c in self.changes if c.severity is severity)


def resolve_loader(source: str | Loader, config: Config | None = None) -> Loader:
    """A loader instance for a source string (or the loader itself)."""
    if not isinstance(source, str):
        return source
    kind, target = parse_source(source)
    if kind == "file" and config is not None and config.path is not None and target:
        # Spec paths in a config file are relative to that file, like snapshot/allowlist.
        candidate = config.path.resolve().parent / target
        if not Path(target).is_absolute() and candidate.exists():
            return get_loader(f"file:{candidate}")
    return get_loader(source)


def load_spec(source: str | Loader, *, config: Config | None = None) -> dict[str, Any]:
    """Load the raw OpenAPI document for a source (``"file:openapi.yaml"``, a loader...)."""
    loader = resolve_loader(source, config)
    return _load(loader, source)


def _load(loader: Loader, source: Any) -> dict[str, Any]:
    try:
        doc = loader.load()
    except ApiContractError:
        raise
    except ModuleNotFoundError as exc:
        kind = parse_source(source)[0] if isinstance(source, str) else ""
        if kind in EXTRAS:
            raise missing_dependency(kind, exc) from exc
        raise LoaderError(f"loading {source!r} failed: {exc}") from exc
    except Exception as exc:
        raise LoaderError(f"loading {source!r} failed: {type(exc).__name__}: {exc}") from exc
    if not isinstance(doc, dict):
        raise LoaderError(f"{loader!r}.load() returned {type(doc).__name__}, expected a dict")
    return doc


def normalize(spec: dict[str, Any], *, ignore_keys=None) -> dict[str, Any]:
    """Canonical form of an OpenAPI document; see :mod:`api_contract.normalize`."""
    return _normalize(spec, ignore_keys=ignore_keys)


def diff(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    rules: Rules | dict[str, str] | None = None,
    loader: Loader | None = None,
    ignore_keys=None,
) -> list[Change]:
    """Changes from ``old`` to ``new`` (raw specs or snapshots), worst first.

    ``loader`` is the new spec's loader; when given, each change is attributed
    to the code behind it.
    """
    if not isinstance(rules, Rules):
        rules = Rules(rules)
    changes = diff_documents(
        _normalize(old, ignore_keys=ignore_keys), _normalize(new, ignore_keys=ignore_keys), rules
    )
    if loader is not None:
        attribute(changes, loader)
    return changes


def _safe_call(func: Any, *args: Any) -> str | None:
    if func is None:
        return None
    try:
        result = func(*args)
    except Exception:
        # Attribution is a nicety; a loader bug must never fail the check.
        return None
    return result if isinstance(result, str) and result else None


def attribute(changes: list[Change], loader: Loader) -> None:
    """Fill ``Change.attribution``: the schema's code (e.g. a serializer) when the
    change sits inside a named component, else the operation's handler."""
    by_operation: dict[tuple[str, str], str | None] = {}
    by_component: dict[str, str | None] = {}
    attribute_schema = getattr(loader, "attribute_schema", None)
    for change in changes:
        if change.kind in _UNATTRIBUTED or not change.method or not change.raw_path:
            continue
        found = None
        if change.component:
            if change.component not in by_component:
                by_component[change.component] = _safe_call(attribute_schema, change.component)
            found = by_component[change.component]
        if found is None:
            key = (change.method, change.raw_path)
            if key not in by_operation:
                by_operation[key] = _safe_call(
                    getattr(loader, "attribute", None), change.method, change.raw_path
                )
            found = by_operation[key]
        change.attribution = found


def read_snapshot(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ApiContractError(
            f"snapshot {path} not found; create it with `api-contract snapshot` and commit it"
        )
    doc = read_document(path)
    if not is_normalized(doc):
        raise ApiContractError(f"{path} is not an api-contract snapshot")
    return doc


def snapshot(config: Config | None = None, *, source: str | None = None, output=None) -> Path:
    """Write the normalized schema of ``source`` (default: the configured one)."""
    config = config or load_config()
    source = source or config.source
    if not source:
        raise ApiContractError("no source configured (set [tool.api-contract] source)")
    spec = load_spec(source, config=config)
    path = Path(output) if output else config.snapshot
    path.write_text(dump_snapshot(_normalize(spec, ignore_keys=config.ignore_keys)), "utf-8")
    return path


def check(
    config: Config | None = None,
    *,
    source: str | Loader | None = None,
    fail_on: Severity | str | None = None,
    today: dt.date | None = None,
) -> CheckResult:
    """Diff the current schema against the committed snapshot and apply the allowlist."""
    config = config or load_config()
    source = source or config.source
    if not source:
        raise ApiContractError("no source configured (set [tool.api-contract] source)")
    old = read_snapshot(config.snapshot)
    loader = resolve_loader(source, config)
    new = _load(loader, source)
    changes = diff(
        old, new, rules=config.make_rules(), loader=loader, ignore_keys=config.ignore_keys
    )
    return finish(changes, config, fail_on=fail_on, today=today)


def finish(
    changes: list[Change],
    config: Config,
    *,
    fail_on: Severity | str | None = None,
    today: dt.date | None = None,
    use_allowlist: bool = True,
) -> CheckResult:
    """Apply the allowlist and the failure threshold to a list of changes."""
    threshold = parse_fail_on(fail_on) if fail_on is not None else config.fail_on
    result = CheckResult(changes=changes, fail_on=threshold)
    if use_allowlist:
        outcome = apply_allowlist(changes, load_allowlist(config.allowlist), today)
        result.expired, result.stale = outcome.expired, outcome.stale
    return result
