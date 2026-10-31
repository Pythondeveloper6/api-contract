"""The public Python API the CLI (and the Django management command) are built on."""

from __future__ import annotations

import contextlib
import datetime as dt
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._io import atomic_write_text
from .allowlist import AllowEntry, add_entries, apply_allowlist, load_allowlist
from .config import Config, load_config, parse_fail_on
from .coverage import warnings_for
from .diff import diff_documents
from .loaders.base import EXTRAS, Loader, LoaderError, get_loader, missing_dependency, parse_source
from .loaders.file import read_document
from .loaders.git import git_show, parse_document
from .model import ApiContractError, Change, Severity
from .normalize import (
    HANDLER,
    METHODS,
    RAW_PATH,
    check_snapshot_format,
    dump_snapshot,
    is_normalized,
)
from .normalize import normalize as _normalize
from .policy import apply_policies, apply_usage
from .rules import Rules
from .usage import read_usage

log = logging.getLogger("api_contract")


@contextlib.contextmanager
def timed(what: str) -> Iterator[None]:
    """Log how long a step took (``--verbose`` shows it)."""
    start = time.perf_counter()
    log.debug("%s ...", what)
    try:
        yield
    finally:
        log.info("%s took %.2fs", what, time.perf_counter() - start)


# Removed operations no longer exist in the new app, so there is nothing to attribute.
_UNATTRIBUTED = {"endpoint-removed", "method-removed"}


@dataclass
class CheckResult:
    changes: list[Change]
    fail_on: Severity = Severity.BREAKING
    expired: list[AllowEntry] = field(default_factory=list)
    stale: list[AllowEntry] = field(default_factory=list)
    # Things that make the result less trustworthy, e.g. an (almost) empty schema.
    warnings: list[str] = field(default_factory=list)

    @property
    def failing(self) -> list[Change]:
        return [
            c
            for c in self.changes
            if c.severity.rank >= (c.fail_on or self.fail_on).rank and not c.allowed
        ]

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
        with timed(f"loading {source if isinstance(source, str) else loader!r}"):
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
    changes, _, _ = _diff(old, new, rules=rules, loader=loader, ignore_keys=ignore_keys)
    return changes


def _diff(
    old: dict[str, Any],
    new: dict[str, Any],
    *,
    rules: Rules | dict[str, str] | None = None,
    loader: Loader | None = None,
    ignore_keys=None,
) -> tuple[list[Change], dict[str, Any], dict[str, Any]]:
    """Like :func:`diff`, also returning both normalized documents."""
    if not isinstance(rules, Rules):
        rules = Rules(rules)
    with timed("normalizing"):
        old_n = _normalize(old, ignore_keys=ignore_keys)
        new_n = _normalize(new, ignore_keys=ignore_keys)
    with timed("diffing"):
        changes = diff_documents(old_n, new_n, rules)
    log.info("%d change(s) found", len(changes))
    if loader is not None:
        with timed("attributing changes"):
            attribute(changes, loader)
    attribute_removed(changes, old_n)
    return changes, old_n, new_n


def evaluate(
    old: dict[str, Any],
    new: dict[str, Any],
    config: Config,
    *,
    loader: Loader | None = None,
    today: dt.date | None = None,
) -> tuple[list[Change], dict[str, Any]]:
    """Diff with the project's rules, then apply its policies (client profiles,
    frozen paths, sunsets). Returns the changes and the normalized new document."""
    changes, old_n, new_n = _diff(
        old, new, rules=config.make_rules(), loader=loader, ignore_keys=config.ignore_keys
    )
    apply_policies(
        changes,
        old_n,
        new_n,
        base_rules=config.rules,
        clients=config.clients,
        frozen=config.frozen,
        today=today,
    )
    return changes, new_n


def attribute_removed(changes: list[Change], old: dict[str, Any]) -> None:
    """Removed endpoints no longer exist in the app; name the handler the snapshot
    recorded for them, if it did."""
    for change in changes:
        if change.kind not in _UNATTRIBUTED or change.attribution or not change.path:
            continue
        op = ((old.get("paths") or {}).get(change.path) or {}).get((change.method or "").lower())
        handler = op.get(HANDLER) if isinstance(op, dict) else None
        if isinstance(handler, str) and handler:
            change.attribution = f"{handler} (removed)"


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


def read_snapshot(path: Path, *, against: str | None = None) -> dict[str, Any]:
    """Read the snapshot file, or (with ``against``) the file as committed at that
    git revision, e.g. ``origin/main``."""
    if against:
        with timed(f"reading {path.name} at {against}"):
            doc = parse_document(git_show(against, path), f"{against}:{path.name}")
        where = f"{path.name} at {against}"
    else:
        if not path.exists():
            raise ApiContractError(
                f"snapshot {path} not found; create it with `api-contract snapshot` and commit it"
            )
        doc = read_document(path)
        where = str(path)
    if not is_normalized(doc):
        raise ApiContractError(f"{where} is not an api-contract snapshot")
    check_snapshot_format(doc, where)
    return doc


class SnapshotRefused(ApiContractError):
    """``snapshot`` would silently approve failing changes; ``result`` lists them."""

    def __init__(self, result: CheckResult) -> None:
        self.result = result
        count = len(result.failing)
        super().__init__(
            f"refusing to overwrite the snapshot: {count} failing change(s) would be "
            'approved silently. Fix them, or re-run with --accept "<reason>" to record '
            "them in the allowlist (or --force to overwrite without a record)"
        )


def record_handlers(normalized: dict[str, Any], loader: Loader) -> None:
    """Store each operation's handler in the snapshot, so that when the endpoint is
    later removed the report can still say where it used to be."""
    attribute_op = getattr(loader, "attribute", None)
    if attribute_op is None:
        return
    for item in (normalized.get("paths") or {}).values():
        raw = item.get(RAW_PATH)
        for method in METHODS:
            op = item.get(method)
            if isinstance(op, dict) and raw:
                found = _safe_call(attribute_op, method.upper(), raw)
                if found:
                    op[HANDLER] = found


def snapshot(
    config: Config | None = None,
    *,
    source: str | None = None,
    output=None,
    accept: str | None = None,
    expires: dt.date | None = None,
    force: bool = False,
    today: dt.date | None = None,
) -> Path:
    """Write the normalized schema of ``source`` (default: the configured one).

    When a snapshot already exists, the new schema is checked against it first:
    changes that would fail ``check`` (and are not in the allowlist) make this
    raise :class:`SnapshotRefused`, because overwriting would approve them with
    no trace. ``accept="reason"`` records them in the allowlist (expiring on
    ``expires``, default in 30 days) and writes the snapshot; ``force=True``
    writes it anyway.
    """
    config = config or load_config()
    source = source or config.source
    if not source:
        raise ApiContractError("no source configured (set [tool.api-contract] source)")
    loader = resolve_loader(source, config)
    spec = _load(loader, source)
    path = Path(output) if output else config.snapshot
    with timed("normalizing"):
        normalized = _normalize(spec, ignore_keys=config.ignore_keys)
    record_handlers(normalized, loader)
    if path.exists() and not force:
        old = read_snapshot(path)
        changes, _ = evaluate(old, normalized, config, today=today)
        result = finish(changes, config, today=today)
        if result.failing:
            if not accept or not accept.strip():
                raise SnapshotRefused(result)
            today = today or dt.date.today()
            until = expires or today + dt.timedelta(days=30)
            add_entries(
                config.allowlist,
                [AllowEntry(id=c.id, reason=accept.strip(), expires=until) for c in result.failing],
            )
            log.info("recorded %d change(s) in %s", len(result.failing), config.allowlist)
    atomic_write_text(path, dump_snapshot(normalized))
    return path


def upgrade_snapshot(config: Config | None = None, *, path: Path | None = None) -> Path:
    """Rewrite an existing snapshot in the current snapshot format and normal form,
    without loading the app. Run it after upgrading api-contract."""
    config = config or load_config()
    path = Path(path) if path else config.snapshot
    doc = read_snapshot(path)
    atomic_write_text(path, dump_snapshot(_normalize(doc, ignore_keys=config.ignore_keys)))
    return path


def check(
    config: Config | None = None,
    *,
    source: str | Loader | None = None,
    fail_on: Severity | str | None = None,
    today: dt.date | None = None,
    against: str | None = None,
    usage: list[str | Path] | None = None,
    unused_severity: Severity | str | None = None,
) -> CheckResult:
    """Diff the current schema against the committed snapshot and apply the allowlist.

    ``against="origin/main"`` reads the snapshot as committed on that git
    revision instead of the working tree, so a snapshot regenerated in the
    same branch can't hide a break. ``usage`` is a list of access-log / JSON
    lines files (see :mod:`api_contract.usage`); with ``unused_severity``,
    changes to endpoints with no traffic are downgraded to it.
    """
    config = config or load_config()
    source = source or config.source
    if not source:
        raise ApiContractError("no source configured (set [tool.api-contract] source)")
    old = read_snapshot(config.snapshot, against=against)
    loader = resolve_loader(source, config)
    new = _load(loader, source)
    changes, new_n = evaluate(old, new, config, loader=loader, today=today)
    if usage:
        add_usage(changes, new_n, old, usage, unused_severity)
    result = finish(changes, config, fail_on=fail_on, today=today)
    result.warnings = warnings_for(new_n)
    return result


def add_usage(
    changes: list[Change],
    new_normalized: dict[str, Any],
    old: dict[str, Any],
    files: list[str | Path],
    unused_severity: Severity | str | None = None,
) -> None:
    """Annotate changes with traffic counts from ``files`` (and maybe downgrade)."""
    templates = set(new_normalized.get("paths") or {}) | set(old.get("paths") or {})
    with timed("reading usage"):
        sample = read_usage(files, templates)
    log.info("usage: %d request line(s), %d matched no endpoint", sample.lines, sample.unmatched)
    if sample.lines == 0:
        raise ApiContractError(
            "the usage files contain no recognizable requests (expected access-log lines "
            "or JSON lines with a method and a path)"
        )
    severity = Severity(unused_severity) if unused_severity is not None else None
    apply_usage(changes, dict(sample.hits), unused_severity=severity)


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
