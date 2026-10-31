"""``git:`` sources: a file as it was at a git revision.

``git:origin/main:openapi.yaml`` reads ``openapi.yaml`` from ``origin/main``
without touching the working tree. The path is relative to the current
directory (like ``git show REV:./path``), so it works from a sub-directory of
the repository too. ``check --against REV`` uses this to read the snapshot
from the target branch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import yaml

from .base import BaseLoader, LoaderError


def git_show(rev: str, path: str | Path, *, cwd: Path | None = None) -> str:
    """The content of ``path`` at ``rev``. Raises :class:`LoaderError`."""
    rel = Path(path)
    if rel.is_absolute():
        top = _git(["rev-parse", "--show-toplevel"], cwd=cwd).strip()
        try:
            spec = rel.resolve().relative_to(Path(top).resolve()).as_posix()
        except ValueError:
            raise LoaderError(f"{path} is outside the git repository {top}") from None
    else:
        spec = "./" + rel.as_posix()
    if rev.startswith("-"):
        raise LoaderError(f"invalid git revision {rev!r}")
    return _git(["show", f"{rev}:{spec}"], cwd=cwd)


def _git(args: list[str], *, cwd: Path | None = None) -> str:
    try:
        proc = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", check=False
        )
    except FileNotFoundError:
        raise LoaderError("git is not installed or not on PATH") from None
    if proc.returncode != 0:
        message = proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else "unknown error"
        hint = ""
        if "does not exist in" in message or "exists on disk, but not in" in message:
            hint = " (was the file committed on that revision?)"
        elif "invalid object name" in message or "unknown revision" in message:
            hint = " (in CI, fetch it first, e.g. actions/checkout with fetch-depth: 0)"
        raise LoaderError(f"git {' '.join(args)} failed: {message}{hint}")
    return proc.stdout


def parse_document(text: str, name: str) -> dict[str, Any]:
    try:
        data = json.loads(text) if name.endswith(".json") else yaml.safe_load(text)
    except (ValueError, yaml.YAMLError) as exc:
        raise LoaderError(f"{name} is not valid JSON/YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise LoaderError(f"{name} does not contain an OpenAPI document (expected a mapping)")
    return data


class GitLoader(BaseLoader):
    """``git:<rev>:<path>``; the revision may not contain ``:``."""

    def load(self) -> dict:
        rev, sep, path = self.target.partition(":")
        if not sep or not rev or not path:
            raise LoaderError(
                f"git source {self.target!r} must look like 'git:<revision>:<path>', "
                "e.g. 'git:origin/main:api-contract.json'"
            )
        return parse_document(git_show(rev, path), f"{rev}:{path}")
