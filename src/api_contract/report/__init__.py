"""Report renderers. Each module exposes ``render(result, *, command, today) -> str``."""

from __future__ import annotations

from collections.abc import Callable

from . import json, markdown, text

FORMATS: dict[str, Callable[..., str]] = {
    "text": text.render,
    "markdown": markdown.render,
    "json": json.render,
}

__all__ = ["FORMATS"]
