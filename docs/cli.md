# Command line

`api-contract` has five commands. Options such as `--format` and `--config` go
**after** the command: `api-contract check --format markdown`.

| Command | What it does |
|---|---|
| [`snapshot`](#snapshot) | Write the normalized current schema to the snapshot file |
| [`check`](#check) | Compare the current schema with the snapshot, apply the allowlist |
| [`diff`](#diff) | Compare any two specs, snapshots or sources |
| [`allow`](#allow) | Add an allowlist entry |
| [`changelog`](#changelog) | Write a consumer-facing Markdown changelog |

```text
usage: api-contract [-h] [--version] COMMAND ...

Detect breaking changes between OpenAPI documents.

positional arguments:
  COMMAND
    snapshot  write the normalized schema snapshot
    check     diff the current schema against the snapshot
    diff      compare any two specs or snapshots
    allow     acknowledge a change in the allowlist
    changelog
              consumer-facing changelog (Markdown)

options:
  -h, --help  show this help message and exit
  --version   show program's version number and exit
```

`--version` prints `api-contract 0.1.0a1` (the installed version).

Options shared by several commands:

| Option | Commands | Meaning |
|---|---|---|
| `--config PATH` | all | Use this `pyproject.toml` or `api-contract.toml` instead of [discovering one](configuration.md#how-the-config-file-is-found) |
| `--source SOURCE` | all | Override the configured [source](frameworks.md#source-strings) for this run |
| `--format {text,markdown,json}` | `check`, `diff` | Report format, default `text`. See [Reports](reports.md) |
| `--fail-on {breaking,potentially-breaking}` | `check`, `diff` | Lowest severity that fails. Default: the config's `fail_on`, else `breaking` |
| `--output FILE`, `-o FILE` | `snapshot`, `check`, `diff`, `changelog` | Write to this file instead of stdout (for `snapshot`, instead of the configured snapshot path) |
| `--no-group` | `check`, `diff` | List every change separately. See [grouping](reports.md#grouping) |

## snapshot

Loads the schema from the source, normalizes it and writes it to the snapshot
file (`snapshot` in the config, default `api-contract.json`). Commit the file.
Prints `Wrote <path>`.

```text
usage: api-contract snapshot [-h] [--config PATH] [--source SOURCE]
                             [--output FILE]

options:
  -h, --help            show this help message and exit
  --config PATH         pyproject.toml or api-contract.toml
  --source SOURCE       override the configured source, e.g.
                        "file:openapi.json"
  --output FILE, -o FILE
                        default: the configured snapshot path
```

```console
$ api-contract snapshot --source file:old.yaml
Wrote /path/to/project/api-contract.json
```

## check

Compares the current schema (from `source`) with the snapshot, applies the
[allowlist](allowlist.md), prints the report and exits 0 or 1. A missing
snapshot is an error (exit 2).

```text
usage: api-contract check [-h] [--config PATH] [--source SOURCE]
                          [--format {json,markdown,text}]
                          [--fail-on {breaking,potentially-breaking}]
                          [--output FILE] [--no-group]

options:
  -h, --help            show this help message and exit
  --config PATH         pyproject.toml or api-contract.toml
  --source SOURCE       override the configured source, e.g.
                        "file:openapi.json"
  --format {json,markdown,text}
  --fail-on {breaking,potentially-breaking}
                        lowest severity that fails (default: config fail_on,
                        else breaking)
  --output FILE, -o FILE
                        write the report here, not stdout
  --no-group            text/markdown: list every change separately instead of
                        grouping changes that differ only by endpoint or media
                        type (json is never grouped)
```

## diff

Compares any two documents, without a snapshot. Each side is a file path or a
source string, so `diff old.json fastapi:app.main:app` compares a saved spec
with the live app. The allowlist is **not** applied unless you pass
`--allowlist PATH`.

```text
usage: api-contract diff [-h] [--config PATH] [--source SOURCE]
                         [--format {json,markdown,text}]
                         [--fail-on {breaking,potentially-breaking}]
                         [--output FILE] [--no-group] [--allowlist PATH]
                         old new

positional arguments:
  old                   file path or source string (e.g. fastapi:app.main:app)
  new                   file path or source string

options:
  -h, --help            show this help message and exit
  --config PATH         pyproject.toml or api-contract.toml
  --source SOURCE       override the configured source, e.g.
                        "file:openapi.json"
  --format {json,markdown,text}
  --fail-on {breaking,potentially-breaking}
                        lowest severity that fails (default: config fail_on,
                        else breaking)
  --output FILE, -o FILE
                        write the report here, not stdout
  --no-group            text/markdown: list every change separately instead of
                        grouping changes that differ only by endpoint or media
                        type (json is never grouped)
  --allowlist PATH      apply this allowlist (not applied by default)
```

Attribution (the `at:` lines) comes from the loader of the second argument.

## allow

Adds an entry to the allowlist (creating the file if needed). `--reason` and
`--expires` are both required, and the reason cannot be empty. Prints
`Allowed <id> until <date> in <path>`. The id is canonicalized first, so an id
copied with real path parameter names (`{id}`) is stored as `{}`.

```text
usage: api-contract allow [-h] [--config PATH] [--source SOURCE] --reason
                          REASON --expires YYYY-MM-DD [--allowlist PATH]
                          id

positional arguments:
  id                    change id, as printed by check

options:
  -h, --help            show this help message and exit
  --config PATH         pyproject.toml or api-contract.toml
  --source SOURCE       override the configured source, e.g.
                        "file:openapi.json"
  --reason REASON
  --expires YYYY-MM-DD
  --allowlist PATH      default: the configured allowlist
```

See [Allowlist](allowlist.md) for the file format and wildcards.

## changelog

Writes a Markdown changelog for the consumers of your API, without ids or
attribution. With no arguments it compares the snapshot with the current
source; with `OLD NEW` it compares two documents. Giving only one of them is an
error. It always exits 0 when it succeeds, whatever the changes are.

```text
usage: api-contract changelog [-h] [--config PATH] [--source SOURCE]
                              [--title TITLE] [--output FILE]
                              [old] [new]

positional arguments:
  old                   default: the snapshot
  new                   default: the configured source

options:
  -h, --help            show this help message and exit
  --config PATH         pyproject.toml or api-contract.toml
  --source SOURCE       override the configured source, e.g.
                        "file:openapi.json"
  --title TITLE
  --output FILE, -o FILE
```

See [Reports](reports.md#changelog) for an example.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | No failing changes |
| 1 | Failing changes, or an [expired allowlist entry](allowlist.md#expiry) |
| 2 | Configuration or load error: no snapshot yet, bad config, app failed to import, framework not installed |

`snapshot`, `allow` and `changelog` return 0 on success and 2 on error.
Argument errors (a missing `--expires`, an unknown `--format`) also return 2.
Errors are printed to stderr as `api-contract: error: <message>`, for example:

```text
api-contract: error: no source configured: set `source` in [tool.api-contract] or pass --source
```

## Django: `manage.py api_contract`

With `"api_contract.contrib.django"` in `INSTALLED_APPS`, every command is also
available as a management command. It runs the same CLI, so the options are the
same:

```bash
python manage.py api_contract snapshot
python manage.py api_contract check --format markdown
python manage.py api_contract allow "GET /api/orders/:response:200:total:type-changed" \
  --reason "..." --expires 2026-12-01
```

Differences from the plain CLI:

- `manage.py` has already set Django up, so you do not need
  `DJANGO_SETTINGS_MODULE` in the environment. (The plain `api-contract` CLI
  has no `--settings` flag and needs the variable.)
- If neither `--source` nor your config names a source, `snapshot`, `check`
  and `changelog` default to `source = "django"`.
- **Flags go after the subcommand**, because everything after it is forwarded
  unchanged:

    ```bash
    python manage.py api_contract check --format markdown     # works
    python manage.py api_contract --format markdown check     # error: unrecognized arguments
    ```

- Django's own options (`--settings`, `--pythonpath`) go before the subcommand:

    ```bash
    python manage.py api_contract --settings=myproject.settings check
    ```

- Messages say `manage.py api_contract` instead of `api-contract`, including
  the suggested `allow` command in the report.
- A non-zero result exits the process with the same code (1 or 2).
