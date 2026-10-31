"""``api-contract-allow.yml``: acknowledged changes, each with a reason and an expiry.

```yaml
allow:
  - id: "GET /api/orders/{}:response:200:total:type-changed"
    reason: "Mobile 4.2+ reads total_display instead"
    expires: 2026-12-01
```

* An allowed change no longer fails the check (it is still reported).
* An entry past its ``expires`` date stops allowing anything and fails the
  check by itself, so acknowledgements can't quietly become permanent.
* An entry that matches no change is *stale*: reported as a warning.

Ids are compared after making path parameters positional, so an id copied
with real names (``GET /api/orders/{id}:...``) works too. ``*`` is a wildcard.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any

import yaml

from ._io import atomic_write_text
from .model import ApiContractError, Change, canonical_id


@dataclass
class AllowEntry:
    id: str
    reason: str
    expires: dt.date

    @property
    def pattern(self) -> str:
        return canonical_id(self.id)

    def matches(self, change: Change) -> bool:
        pattern = self.pattern
        if "*" in pattern:
            # fnmatch treats [] as a character class; ids use them for array items.
            return fnmatchcase(change.id, pattern.replace("[", "[[]"))
        return change.id == pattern

    def expired(self, today: dt.date) -> bool:
        return self.expires < today

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "reason": self.reason, "expires": self.expires.isoformat()}


@dataclass
class AllowlistResult:
    expired: list[AllowEntry]
    stale: list[AllowEntry]


def parse_date(value: Any, *, what: str = "expires") -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise ApiContractError(f"{what} must be a date like 2026-12-01, got {value!r}")


class _UniqueKeyLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys instead of keeping the last."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _ in node.value:
            try:
                key = self.construct_object(key_node, deep=True)
                hash(key)
            except Exception:  # noqa: BLE001 - let the normal path report odd keys
                continue
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}; merge the entries into one list",
                    key_node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _safe_load_unique(source: Any) -> Any:
    return yaml.load(source, Loader=_UniqueKeyLoader)  # noqa: S506 - SafeLoader subclass


def load_allowlist(path: Path) -> list[AllowEntry]:
    """Read the allowlist; a missing file is an empty allowlist."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8") as fh:  # a stream, so errors name the file
            data = _safe_load_unique(fh)
    except (OSError, yaml.YAMLError) as exc:
        raise ApiContractError(f"cannot read allowlist {path}: {exc}") from exc
    if data is None:
        return []
    items = data.get("allow") if isinstance(data, dict) else data
    if items is None:
        return []
    if not isinstance(items, list):
        raise ApiContractError(f"{path}: expected an 'allow:' list of entries")
    entries = []
    for index, item in enumerate(items, 1):
        where = f"{path} entry {index}"
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            raise ApiContractError(f"{where}: each entry needs an 'id' string")
        reason = item.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise ApiContractError(f"{where}: 'reason' is required")
        if "expires" not in item:
            raise ApiContractError(f"{where}: 'expires' is required (YYYY-MM-DD)")
        expires = parse_date(item["expires"], what=f"{where}: expires")
        entries.append(AllowEntry(id=item["id"], reason=reason, expires=expires))
    return entries


def apply_allowlist(
    changes: list[Change], entries: list[AllowEntry], today: dt.date | None = None
) -> AllowlistResult:
    """Mark changes acknowledged by a live entry; collect expired and stale entries."""
    today = today or dt.date.today()
    expired = [e for e in entries if e.expired(today)]
    live = [e for e in entries if not e.expired(today)]
    used: set[int] = set()
    for change in changes:
        for index, entry in enumerate(live):
            if entry.matches(change):
                change.allowed_by = entry
                used.add(index)
                break
    stale = [e for i, e in enumerate(live) if i not in used]
    return AllowlistResult(expired=expired, stale=stale)


def _entry_yaml(entry: AllowEntry, indent: str) -> str:
    dump = yaml.safe_dump(
        [{"id": entry.id, "reason": entry.reason, "expires": entry.expires}],
        sort_keys=False,
        allow_unicode=True,
        width=1000,
    )
    return "".join(indent + line + "\n" for line in dump.splitlines())


_HEADER = (
    "# Acknowledged API contract changes. An entry stops a change from failing\n"
    "# `api-contract check` until it expires. Add entries with `api-contract allow`.\n"
)


def add_entry(path: Path, entry: AllowEntry) -> None:
    """Append (or replace, for the same id) an entry, keeping the file's comments when possible."""
    entries = load_allowlist(path)
    replacing = any(canonical_id(e.id) == canonical_id(entry.id) for e in entries)
    if path.exists() and not replacing:
        text = path.read_text(encoding="utf-8")
        match = re.search(r"^(\s*)- ", text, re.MULTILINE)
        indent = match.group(1) if match else "  "
        if not text.endswith("\n"):
            text += "\n"
        if not re.search(r"^allow:", text, re.MULTILINE):
            text += "allow:\n"
        candidate = text + _entry_yaml(entry, indent)
        # Appending text is only safe when `allow:` is the last block; check
        # the result parses to exactly the old entries plus the new one.
        try:
            parsed = yaml.safe_load(candidate)
            ok = isinstance(parsed, dict) and len(parsed.get("allow") or []) == len(entries) + 1
        except yaml.YAMLError:
            ok = False
        if ok:
            atomic_write_text(path, candidate)
            return
    entries = [e for e in entries if canonical_id(e.id) != canonical_id(entry.id)] + [entry]
    body = yaml.safe_dump(
        {"allow": [{"id": e.id, "reason": e.reason, "expires": e.expires} for e in entries]},
        sort_keys=False,
        allow_unicode=True,
        width=1000,
        indent=2,
    )
    atomic_write_text(path, _HEADER + body)


def add_entries(path: Path, entries: list[AllowEntry]) -> None:
    """Add several entries (same id: the later one wins)."""
    for entry in entries:
        add_entry(path, entry)


def expiring(
    entries: list[AllowEntry], within: dt.timedelta, today: dt.date | None = None
) -> tuple[list[AllowEntry], list[AllowEntry]]:
    """``(already expired, expiring within the window)``, each sorted by date."""
    today = today or dt.date.today()
    expired = sorted((e for e in entries if e.expired(today)), key=lambda e: e.expires)
    soon = sorted(
        (e for e in entries if not e.expired(today) and e.expires <= today + within),
        key=lambda e: e.expires,
    )
    return expired, soon


def parse_duration(value: str) -> dt.timedelta:
    """``14d`` / ``2w`` / ``14`` (days) -> timedelta."""
    match = re.fullmatch(r"\s*(\d+)\s*([dw]?)\s*", value or "")
    if not match:
        raise ApiContractError(f"invalid duration {value!r} (use e.g. 14d or 2w)")
    days = int(match.group(1)) * (7 if match.group(2) == "w" else 1)
    return dt.timedelta(days=days)
