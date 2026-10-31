"""``file:`` sources: a JSON/YAML file, or ``module:callable`` returning a dict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .._safety import load_yaml
from .base import BaseLoader, LoaderError, import_string

_SUFFIXES = {".json", ".yaml", ".yml"}


def read_document(path: Path) -> dict[str, Any]:
    """Parse a JSON or YAML file into a dict (YAML is a superset of JSON)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoaderError(f"cannot read {path}: {exc.strerror or exc}") from exc
    try:
        data = json.loads(text) if path.suffix == ".json" else load_yaml(text, str(path))
    except (ValueError, yaml.YAMLError) as exc:
        raise LoaderError(
            f"{path} is not valid {path.suffix.lstrip('.').upper() or 'YAML'}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise LoaderError(f"{path} does not contain an OpenAPI document (expected a mapping)")
    return data


class FileLoader(BaseLoader):
    """Loads ``openapi.json`` / ``openapi.yaml`` (relative to the working
    directory), or calls ``"pkg.module:build_schema"`` and uses the dict it returns.
    """

    def load(self) -> dict:
        target = self.target.strip()
        if not target:
            raise LoaderError("the file loader needs a path, e.g. 'file:openapi.json'")
        path = Path(target).expanduser()
        if path.exists() or path.suffix.lower() in _SUFFIXES or ":" not in target:
            if not path.exists():
                raise LoaderError(f"spec file not found: {path}")
            return read_document(path)
        try:
            obj = import_string(target)
        except ImportError as exc:
            raise LoaderError(str(exc)) from exc
        if callable(obj):
            obj = obj()
        if not isinstance(obj, dict):
            raise LoaderError(f"{target!r} did not produce a dict (got {type(obj).__name__})")
        return obj
