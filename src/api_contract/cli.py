"""``api-contract`` command line: init | snapshot | check | diff | allow | changelog |
coverage | explain | expiring | import-oasdiff.

Exit codes: 0 no failing changes, 1 failing changes (or an expired allowlist
entry), 2 configuration or load error.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

from . import __version__
from ._io import atomic_write_text
from .allowlist import (
    AllowEntry,
    add_entries,
    add_entry,
    expiring,
    load_allowlist,
    parse_date,
    parse_duration,
)
from .changelog import render_changelog
from .config import Config, load_config
from .core import (
    SnapshotRefused,
    check,
    evaluate,
    finish,
    load_spec,
    read_snapshot,
    resolve_loader,
    snapshot,
    upgrade_snapshot,
)
from .model import ApiContractError, Severity, canonical_id
from .report import FORMATS

EXIT_OK, EXIT_FAILED, EXIT_ERROR = 0, 1, 2


def build_parser(prog: str = "api-contract") -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--config", metavar="PATH", help="pyproject.toml or api-contract.toml")
    common.add_argument("--source", help='override the configured source, e.g. "file:openapi.json"')
    common.add_argument(
        "--verbose",
        "-v",
        action="count",
        default=0,
        help="log progress and timings to stderr (-vv for debug detail)",
    )

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

    p = sub.add_parser("init", parents=[common], help="set up api-contract in this project")
    p.add_argument("--no-snapshot", action="store_true", help="do not write the first snapshot")
    p.add_argument("--no-workflow", action="store_true", help="do not write a GitHub workflow")
    p.add_argument("--pre-commit", action="store_true", help="also add a pre-commit hook")

    p = sub.add_parser("snapshot", parents=[common], help="write the normalized schema snapshot")
    p.add_argument("--output", "-o", metavar="FILE", help="default: the configured snapshot path")
    p.add_argument(
        "--accept",
        metavar="REASON",
        help="approve failing changes: record them in the allowlist with this reason",
    )
    p.add_argument(
        "--expires",
        metavar="YYYY-MM-DD",
        help="expiry for entries written by --accept (default: in 30 days)",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="overwrite even if failing changes would be approved without a record",
    )
    p.add_argument(
        "--upgrade",
        action="store_true",
        help="rewrite the existing snapshot in the current format, without loading the app",
    )

    p = sub.add_parser(
        "check", parents=[common, report], help="diff the current schema against the snapshot"
    )
    p.add_argument(
        "--against",
        metavar="REV",
        help="read the snapshot as committed at this git revision (e.g. origin/main)",
    )
    p.add_argument(
        "--usage",
        metavar="FILE",
        action="append",
        help="access log or JSON-lines traffic sample; adds request counts (repeatable)",
    )
    p.add_argument(
        "--unused-severity",
        choices=[s.value for s in Severity],
        help="with --usage: downgrade changes to endpoints with no traffic to this severity",
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
    p.add_argument("--against", metavar="REV", help="use the snapshot as committed at REV")

    p = sub.add_parser(
        "coverage", parents=[common], help="how much of the API the schema describes"
    )
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument(
        "--min-typed",
        type=float,
        metavar="PCT",
        help="exit 1 if fewer operations than this declare a typed success response",
    )
    p.add_argument(
        "--min-errors",
        type=float,
        metavar="PCT",
        help="exit 1 if fewer operations than this declare an error response",
    )

    p = sub.add_parser(
        "explain", parents=[common], help="what a change kind means and how to ship it safely"
    )
    p.add_argument("target", help="a change kind (response-field-removed) or a change id")

    p = sub.add_parser(
        "expiring", parents=[common], help="allowlist entries that expired or expire soon"
    )
    p.add_argument("--within", default="14d", help="look-ahead window, e.g. 14d or 2w")
    p.add_argument("--format", choices=["text", "json", "slack"], default="text")
    p.add_argument("--allowlist", metavar="PATH", help="default: the configured allowlist")
    p.add_argument("--fail", action="store_true", help="exit 1 if any entry is listed")

    p = sub.add_parser(
        "verify-samples",
        parents=[common],
        help="check recorded responses against the contract (runtime sampling)",
    )
    p.add_argument("samples", nargs="+", help="JSON-lines samples or HAR files")
    p.add_argument("--against", metavar="REV", help="use the snapshot as committed at REV")
    p.add_argument("--format", choices=["text", "json"], default="text")
    p.add_argument(
        "--fail-undocumented",
        action="store_true",
        help="also exit 1 for samples whose endpoint is not in the contract",
    )

    p = sub.add_parser(
        "import-oasdiff", parents=[common], help="convert oasdiff ignore/severity files"
    )
    p.add_argument("--err-ignore", metavar="FILE", help="oasdiff --err-ignore file")
    p.add_argument("--severity-levels", metavar="FILE", help="oasdiff --severity-levels file")
    p.add_argument("--reason", help="reason for imported allowlist entries")
    p.add_argument("--expires", metavar="YYYY-MM-DD", help="expiry for imported entries")
    p.add_argument(
        "--write",
        action="store_true",
        help="add the entries to the allowlist instead of printing them",
    )
    return parser


def _write(text: str, output: str | None) -> None:
    if output:
        atomic_write_text(Path(output), text)
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
    if args.upgrade:
        path = upgrade_snapshot(config, path=Path(args.output) if args.output else None)
        print(f"Upgraded {path}")
        return EXIT_OK
    if args.expires and not args.accept:
        raise ApiContractError("--expires only applies together with --accept")
    expires = parse_date(args.expires) if args.expires else None
    try:
        path = snapshot(
            config,
            source=_source(args, config),
            output=args.output,
            accept=args.accept,
            expires=expires,
            force=args.force,
        )
    except SnapshotRefused as exc:
        sys.stdout.write(FORMATS["text"](exc.result, command=prog))
        print(f"{prog}: {exc}", file=sys.stderr)
        return EXIT_FAILED
    if args.accept:
        print(f"Recorded accepted changes in {config.allowlist}")
    print(f"Wrote {path}")
    return EXIT_OK


def _cmd_check(args: argparse.Namespace, config: Config, prog: str) -> int:
    if args.unused_severity and not args.usage:
        raise ApiContractError("--unused-severity needs --usage")
    result = check(
        config,
        source=_source(args, config),
        fail_on=args.fail_on,
        against=args.against,
        usage=args.usage,
        unused_severity=args.unused_severity,
    )
    for warning in result.warnings:
        print(f"{prog}: warning: {warning}", file=sys.stderr)
    _write(FORMATS[args.format](result, command=prog, group=not args.no_group), args.output)
    return result.exit_code


def _cmd_diff(args: argparse.Namespace, config: Config, prog: str) -> int:
    old = load_spec(args.old, config=config)
    loader = resolve_loader(args.new, config)
    new = load_spec(loader)
    changes, _ = evaluate(old, new, config, loader=loader)
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
        old = read_snapshot(config.snapshot, against=args.against)
        new = load_spec(_source(args, config), config=config)
    else:
        if args.against:
            raise ApiContractError("--against replaces OLD; pass one or the other")
        old = load_spec(args.old, config=config)
        new = load_spec(args.new, config=config)
    changes, _ = evaluate(old, new, config)
    _write(render_changelog(changes, title=args.title), args.output)
    return EXIT_OK


def _cmd_init(args: argparse.Namespace, config: Config, prog: str) -> int:
    from .init import detect, write_config, write_pre_commit, write_workflow

    root = config.path.resolve().parent if config.path else Path.cwd()
    found = detect(root)
    source = args.source or config.source or found.source
    if not source:
        raise ApiContractError(
            "could not detect the framework; pass --source, e.g. "
            "'fastapi:app.main:app', 'flask:app:create_app', 'django' or 'file:openapi.json'"
        )
    print(f"Source: {source}" + (f" (detected {found.framework})" if not args.source else ""))
    for note in found.notes:
        print(f"Note: {note}")
    path, changed = write_config(root, source)
    print(f"{'Wrote' if changed else 'Kept existing'} [tool.api-contract] in {path}")
    status = EXIT_OK
    if not args.no_snapshot:
        config = load_config(path)
        if config.snapshot.exists():
            print(f"Kept existing snapshot {config.snapshot}")
        else:
            try:
                print(f"Wrote {snapshot(config, source=source)}; commit it")
            except ApiContractError as exc:
                print(f"{prog}: could not take the first snapshot: {exc}", file=sys.stderr)
                print("Fix the source, then run `api-contract snapshot`.", file=sys.stderr)
                status = EXIT_ERROR
    if not args.no_workflow:
        path, changed = write_workflow(root, found.extra)
        print(f"{'Wrote' if changed else 'Kept existing'} {path}")
    if args.pre_commit:
        path, changed = write_pre_commit(root)
        print(f"{'Added the hook to' if changed else 'Hook already in'} {path}")
    return status


def _cmd_coverage(args: argparse.Namespace, config: Config, prog: str) -> int:
    from .coverage import measure, render_text
    from .normalize import normalize

    doc = normalize(load_spec(_source(args, config), config=config), ignore_keys=config.ignore_keys)
    cov = measure(doc)
    if args.format == "json":
        sys.stdout.write(json.dumps(cov.to_dict(), indent=2) + "\n")
    else:
        sys.stdout.write(render_text(cov))
    failed = []
    if args.min_typed is not None and cov.typed_pct < args.min_typed:
        failed.append(f"typed responses {cov.typed_pct:.1f}% < {args.min_typed:g}%")
    if args.min_errors is not None and cov.errors_pct < args.min_errors:
        failed.append(f"declared errors {cov.errors_pct:.1f}% < {args.min_errors:g}%")
    for message in failed:
        print(f"{prog}: coverage too low: {message}", file=sys.stderr)
    return EXIT_FAILED if failed else EXIT_OK


def _cmd_explain(args: argparse.Namespace, config: Config, prog: str) -> int:
    from .explain import explain

    sys.stdout.write(explain(args.target, rules=config.make_rules()))
    return EXIT_OK


def _cmd_expiring(args: argparse.Namespace, config: Config, prog: str) -> int:
    path = Path(args.allowlist) if args.allowlist else config.allowlist
    expired, soon = expiring(load_allowlist(path), parse_duration(args.within))
    if args.format == "json":
        data = {
            "allowlist": str(path),
            "expired": [e.to_dict() for e in expired],
            "expiring": [e.to_dict() for e in soon],
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        bullet = "\u2022" if args.format == "slack" else "-"
        code = "`" if args.format == "slack" else ""
        if not expired and not soon:
            lines = [f"No allowlist entries expire within {args.within}."]
        else:
            lines = [f"API contract allowlist ({path.name}):"]
            for entry in expired:
                lines.append(
                    f"{bullet} {code}{entry.id}{code} EXPIRED {entry.expires.isoformat()} "
                    f"(fails the check): {entry.reason}"
                )
            for entry in soon:
                days = (entry.expires - dt.date.today()).days
                lines.append(
                    f"{bullet} {code}{entry.id}{code} expires {entry.expires.isoformat()} "
                    f"(in {days} days): {entry.reason}"
                )
        if args.format == "slack":
            sys.stdout.write(json.dumps({"text": "\n".join(lines)}) + "\n")
        else:
            sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_FAILED if args.fail and (expired or soon) else EXIT_OK


def _cmd_import_oasdiff(args: argparse.Namespace, config: Config, prog: str) -> int:
    from .oasdiff import (
        import_err_ignore,
        import_severity_levels,
        render_allowlist_yaml,
        render_rules_toml,
    )

    if not args.err_ignore and not args.severity_levels:
        raise ApiContractError("pass --err-ignore FILE and/or --severity-levels FILE")
    if args.severity_levels:
        text = _read_text(args.severity_levels)
        rules, unmapped = import_severity_levels(text)
        sys.stdout.write("# Add to pyproject.toml:\n" + render_rules_toml(rules))
        for check_id in unmapped:
            print(f"{prog}: no equivalent for oasdiff check {check_id!r}", file=sys.stderr)
    if args.err_ignore:
        if not args.reason or not args.expires:
            raise ApiContractError("--err-ignore needs --reason and --expires")
        entries, skipped = import_err_ignore(
            _read_text(args.err_ignore), reason=args.reason, expires=parse_date(args.expires)
        )
        for number in skipped:
            print(f"{prog}: {args.err_ignore}:{number}: not 'METHOD /path ...'", file=sys.stderr)
        if args.write:
            add_entries(config.allowlist, entries)
            print(f"Added {len(entries)} entries to {config.allowlist}")
        else:
            sys.stdout.write("# api-contract-allow.yml:\n" + render_allowlist_yaml(entries))
    return EXIT_OK


def _cmd_verify_samples(args: argparse.Namespace, config: Config, prog: str) -> int:
    from .normalize import normalize
    from .sampling import read_samples, render_report, verify_samples

    if args.source:
        contract = normalize(load_spec(args.source, config=config), ignore_keys=config.ignore_keys)
    else:
        contract = read_snapshot(config.snapshot, against=args.against)
    samples = [s for path in args.samples for s in read_samples(path)]
    report = verify_samples(contract, samples)
    if args.format == "json":
        data = {
            "ok": report.ok,
            "checked": report.checked,
            "problems": report.problems,
            "unmatched": report.unmatched,
        }
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
    else:
        sys.stdout.write(render_report(report))
    failed = not report.ok or (args.fail_undocumented and report.unmatched)
    return EXIT_FAILED if failed else EXIT_OK


def _read_text(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise ApiContractError(f"cannot read {path}: {exc.strerror or exc}") from exc


class _StderrHandler(logging.StreamHandler):  # type: ignore[type-arg,unused-ignore]
    """Writes to whatever ``sys.stderr`` is at the time (it may be swapped)."""

    @property  # type: ignore[override,unused-ignore]
    def stream(self):  # noqa: D401
        return sys.stderr

    @stream.setter
    def stream(self, value) -> None:
        pass


_COMMANDS = {
    "init": _cmd_init,
    "snapshot": _cmd_snapshot,
    "check": _cmd_check,
    "diff": _cmd_diff,
    "allow": _cmd_allow,
    "changelog": _cmd_changelog,
    "coverage": _cmd_coverage,
    "explain": _cmd_explain,
    "expiring": _cmd_expiring,
    "import-oasdiff": _cmd_import_oasdiff,
    "verify-samples": _cmd_verify_samples,
}


def _configure_logging(verbosity: int) -> None:
    if not verbosity:
        return
    logger = logging.getLogger("api_contract")
    if not any(isinstance(h, _StderrHandler) for h in logger.handlers):
        handler = _StderrHandler()
        handler.setFormatter(logging.Formatter("api-contract: %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbosity > 1 else logging.INFO)


def main(argv: list[str] | None = None, *, prog: str = "api-contract") -> int:
    """Run the CLI and return its exit code (it never calls ``sys.exit`` itself,
    so wrappers such as the Django management command can reuse it)."""
    parser = build_parser(prog)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else EXIT_ERROR
    _configure_logging(getattr(args, "verbose", 0))
    try:
        config = load_config(args.config)
        return _COMMANDS[args.command](args, config, prog)
    except ApiContractError as exc:
        print(f"{prog}: error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
