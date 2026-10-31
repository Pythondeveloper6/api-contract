# Allowlist

When a breaking change is intentional (the mobile app already handles it, the
endpoint was never used), acknowledge it instead of weakening the rules. An
allowed change is still reported, with its reason and date, but no longer fails
the check.

## The `allow` command

```bash
api-contract allow "GET /api/orders/{id}/:response:200:total:type-changed" \
  --reason "Mobile 4.2+ reads total_display instead" \
  --expires 2026-12-01
```

```text
Allowed GET /api/orders/{}/:response:200:total:type-changed until 2026-12-01 in /path/to/project/api-contract-allow.yml
```

- `--reason` and `--expires` are required. The reason cannot be empty and the
  date must look like `2026-12-01`.
- `--allowlist PATH` writes to another file; the default is the `allowlist`
  [setting](configuration.md#snapshot-and-allowlist).
- If the file exists, the new entry is appended and your comments and
  formatting are kept. If an entry with the same id exists, it is replaced.
- The `allow` command printed in a report is already shell-safe: the id is
  quoted for your shell, even when it contains double quotes (enum values do),
  so copy the line as printed. If you type an id by hand, put single quotes
  around the whole id when it contains double quotes.

You can also edit the file by hand.

## File format

`api-contract-allow.yml` (commit it) is a YAML mapping with one `allow` list:

```yaml
# Acknowledged API contract changes. An entry stops a change from failing
# `api-contract check` until it expires. Add entries with `api-contract allow`.
allow:
- id: POST /api/orders/:request:currency:required-request-field-added
  reason: Clients send currency since 4.0
  expires: 2026-11-15
- id: GET /api/orders/{}/:response:200:total:type-changed
  reason: Mobile 4.2+ reads total_display instead
  expires: 2026-12-01
```

| Field | Type | Meaning |
|---|---|---|
| `id` | string | A change id, or a pattern with `*` |
| `reason` | string | Why the change is acceptable. Required and non-empty |
| `expires` | date | `YYYY-MM-DD`. Required |

A missing file is an empty allowlist. A top-level list of entries, without the
`allow:` key, is also accepted. A malformed entry is a configuration error
(exit code 2) that names the file and the entry number.

## Ids

The id is the `id:` line that `check` prints under a change, or the
`id` field in the [JSON report](reports.md#json). Its shape is
`METHOD path:location:field:kind[:detail]`; see [Rules](rules.md#change-ids).

Ids are compared after path parameters are made positional, so an id copied
with real names (`GET /api/orders/{id}/:...`) matches the same change as
`GET /api/orders/{}/:...`. Renaming `{id}` to `{order_id}` is not a change at
all.

## Wildcards

`*` matches any run of characters, including `/` and `:`. Use it to
acknowledge the same change across several operations, which is common
because one serializer or model is reused by many endpoints:

```yaml
allow:
- id: '* /orders*:response:*total:response-field-removed'
  reason: Clients migrated to line_total
  expires: 2026-12-01
```

With that entry, the three endpoints that lost `total` are all allowed:

```text
API contract: 3 changes (3 breaking, 3 allowed)

BREAKING
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      allowed until 2026-12-01: Clients migrated to line_total
  response field "total" removed  (2 endpoints)
      GET /orders/{order_id}
      PUT /orders/{order_id}
      media types: application/json
      at: app.main.Order (app/main.py:7)
      allowed until 2026-12-01: Clients migrated to line_total
```

Keep patterns as narrow as you can: a pattern such as `* *:type-changed`
silences every type change. Entries are tried in file order, and the first live
entry that matches a change is the one reported.

To copy every id into the allowlist one by one, run `check --no-group`, since
the grouped report prints only one id per group.

## Expiry

An entry is live through its `expires` date. After that:

- It **stops allowing anything**, so the change fails the check again.
- It **fails the check on its own**, even if its change is gone. Acknowledgements
  cannot quietly become permanent.

```text
API contract: 4 changes (2 breaking, 1 allowed)

BREAKING
  POST /api/orders/  new required request field "currency"
      id: POST /api/orders/:request:currency:required-request-field-added
  GET /api/orders/{id}/  response field "total" type changed: number -> string
      allowed until 2026-12-01: Mobile 4.2+ reads total_display instead

POTENTIALLY BREAKING
  GET /api/orders/{id}/  response field "status" enum value added: "on_hold"
      id: GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"

SAFE
  POST /api/coupons/  new endpoint

EXPIRED ALLOWLIST ENTRIES (these fail the check)
  POST /api/orders/:request:currency:required-request-field-added  expired 2026-01-15: Clients send currency since 4.0

STALE ALLOWLIST ENTRIES (match no change; consider removing)
  DELETE /api/orders/{}/:endpoint-removed

Fix the change, or acknowledge it:
  api-contract allow 'POST /api/orders/:request:currency:required-request-field-added' --reason "..." --expires 2026-11-24
```

Fix the change, move the date forward, or remove the entry.

## Stale entries

A live entry that matches no change is **stale**: its change was fixed, or the
snapshot was updated. It is reported as a warning (see the
`DELETE /api/orders/{}/:endpoint-removed` entry above) and does not fail the
check. Remove it.

Run `api-contract snapshot` once the change has shipped, so the new schema
becomes the baseline and the entry goes stale.

## Duplicate keys are an error

YAML lets a key appear twice and silently keeps the last one, which would drop
your first `allow:` list. `api-contract` rejects it instead:

```text
api-contract: error: cannot read allowlist /path/to/project/api-contract-allow.yml: while constructing a mapping
  in "/path/to/project/api-contract-allow.yml", line 1, column 1
found duplicate key 'allow'; merge the entries into one list
  in "/path/to/project/api-contract-allow.yml", line 5, column 1
```

Merge the entries into one list.
