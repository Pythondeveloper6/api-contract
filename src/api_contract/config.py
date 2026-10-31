"""``[tool.api-contract]`` from ``pyproject.toml``, or a standalone ``api-contract.toml``."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .model import ApiContractError, Severity
from .normalize import DEFAULT_IGNORE_KEYS
from .policy import ClientProfile
from .rules import Rules

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on 3.10 in CI
    import tomli as tomllib  # type: ignore[import-not-found,unused-ignore]

CONFIG_FILES = ("api-contract.toml", "pyproject.toml")
_KEYS = {
    "source",
    "snapshot",
    "allowlist",
    "rules",
    "fail_on",
    "ignore_keys",
    "extra_ignore_keys",
    "frozen",
    "clients",
}
_CLIENT_KEYS = {"paths", "tags", "fail_on", "rules"}
_FAIL_ON = (Severity.BREAKING, Severity.POTENTIALLY_BREAKING)


@dataclass
class Config:
    source: str | None = None
    snapshot: Path = Path("api-contract.json")
    allowlist: Path = Path("api-contract-allow.yml")
    rules: dict[str, Severity] = field(default_factory=dict)
    fail_on: Severity = Severity.BREAKING
    ignore_keys: tuple[str, ...] = DEFAULT_IGNORE_KEYS
    # Path globs where every change fails (see api_contract.policy).
    frozen: tuple[str, ...] = ()
    clients: list[ClientProfile] = field(default_factory=list)
    # The directory relative paths were resolved against; None means defaults.
    path: Path | None = None

    def make_rules(self) -> Rules:
        return Rules(self.rules)


def parse_fail_on(value: Any) -> Severity:
    try:
        severity = Severity(value)
    except ValueError:
        severity = None
    if severity not in _FAIL_ON:
        choices = ", ".join(s.value for s in _FAIL_ON)
        raise ApiContractError(f"invalid fail_on {value!r} (choose from: {choices})")
    return severity


def find_config(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` to the first api-contract.toml, or pyproject.toml
    that has a ``[tool.api-contract]`` table."""
    directory = (start or Path.cwd()).resolve()
    for folder in (directory, *directory.parents):
        for name in CONFIG_FILES:
            candidate = folder / name
            if not candidate.is_file():
                continue
            if name == "api-contract.toml" or "api-contract" in _read(candidate).get("tool", {}):
                return candidate
    return None


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except OSError as exc:
        raise ApiContractError(f"cannot read {path}: {exc.strerror or exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ApiContractError(f"{path} is not valid TOML: {exc}") from exc


def load_config(path: str | Path | None = None, *, start: Path | None = None) -> Config:
    """Load configuration from ``path``, or discover it from ``start`` (the cwd).

    Relative ``snapshot`` / ``allowlist`` paths resolve against the config
    file's directory. With no config file at all, defaults apply relative to
    the working directory.
    """
    if path is None:
        found = find_config(start)
        if found is None:
            base = (start or Path.cwd()).resolve()
            return Config(
                snapshot=base / "api-contract.json", allowlist=base / "api-contract-allow.yml"
            )
        path = found
    path = Path(path)
    if not path.is_file():
        raise ApiContractError(f"config file not found: {path}")
    data = _read(path)
    table = data.get("tool", {}).get("api-contract")
    if table is None:
        # api-contract.toml may use bare keys, or the same [tool.api-contract] table.
        table = {} if path.name == "pyproject.toml" else data
    return config_from_dict(table, base=path.resolve().parent, origin=path)


def config_from_dict(table: dict[str, Any], *, base: Path, origin: Path | None = None) -> Config:
    where = f" in {origin}" if origin else ""
    unknown = sorted(set(table) - _KEYS)
    if unknown:
        raise ApiContractError(f"unknown api-contract setting(s){where}: {', '.join(unknown)}")

    source = table.get("source")
    if source is not None and not isinstance(source, str):
        raise ApiContractError(f"'source'{where} must be a string")

    def as_path(key: str, default: str) -> Path:
        value = table.get(key, default)
        if not isinstance(value, str):
            raise ApiContractError(f"{key!r}{where} must be a string path")
        return base / value

    rules_table = table.get("rules", {})
    if not isinstance(rules_table, dict):
        raise ApiContractError(f"'rules'{where} must be a table of kind = severity")
    rules = Rules(rules_table).overrides

    def key_list(key: str, default: list[str]) -> list[str]:
        value = table.get(key, default)
        if not isinstance(value, list) or not all(isinstance(k, str) for k in value):
            raise ApiContractError(f"'{key}'{where} must be a list of strings")
        return value

    # ``ignore_keys`` replaces the defaults; ``extra_ignore_keys`` adds to whatever
    # list is in effect, so the defaults (example, title, x-*) stay ignored.
    ignore = key_list("ignore_keys", list(DEFAULT_IGNORE_KEYS))
    extra = key_list("extra_ignore_keys", [])
    ignore = ignore + [k for k in extra if k not in ignore]

    clients = []
    clients_table = table.get("clients", {})
    if not isinstance(clients_table, dict):
        raise ApiContractError(f"'clients'{where} must be a table of [clients.<name>] tables")
    for name, spec in clients_table.items():
        label = f"clients.{name}"
        if not isinstance(spec, dict):
            raise ApiContractError(f"'{label}'{where} must be a table")
        unknown = sorted(set(spec) - _CLIENT_KEYS)
        if unknown:
            raise ApiContractError(f"unknown setting(s) in '{label}'{where}: {', '.join(unknown)}")
        paths = _str_list(spec, "paths", f"{label}.paths", where)
        tags = _str_list(spec, "tags", f"{label}.tags", where)
        if not paths and not tags:
            raise ApiContractError(f"'{label}'{where} needs 'paths' or 'tags'")
        client_rules = spec.get("rules", {})
        if not isinstance(client_rules, dict):
            raise ApiContractError(f"'{label}.rules'{where} must be a table of kind = severity")
        clients.append(
            ClientProfile(
                name=str(name),
                paths=tuple(paths),
                tags=tuple(tags),
                fail_on=parse_fail_on(spec["fail_on"]) if "fail_on" in spec else None,
                rules=Rules(client_rules).overrides,
            )
        )

    return Config(
        source=source,
        snapshot=as_path("snapshot", "api-contract.json"),
        allowlist=as_path("allowlist", "api-contract-allow.yml"),
        rules=rules,
        fail_on=parse_fail_on(table.get("fail_on", "breaking")),
        ignore_keys=tuple(ignore),
        frozen=tuple(_str_list(table, "frozen", "frozen", where)),
        clients=clients,
        path=origin,
    )


def _str_list(table: dict[str, Any], key: str, label: str, where: str) -> list[str]:
    value = table.get(key, [])
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ApiContractError(f"'{label}'{where} must be a list of strings")
    return value
