"""``manage.py api_contract <snapshot|check|diff|allow|changelog> ...``.

A thin wrapper over the core CLI. Django is already set up by manage.py, so the
loader sees an initialised app registry and does not call ``django.setup()``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

from django.core.management.base import BaseCommand

from api_contract.cli import main
from api_contract.config import load_config
from api_contract.model import ApiContractError

_NEEDS_SOURCE = {"snapshot", "check", "changelog", "coverage", "init"}


def _with_default_source(argv: list[str]) -> list[str]:
    """Add ``--source django`` when neither the CLI nor the config names a source.

    ``changelog OLD NEW`` and ``diff`` take explicit sources, so they are left alone.
    """
    if not argv or argv[0] not in _NEEDS_SOURCE or "--source" in argv:
        return argv
    if argv[0] == "changelog" and any(not a.startswith("-") for a in argv[1:]):
        return argv
    config_path = None
    if "--config" in argv and argv.index("--config") + 1 < len(argv):
        config_path = argv[argv.index("--config") + 1]
    try:
        if load_config(config_path).source:
            return argv
    except ApiContractError:
        return argv  # let the CLI report the config problem
    return [argv[0], "--source", "django", *argv[1:]]


class Command(BaseCommand):
    help = (
        "Detect breaking API changes. Commands: snapshot, check, diff, allow, changelog. "
        "Run `manage.py api_contract <command> --help` for the options of each command, "
        "for example `manage.py api_contract check --help`."
    )
    requires_system_checks: list[str] = []

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "cli_args",
            nargs=argparse.REMAINDER,
            metavar="command ...",
            help="A command and its options, e.g. `check --format markdown`.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        argv = list(options["cli_args"])
        code = main(_with_default_source(argv), prog="manage.py api_contract")
        if code:
            sys.exit(int(code))
