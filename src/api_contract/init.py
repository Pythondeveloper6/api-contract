"""``api-contract init``: set a project up in one command.

Detects the framework from the project's dependency files and source, then
writes ``[tool.api-contract]``, the first snapshot, a GitHub Actions workflow
and (optionally) a pre-commit hook. Every step can be skipped or overridden,
and nothing that already exists is overwritten.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from ._io import atomic_write_text
from .model import ApiContractError

_SKIP_DIRS = {
    ".git",
    ".hg",
    ".tox",
    ".nox",
    "node_modules",
    "site-packages",
    "__pycache__",
    "build",
    "dist",
    "migrations",
}
_DEP_FILES = ("pyproject.toml", "setup.cfg", "setup.py", "Pipfile")
_APP_PATTERNS = (
    # (framework, regex for "name = Constructor(")
    ("fastapi", re.compile(r"^(\w+)\s*(?::\s*\w+\s*)?=\s*(?:fastapi\.)?FastAPI\(", re.M)),
    ("flask", re.compile(r"^(\w+)\s*(?::\s*\w+\s*)?=\s*(?:apiflask\.)?APIFlask\(", re.M)),
    ("flask", re.compile(r"^(\w+)\s*(?::\s*\w+\s*)?=\s*(?:flask_openapi3\.)?OpenAPI\(", re.M)),
    ("flask", re.compile(r"^(\w+)\s*(?::\s*\w+\s*)?=\s*(?:flask\.)?Flask\(", re.M)),
)
_FACTORY = re.compile(r"^def (create_app|make_app|app_factory)\(", re.M)

WORKFLOW = """\
name: API contract

on:
  pull_request:

permissions:
  contents: read

jobs:
  api-contract:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0   # --against needs the target branch
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip
      - name: Install
        run: |
          {install}
          pip install --pre "api-contract[{extra}]"
      - name: Check the API contract
        run: |
          set +e
          api-contract check --against "origin/${{{{ github.base_ref }}}}" \\
            --format markdown --output api-contract-report.md
          status=$?
          [ -f api-contract-report.md ] && cat api-contract-report.md >> "$GITHUB_STEP_SUMMARY"
          exit "$status"
"""

PRE_COMMIT = """\
  - repo: local
    hooks:
      - id: api-contract
        name: API contract
        entry: api-contract check
        language: system
        pass_filenames: false
        always_run: true
        stages: [pre-push]
"""


@dataclass
class Detection:
    framework: str | None = None
    source: str | None = None
    extra: str = "fastapi"
    notes: list[str] = field(default_factory=list)


def _dependency_text(root: Path) -> str:
    texts = []
    for name in _DEP_FILES:
        if (root / name).is_file():
            texts.append((root / name).read_text("utf-8", errors="replace"))
    for req in sorted(root.glob("requirements*.txt")):
        texts.append(req.read_text("utf-8", errors="replace"))
    return "\n".join(texts).lower()


def _python_files(root: Path, limit: int = 2000):
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if d not in _SKIP_DIRS and not d.startswith((".venv", "venv"))
        )
        for name in sorted(filenames):
            if name.endswith(".py"):
                yield Path(dirpath) / name
                count += 1
                if count >= limit:
                    return


def _module_name(root: Path, file: Path) -> str:
    rel = file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[0] == "src" and len(parts) > 1:
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def detect(root: Path) -> Detection:
    """Best guess at the framework and ``source`` for the project in ``root``."""
    deps = _dependency_text(root)
    found = Detection()
    if (root / "manage.py").is_file() or "django" in deps:
        if "django-ninja" in deps or "django_ninja" in deps:
            found.extra = "ninja"
        elif "drf-spectacular" in deps or "djangorestframework" in deps:
            found.extra = "django"
        else:
            found.extra = "django"
        found.framework, found.source = "django", "django"
        if "drf-spectacular" not in deps and "django-ninja" not in deps:
            found.notes.append(
                "Django detected, but neither drf-spectacular nor django-ninja: one of them "
                "must generate the schema"
            )
        return found
    for path in _python_files(root):
        try:
            text = path.read_text("utf-8", errors="replace")
        except OSError:
            continue
        for framework, pattern in _APP_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            module = _module_name(root, path)
            factory = _FACTORY.search(text)
            attr = factory.group(1) if factory and framework == "flask" else match.group(1)
            found.framework = framework
            found.source = f"{framework}:{module}:{attr}"
            if framework == "flask":
                found.extra = (
                    "apiflask"
                    if "apiflask" in text.lower()
                    else "flask-openapi3"
                    if "flask_openapi3" in text
                    else "smorest"
                    if "flask_smorest" in text or "flask-smorest" in deps
                    else "flask"
                )
                if found.extra == "flask":
                    found.source = f"flask-routes:{module}:{attr}"
                    found.notes.append(
                        "no OpenAPI library found for Flask: using the route inventory "
                        "(endpoints and methods only)"
                    )
            else:
                found.extra = "fastapi"
            return found
    for name in ("openapi.json", "openapi.yaml", "openapi.yml"):
        if (root / name).is_file():
            found.framework, found.source, found.extra = "file", f"file:{name}", ""
            return found
    return found


def _config_block(source: str) -> str:
    return f'[tool.api-contract]\nsource = "{source}"\n'


def write_config(root: Path, source: str) -> tuple[Path, bool]:
    """Add ``[tool.api-contract]`` to pyproject.toml (or write api-contract.toml).
    Returns the file and whether it was changed."""
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text("utf-8")
        if re.search(r"^\[tool\.api-contract\]", text, re.M):
            return pyproject, False
        sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
        atomic_write_text(pyproject, text + sep + _config_block(source))
        return pyproject, True
    standalone = root / "api-contract.toml"
    if standalone.is_file():
        return standalone, False
    atomic_write_text(standalone, _config_block(source))
    return standalone, True


def write_workflow(root: Path, extra: str) -> tuple[Path, bool]:
    path = root / ".github" / "workflows" / "api-contract.yml"
    if path.exists():
        return path, False
    install = (
        "pip install -r requirements.txt"
        if (root / "requirements.txt").is_file()
        else ("pip install -e .")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    extra_spec = extra or "fastapi"
    atomic_write_text(path, WORKFLOW.format(install=install, extra=extra_spec))
    return path, True


def write_pre_commit(root: Path) -> tuple[Path, bool]:
    path = root / ".pre-commit-config.yaml"
    if path.is_file():
        text = path.read_text("utf-8")
        if "id: api-contract" in text:
            return path, False
        if not re.search(r"^repos:", text, re.M):
            raise ApiContractError(f"{path} has no top-level 'repos:' list; add the hook by hand")
        atomic_write_text(path, text + ("" if text.endswith("\n") else "\n") + PRE_COMMIT)
        return path, True
    atomic_write_text(path, "repos:\n" + PRE_COMMIT)
    return path, True
