# Stability policy

Allowlists, CI thresholds and scripts depend on what `api-contract` prints, so
this page says what may change between releases and how.

## Versions

Releases follow [Semantic Versioning](https://semver.org/). Until 1.0, a minor
release (0.2 -> 0.3) may make the breaking changes listed below, always in the
changelog under **Changed** with a migration note; patch releases (0.2.0 ->
0.2.1) never do. From 1.0 on, they wait for a major release.

## What is stable

| Surface | Promise |
|---|---|
| **Change ids** (`GET /orders/{}:response:200:total:type-changed`) | The format and every existing kind name stay. A change that would alter ids that allowlists hold is a breaking change. |
| **Change kinds** (`docs/rules.md`) | Kinds are only added. Removing or renaming one is a breaking change; a renamed kind keeps working as an alias in allowlists and `[tool.api-contract.rules]` for at least one minor release, with a warning. |
| **Default severities** | Raising a default severity can fail CI that passed, so it is a breaking change. Lowering one is not. |
| **Exit codes** | 0, 1 and 2 keep their meaning. |
| **JSON report** | `version` is bumped on any incompatible change. Adding fields is compatible. |
| **Snapshot format** | `x-api-contract.format` is bumped when older versions can't read a snapshot; they then refuse it with an upgrade hint instead of misreading it. Newer versions read older snapshots, and `api-contract snapshot --upgrade` rewrites one in the current format without loading the app. |
| **Configuration keys** | Keys are only added; a renamed key is accepted with a warning for at least one minor release. |
| **Python API** (`from api_contract import ...`) | The names in `api_contract.__all__` follow the same rules. Modules and names not exported there are internal. |

## What is not covered

- Text and Markdown report layout (use `--format json`, `sarif`, `junit` or
  `github` to parse).
- Which changes are found: a release may find a change an earlier one missed,
  or stop reporting a false positive. Both are bug fixes.
- Attribution text (`at:` lines).

## Deprecation cycle

Anything stable above is deprecated for at least one minor release before it
is removed: it keeps working, prints a warning naming the replacement, and the
changelog lists it under **Deprecated**.
