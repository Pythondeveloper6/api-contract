"""Guards for untrusted input and output: specs from partners, pull requests or
recorded traffic are data, never trusted to be small, flat or printable."""

from __future__ import annotations

import re
from typing import Any

import yaml

from .model import ApiContractError

# A real OpenAPI document of thousands of operations is a few million nodes at
# most once YAML aliases are expanded; an alias bomb is billions.
MAX_DOCUMENT_NODES = 20_000_000


def check_document_size(data: Any, what: str) -> None:
    """Reject documents whose alias-expanded size explodes, or that contain a
    reference to themselves (both only possible through YAML aliases).

    Shared objects are measured once each (memoized by identity), so even an
    exponential alias bomb is measured in linear time.
    """
    sizes: dict[int, int] = {}
    active: set[int] = set()
    stack: list[tuple[Any, bool]] = [(data, False)]
    while stack:
        node, done = stack.pop()
        if not isinstance(node, (dict, list)):
            continue
        key = id(node)
        children = list(node.values()) if isinstance(node, dict) else node
        if done:
            active.discard(key)
            total = 1 + sum(sizes.get(id(c), 1) for c in children if isinstance(c, (dict, list)))
            sizes[key] = total
            if total > MAX_DOCUMENT_NODES:
                raise ApiContractError(
                    f"{what} is too large once its YAML aliases are expanded "
                    f"(more than {MAX_DOCUMENT_NODES:,} nodes)"
                )
            continue
        if key in sizes:
            continue
        if key in active:
            raise ApiContractError(f"{what} refers to itself through a YAML alias")
        active.add(key)
        stack.append((node, True))
        stack.extend((c, False) for c in children if isinstance(c, (dict, list)))


def load_yaml(source: Any, what: str, loader: type = yaml.SafeLoader) -> Any:
    """``yaml.load`` with a safe loader, then :func:`check_document_size`."""
    data = yaml.load(source, Loader=loader)  # noqa: S506 - always a SafeLoader (subclass)
    check_document_size(data, what)
    return data


# C0/C1 control characters other than tab. A newline inside a value could start
# a fake ``::error::`` workflow command in CI logs; ESC sequences could rewrite
# the terminal.
_CONTROL = re.compile(r"[\x00-\x08\x0a-\x1f\x7f-\x9f]")


def clean(text: str) -> str:
    """Escape control characters so one value stays on one printable line."""
    return _CONTROL.sub(lambda m: m.group().encode("unicode_escape").decode("ascii"), text)


_MD_SPECIAL = re.compile(r"([\\`*_\[\]<])")


def md_text(text: str) -> str:
    """Plain text for Markdown (a PR comment): no HTML, links or @mentions."""
    text = _MD_SPECIAL.sub(r"\\\1", clean(text))
    # A zero-width joiner keeps "@team" readable but stops it from notifying.
    return text.replace("@", "@‍")
