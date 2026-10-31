# Reports

`check` and `diff` accept `--format`:

| Format | Use |
|---|---|
| `text` (default) | Terminals and CI logs |
| `markdown` | Pull request comments and `$GITHUB_STEP_SUMMARY` |
| `sarif` | GitHub code scanning and other SARIF 2.1.0 tools |
| `github` | GitHub Actions annotations (workflow commands) |
| `junit` | GitLab, Jenkins and other JUnit XML consumers |
| `json` | Scripts. Has `ok`, `summary` counts, every change, and expired/stale allowlist entries |

`--output FILE` writes the report to a file instead of stdout. Changes are
sorted worst first. The report never changes the exit code: see
[Exit codes](cli.md#exit-codes).

## Text

The default. Changes are listed by severity. Each change shows its endpoint,
what changed, an `at:` line when the code behind it is known (see
[attribution](frameworks.md#attribution)), and its `id:`. Safe changes have no
id, since nothing needs acknowledging.

```console
$ api-contract check
API contract: 4 changes (2 breaking)

BREAKING
  POST /api/orders/  new required request field "currency"
      id: POST /api/orders/:request:currency:required-request-field-added
  GET /api/orders/{id}/  response field "total" type changed: number -> string
      id: GET /api/orders/{}/:response:200:total:type-changed

POTENTIALLY BREAKING
  GET /api/orders/{id}/  response field "status" enum value added: "on_hold"
      id: GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"

SAFE
  POST /api/coupons/  new endpoint

Fix the change, or acknowledge it:
  api-contract allow 'POST /api/orders/:request:currency:required-request-field-added' --reason \"...\" --expires 2026-11-24
```

When changes are allowed, the id is replaced by the reason and date:

```console
$ api-contract check
API contract: 4 changes (2 breaking, 2 allowed)

BREAKING
  POST /api/orders/  new required request field "currency"
      allowed until 2026-11-15: Clients send currency since 4.0
  GET /api/orders/{id}/  response field "total" type changed: number -> string
      allowed until 2026-12-01: Mobile 4.2+ reads total_display instead

POTENTIALLY BREAKING
  GET /api/orders/{id}/  response field "status" enum value added: "on_hold"
      id: GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"

SAFE
  POST /api/coupons/  new endpoint
```

Expired and stale allowlist entries get their own sections; see
[Allowlist](allowlist.md#expiry). The closing hint suggests the `allow` command
for the first failing change.

## Markdown

For pull request comments and `$GITHUB_STEP_SUMMARY`. The heading ends with
`passed` or `failed`, and safe changes are folded into a `<details>` block.

```console
$ api-contract check --format markdown
### API contract: 4 changes (2 breaking, 2 allowed) — passed

#### Breaking (2)

- **POST** `/api/orders/` — new required request field "currency"
  - allowed until 2026-11-15: Clients send currency since 4.0
- **GET** `/api/orders/{id}/` — response field "total" type changed: number -> string
  - allowed until 2026-12-01: Mobile 4.2+ reads total_display instead

#### Potentially breaking (1)

- **GET** `/api/orders/{id}/` — response field "status" enum value added: "on_hold"
  - id: `GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"`

<details><summary>Safe (1)</summary>

- **POST** `/api/coupons/` — new endpoint

</details>
```

## JSON

For scripts. One object per change, ids unchanged, never grouped:

```json
{
  "version": 1,
  "ok": true,
  "fail_on": "breaking",
  "summary": {
    "total": 4,
    "breaking": 2,
    "potentially-breaking": 1,
    "safe": 1,
    "allowed": 2,
    "failing": 0
  },
  "changes": [
    ...
  ],
  "allowlist": {
    "expired": [],
    "stale": []
  }
}
```

The full report has these top-level keys:

| Key | Meaning |
|---|---|
| `version` | The report schema version, currently `1` |
| `ok` | `true` when `check` would exit 0 |
| `fail_on` | The threshold in effect |
| `summary` | Counts: `total`, `breaking`, `potentially-breaking`, `safe`, `allowed`, `failing` |
| `changes` | One object per change |
| `allowlist` | `expired` and `stale` entries, each with `id`, `reason` and `expires` |

Each element of `changes` looks like this (an allowed breaking change; `allowed`
is `null` otherwise, and `attribution` is `null` for file sources):

```json
{
  "id": "GET /api/orders/{}/:response:200:total:type-changed",
  "kind": "type-changed",
  "severity": "breaking",
  "direction": "response",
  "method": "GET",
  "path": "/api/orders/{}/",
  "raw_path": "/api/orders/{id}/",
  "location": "response:200:application/json",
  "pointer": "total",
  "detail": null,
  "old": [
    "number"
  ],
  "new": [
    "string"
  ],
  "message": "response field \"total\" type changed: number -> string",
  "component": "Order",
  "attribution": null,
  "allowed": {
    "id": "GET /api/orders/{}/:response:200:total:type-changed",
    "reason": "Mobile 4.2+ reads total_display instead",
    "expires": "2026-12-01"
  }
}
```

`old` and `new` hold the schema fragments (or types) before and after.

## SARIF

`--format sarif` writes SARIF 2.1.0. Each change is a result whose `ruleId` is
the change kind; failing changes are `error`, other breaking or potentially
breaking changes (including allowed ones) are `warning`, safe changes are
`note`. Allowed changes carry a `suppressions` entry with the allowlist reason,
so code scanning shows them as dismissed. `partialFingerprints` holds the change
id, so alerts stay stable between runs. When the attribution has a
`(file:line)`, the result points at that file; otherwise it only names the
endpoint. Expired allowlist entries become `allowlist-entry-expired` errors.

```yaml
- run: api-contract check --format sarif --output api-contract.sarif
  continue-on-error: true
- uses: github/codeql-action/upload-sarif@v3
  with:
    sarif_file: api-contract.sarif
    category: api-contract
```

## GitHub annotations

`--format github` prints one workflow command per non-safe change and per
expired allowlist entry, then the usual summary line. Failing changes are
`::error`, the rest `::warning`. `file=` and `line=` appear only when the
attribution has them. Special characters are escaped as GitHub requires.

```yaml
- run: api-contract check --format github
```

```text
::error file=app/main.py,line=7,title=api-contract%3A type-changed::GET /orders/{id} response field "total" type changed: number -> string (id: GET /orders/{}:response:200:total:type-changed)
API contract: 3 changes (1 breaking)
```

## JUnit

`--format junit` writes JUnit XML: one `testsuite` named `api-contract`, one
`testcase` per change (`classname` is the endpoint, `name` the change id).
Failing changes and expired allowlist entries have a `<failure>`, allowed
changes are `<skipped>` with the reason, everything else passes.

```yaml
# .gitlab-ci.yml
api-contract:
  script:
    - api-contract check --format junit --output api-contract.xml
  artifacts:
    when: always
    reports:
      junit: api-contract.xml
```

## Grouping

One change to a shared serializer can show up once per endpoint and once per
content type (JSON, form, multipart). The text and markdown reports fold changes
that share a kind, location and pointer, and differ only in endpoint or media
type, into one entry that lists the affected endpoints and media types. Here
the FastAPI model `Order` lost a field that three endpoints return:

```text
API contract: 3 changes (3 breaking)

BREAKING
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: POST /orders:response:201:total:response-field-removed
  response field "total" removed  (2 endpoints)
      GET /orders/{order_id}
      PUT /orders/{order_id}
      media types: application/json
      at: app.main.Order (app/main.py:7)
      id: GET /orders/{}:response:200:total:response-field-removed
      (+1 similar changes; --no-group or --format json lists every id)

Fix the change, or acknowledge it:
  api-contract allow 'POST /orders:response:201:total:response-field-removed' --reason \"...\" --expires 2026-11-24
```

`POST /orders` returns it with status 201, so it is a different location and
stays on its own; the two `200` responses are folded.

Grouping only affects how the text and markdown reports are laid out. The
counts in the summary line, the exit code and the `json` report are the same.
Pass `--no-group` to list every change on its own line, for example to copy
every id into the allowlist:

```text
API contract: 3 changes (3 breaking)

BREAKING
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: POST /orders:response:201:total:response-field-removed
  GET /orders/{order_id}  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: GET /orders/{}:response:200:total:response-field-removed
  PUT /orders/{order_id}  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: PUT /orders/{}:response:200:total:response-field-removed

Fix the change, or acknowledge it:
  api-contract allow 'POST /orders:response:201:total:response-field-removed' --reason \"...\" --expires 2026-11-24
```

## Changelog

`api-contract changelog` writes a consumer-facing summary, without ids,
severities or attribution, that you can paste into release notes. With no
arguments it compares the snapshot with the current source; `changelog OLD NEW`
compares two documents. `--title` sets the heading (default `API changes`) and
`-o FILE` writes to a file.

```console
$ api-contract changelog --title v2.1
## v2.1

### Breaking changes

- `POST /api/orders/`: new required request field "currency"
- `GET /api/orders/{id}/`: response field "total" type changed: number -> string

### Changes that may affect you

- `GET /api/orders/{id}/`: response field "status" enum value added: "on_hold"

### New and improved

- New endpoint `POST /api/coupons/`
```

Changes are grouped by how much they should worry a client: breaking changes,
"changes that may affect you", and "new and improved". Deprecations get their
own section. With no differences it writes `No changes to the API contract.`
