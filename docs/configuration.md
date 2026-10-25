# Configuration

Settings live under `[tool.api-contract]` in `pyproject.toml`, or in a
standalone `api-contract.toml`. All keys are optional, but `check` and
`snapshot` need a `source` (in the file or as `--source`).

```toml
# pyproject.toml
[tool.api-contract]
source = "fastapi:app.main:app"
snapshot = "api-contract.json"
allowlist = "api-contract-allow.yml"
fail_on = "breaking"
extra_ignore_keys = ["deprecated"]

[tool.api-contract.rules]
enum-value-added = "safe"
```

## Keys

| Key | Type | Default | Meaning |
|---|---|---|---|
| `source` | string | none | Where the current schema comes from. See [source strings](frameworks.md#source-strings) |
| `snapshot` | string (path) | `"api-contract.json"` | The committed baseline |
| `allowlist` | string (path) | `"api-contract-allow.yml"` | [Acknowledged changes](allowlist.md) |
| `fail_on` | string | `"breaking"` | Lowest severity that fails: `"breaking"` or `"potentially-breaking"` |
| `rules` | table | `{}` | Severity overrides, see [rules](#rules) |
| `ignore_keys` | list of strings | `["description", "summary", "example", "examples", "title", "externalDocs", "x-*"]` | The **full** list of schema keys left out of the comparison. Replaces the defaults |
| `extra_ignore_keys` | list of strings | `[]` | Keys added to the ignored list (the defaults, or your `ignore_keys`) |

Unknown keys are an error (exit code 2), so a typo such as `sourc` is caught
instead of silently ignored. There are no other settings.

### `source`

A string such as `"django"`, `"fastapi:app.main:app"`,
`"flask:myapp:create_app"` or `"file:openapi.yaml"`. Every form is listed in
[Frameworks](frameworks.md#source-strings). `--source` overrides it for one run.

### `snapshot` and `allowlist`

Relative paths resolve against the **directory of the config file**, not the
working directory. That way `api-contract check` gives the same result from any
subdirectory. With no config file at all, both default to the working
directory.

```toml
[tool.api-contract]
snapshot = "contracts/orders.json"
allowlist = "contracts/orders-allow.yml"
```

`snapshot -o FILE` and `allow --allowlist PATH` override these for one run; as
command-line values they are relative to the working directory.

### `fail_on`

`"breaking"` fails only breaking changes. `"potentially-breaking"` also fails
potentially breaking ones. Safe changes never fail. `--fail-on` overrides it
for one run. Any other value is an error:

```text
api-contract: error: invalid fail_on 'safe' (choose from: breaking, potentially-breaking)
```

### `rules`

Change a severity under `[tool.api-contract.rules]`. A key is a full kind, or
the kind without `request-` / `response-`, which applies to both directions:

```toml
[tool.api-contract.rules]
enum-value-added = "safe"                 # both directions
response-enum-value-added = "breaking"    # exact kind wins over the alias
param-removed = "safe"
```

Values are `breaking`, `potentially-breaking` or `safe`. Unknown kinds and
severities are errors (exit code 2):

```text
api-contract: error: unknown change kind in rules: 'nope'
```

For a one-off exception use the [allowlist](allowlist.md); use rules for a
policy that applies to the whole project. The kinds are in [Rules](rules.md).

### `ignore_keys` and `extra_ignore_keys`

Keys listed here are dropped from the schema before the comparison, so changing them is never a change. Entries are matched as wildcard
patterns (`x-*` matches every vendor extension). The defaults cover
documentation-only keys.

To ignore one more key and keep the defaults, use `extra_ignore_keys`:

```toml
[tool.api-contract]
extra_ignore_keys = ["deprecated", "x-internal"]
```

Setting `ignore_keys` **replaces** the defaults, so `ignore_keys =
["description"]` makes `example`, `title` and `x-*` count as changes again.
If both are set, the result is `ignore_keys` plus `extra_ignore_keys`.

!!! note
    The snapshot is normalized again with the ignore list in effect on every
    run, so adding keys to the list takes effect immediately. Keys that were
    already dropped when the snapshot was written cannot come back: after
    *removing* keys from the list, run `api-contract snapshot` again.

## `api-contract.toml`

The same keys work in a standalone file, either bare or under the same table:

```toml
# api-contract.toml
source = "fastapi:app.main:app"
fail_on = "potentially-breaking"

[rules]
enum-value-added = "safe"
```

## How the config file is found

Starting in the working directory and walking up to the root, each folder is
checked for `api-contract.toml`, then for a `pyproject.toml` that has a
`[tool.api-contract]` table. The first match wins, so a `pyproject.toml`
without the table is skipped. Use `--config PATH` to pick a file explicitly:

```bash
api-contract check --config services/orders/api-contract.toml
```

If nothing is found, defaults apply and you must pass `--source`.
