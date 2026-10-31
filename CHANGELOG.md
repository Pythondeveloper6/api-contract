# Changelog

All notable changes to api-contract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `api-contract init`: detects the framework, writes the config, the first
  snapshot and a GitHub Actions workflow (optionally a pre-commit hook).
- Composite GitHub Action (`action.yml`): checks against the base branch,
  writes the job summary and keeps one pull-request comment updated.
- pytest plugin: `pytest --api-contract` and the `api_contract_check` fixture.
- `check --against REV` and `changelog --against REV` read the snapshot from a
  git revision; a `git:<rev>:<path>` source loads any committed spec.
- Report formats `sarif`, `github` (workflow annotations) and `junit`.
- Swagger 2.0 documents are converted to OpenAPI 3.0 before diffing.
- Client profiles (`[[tool.api-contract.clients]]`), frozen paths (`frozen`)
  and `x-sunset` deprecation windows.
- `--usage` access logs or traffic samples: request counts per change, with
  `--unused-severity` to downgrade changes to unused endpoints.
- New commands: `coverage`, `explain`, `expiring`, `verify-samples` and
  `import-oasdiff`.
- `snapshot --upgrade` rewrites an old snapshot in the current format; the
  snapshot records each operation's handler so removals stay attributed.
- FastAPI mounted sub-applications are merged into the loaded schema.
- `flask-routes:` source: an inventory of plain Flask routes; Flask schema
  attribution from marshmallow or pydantic classes.
- `-v/--verbose` logging with timings; warnings when the schema has no
  operations or no typed responses.
- Python 3.14 support; mypy configuration; a benchmark (`benchmarks/bench.py`).
- Docs: troubleshooting, stability policy, performance, security, beyond the
  schema, explain and oasdiff pages.

### Changed

- **Behaviour change:** `snapshot` refuses to overwrite an existing snapshot
  when the new schema has failing changes. Use `--accept "reason"` to record
  them in the allowlist, or `--force`.
- Markdown reports escape Markdown and HTML in names and descriptions.
- Snapshot files are written atomically.

### Fixed

- Components that are shared very widely or nested very deeply are stored
  once instead of being inlined, which removed exponential blow-up and
  recursion errors on large specs.
- django-ninja operations are attributed on versions before 1.4.
- Flask schema attribution stays within the app's own schema library.

### Security

- YAML input with alias expansion bombs or recursive aliases is rejected
  instead of exhausting memory (denial of service).
- Text reports escape control characters, so schema text can't inject
  terminal escapes or GitHub workflow commands.
- Markdown reports escape HTML, Markdown and `@mentions`, and size code fences
  to their content, so schema text can't break out of a pull-request comment.
- The workflow written by `init` and the Action pass branch names through
  environment variables instead of template expressions.
- Deeply nested documents fail with a clear error (exit 2) instead of a crash.
- Usage logs are streamed instead of read fully into memory.
- `git` revisions starting with `-` are refused.
- Fingerprints use `sha1(..., usedforsecurity=False)`.

## [0.1.0a1] - 2026-10-25

First alpha.

### Added

- CLI (`api-contract`) with `snapshot`, `check`, `diff`, `allow` and
  `changelog` commands. Exit codes: 0 pass, 1 failing changes, 2 configuration
  or load error.
- Diff engine for OpenAPI 3.0 and 3.1 documents, with 74 change kinds
  classified as breaking, potentially breaking or safe. Severity depends on
  direction (request vs response). Schemas are normalized first, so reordering
  and description-only edits are not reported.
- Response header requiredness changes: `response-header-became-optional`
  (breaking) and `response-header-became-required` (safe).
- Schema loaders: `file:` (JSON, YAML, or a callable returning a dict),
  `fastapi:`, `flask:` (APIFlask, flask-smorest, flask-openapi3) and `django`
  (drf-spectacular, django-ninja).
- Attribution: breaking changes name the handler, and where known the
  serializer or schema class, behind them.
- Configuration in `[tool.api-contract]` in `pyproject.toml`, or a standalone
  `api-contract.toml`: `source`, `snapshot`, `allowlist`, `fail_on`, `rules`,
  `ignore_keys`, `extra_ignore_keys`. `ignore_keys` replaces the default list;
  `extra_ignore_keys` is appended to it.
- Per-kind severity overrides, by exact kind or by direction-less alias.
- Allowlist file (`api-contract-allow.yml`) with a required reason and expiry;
  expired entries fail the check, stale entries are reported.
- Reports in `text`, `markdown` (for pull request comments) and `json`.
- Consumer-facing Markdown changelog generated from a diff.
- Django management command (`manage.py api_contract`), enabled by adding
  `api_contract.contrib.django` to `INSTALLED_APPS`.
- Extras: `django`, `ninja`, `fastapi`, `flask`, `apiflask`, `smorest`,
  `flask-openapi3`.
- Text and markdown reports group changes that differ only by endpoint or media
  type into one entry listing the affected endpoints. The JSON report is never
  grouped. `--no-group` on `check` and `diff` restores one line per change.
- Install hints name the extra that provides the missing module
  (`api-contract[django]` for DRF, `api-contract[ninja]` for django-ninja,
  `apiflask` / `smorest` / `flask-openapi3` for Flask).
- `manage.py api_contract --help` explains how to get help for each command.

### Fixed

- The Django "settings not configured" error no longer suggests a `--settings`
  flag the plain CLI does not have.
- A duplicate `allow:` key (or any duplicate mapping key) in the allowlist is a
  configuration error (exit 2) instead of silently dropping earlier entries.

### Known limitations

- FastAPI mounted sub-apps are not covered.
- flask-smorest apps with several `Api` objects: only the first is read.
- Flask schema attribution is not implemented; it falls back to the handler.
- DRF serializer attribution relies on a private drf-spectacular registry.
- Swagger 2.0 documents are not supported.
