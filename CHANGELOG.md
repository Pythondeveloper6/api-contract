# Changelog

All notable changes to api-contract are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
