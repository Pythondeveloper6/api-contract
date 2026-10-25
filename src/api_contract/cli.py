"""``api-contract`` command line: snapshot | check | diff | allow | changelog.

Exit codes: 0 no failing changes, 1 failing changes (or an expired allowlist
entry), 2 configuration or load error.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .allowlist import AllowEntry, add_entry, parse_date
from .changelog import render_changelog
from .config import Config, load_config
from .core import check, diff, finish, load_spec, read_snapshot, resolve_loader, snapshot
from .model import ApiContractError, canonical_id
from .report import FORMATS

EXIT_OK, EXIT_FAILED, EXIT_ERROR = 0, 1, 2


def build_parser(prog: str = "api-contract") -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", help="pyproject.toml or api-contract.toml")
    common.add_argument("--source", help='override the configured source, e.g. "file:openapi.json"')

    report = argparse.ArgumentParser(add_help=False)
    report.add_argument("--format", choices=sorted(FORMATS), default="text")
    report.add_argument(
        "--fail-on",
        choices=["breaking", "potentially-breaking"],
        help="lowest severity that fails (default: config fail_on, else breaking)",
    )
    report.add_argument("--output", "-o", metavar="FILE", help="write the report here, not stdout")
    report.add_argument(
        "--no-group",
        action="store_true",
        help="text/markdown: list every change separately instead of grouping changes "
        "that differ only by endpoint or media type (json is never grouped)",
    )

    parser = argparse.ArgumentParser(
        prog=prog, description="Detect breaking changes between OpenAPI documents."
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("snapshot", parents=[common], help="write the normalized schema snapshot")
    p.add_argument("--output", "-o", metavar="FILE", help="default: the configured snapshot path")

    sub.add_parser(
        "check", parents=[common, report], help="diff the current schema against the snapshot"
    )

    p = sub.add_parser("diff", parents=[common, report], help="compare any two specs or snapshots")
    p.add_argument("old", help="file path or source string (e.g. fastapi:app.main:app)")
    p.add_argument("new", help="file path or source string")
    p.add_argument(
        "--allowlist", metavar="PATH", help="apply this allowlist (not applied by default)"
    )

    p = sub.add_parser("allow", parents=[common], help="acknowledge a change in the allowlist")
    p.add_argument("id", help="change id, as printed by check")
    p.add_argument("--reason", required=True)
    p.add_argument("--expires", required=True, metavar="YYYY-MM-DD")
    p.add_argument("--allowlist", metavar="PATH", help="default: the configured allowlist")

    p = sub.add_parser("changelog", parents=[common], help="consumer-facing changelog (Markdown)")
    p.add_argument("old", nargs="?", help="default: the snapshot")
    p.add_argument("new", nargs="?", help="default: the configured source")
    p.add_argument("--title", default="API changes")
    p.add_argument("--output", "-o", metavar="FILE")
    return parser


def _write(text: str, output: str | None) -> None:
    if output:
        Path(output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)


def _source(args: argparse.Namespace, config: Config) -> str:
    source = args.source or config.source
    if not source:
        raise ApiContractError(
            "no source configured: set `source` in [tool.api-contract] or pass --source"
        )
    return source


def _cmd_snapshot(args: argparse.Namespace, config: Config, prog: str) -> int:
    path = snapshot(config, source=_source(args, config), output=args.output)
    print(f"Wrote {path}")
    return EXIT_OK


def _cmd_check(args: argparse.Namespace, config: Config, prog: str) -> int:
    result = check(config, source=_source(args, config), fail_on=args.fail_on)
    _write(FORMATS[args.format](result, command=prog, group=not args.no_group), args.output)
    return result.exit_code


def _cmd_diff(args: argparse.Namespace, config: Config, prog: str) -> int:
    old = load_spec(args.old, config=config)
    loader = resolve_loader(args.new, config)
    new = load_spec(loader)
    changes = diff(
        old, new, rules=config.make_rules(), loader=loader, ignore_keys=config.ignore_keys
    )
    if args.allowlist:
        config.allowlist = Path(args.allowlist)
    result = finish(changes, config, fail_on=args.fail_on, use_allowlist=bool(args.allowlist))
    _write(FORMATS[args.format](result, command=prog, group=not args.no_group), args.output)
    return result.exit_code


def _cmd_allow(args: argparse.Namespace, config: Config, prog: str) -> int:
    path = Path(args.allowlist) if args.allowlist else config.allowlist
    if not args.reason.strip():
        raise ApiContractError("--reason must not be empty")
    entry = AllowEntry(
        id=canonical_id(args.id), reason=args.reason, expires=parse_date(args.expires)
    )
    add_entry(path, entry)
    print(f"Allowed {entry.id} until {entry.expires.isoformat()} in {path}")
    return EXIT_OK


def _cmd_changelog(args: argparse.Namespace, config: Config, prog: str) -> int:
    if (args.old is None) != (args.new is None):
        raise ApiContractError("changelog takes both OLD and NEW, or neither")
    if args.old is None:
        old = read_snapshot(config.snapshot)
        new = load_spec(_source(args, config), config=config)
    else:
        old = load_spec(args.old, config=config)
        new = load_spec(args.new, config=config)
    changes = diff(old, new, rules=config.make_rules(), ignore_keys=config.ignore_keys)
    _write(render_changelog(changes, title=args.title), args.output)
    return EXIT_OK


_COMMANDS = {
    "snapshot": _cmd_snapshot,
    "check": _cmd_check,
    "diff": _cmd_diff,
    "allow": _cmd_allow,
    "changelog": _cmd_changelog,
}


def main(argv: list[str] | None = None, *, prog: str = "api-contract") -> int:
    """Run the CLI and return its exit code (it never calls ``sys.exit`` itself,
    so wrappers such as the Django management command can reuse it)."""
    parser = build_parser(prog)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ERROR
    try:
        config = load_config(args.config)
        return _COMMANDS[args.command](args, config, prog)
    except ApiContractError as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
