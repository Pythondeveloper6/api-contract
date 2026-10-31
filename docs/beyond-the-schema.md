# Beyond the schema

A schema diff sees exactly what the schema declares. Three commands deal with
what it doesn't: how much is declared, what real traffic uses, and whether real
responses match.

## How much does the schema describe? `coverage`

```console
$ api-contract coverage
API contract coverage: 42 operations
  typed success response   71.4%
  declared error response  38.1%
  declared auth            90.5%

Untyped success responses (12):
  GET /api/reports/{id}/
  ...
```

- **Typed success response**: the 2xx response declares a body schema (or is
  a 204/205/304). An untyped response is a blind spot: removing a field from
  it is invisible.
- **Declared error response**: at least one 4xx, 5xx or `default` response.
  Without one, a change to the error envelope clients parse is invisible.
- **Declared auth**: a security requirement, so adding or dropping auth shows.

`--min-typed PCT` and `--min-errors PCT` exit 1 below a threshold, so CI can
keep coverage from slipping; `--format json` lists every endpoint.

`check` also warns (on stderr and at the top of the report) when the schema has
no operations at all, or when none of them declares a typed response: a green
check on an almost empty schema means little.

### Declaring the error contract

Most frameworks only document errors you declare. Declare the envelope once
and reuse it, so the check covers it:

- FastAPI: `responses={404: {"model": ErrorOut}, 422: {"model": ErrorOut}}` on
  the router or app.
- DRF + drf-spectacular: `@extend_schema(responses={200: OrderSerializer, 404: ErrorSerializer})`,
  or a default in `SPECTACULAR_SETTINGS`.
- django-ninja: `response={200: OrderOut, 404: ErrorOut}`.
- APIFlask: `@app.doc(responses=[404])` plus `app.config["HTTP_ERROR_SCHEMA"]`;
  flask-smorest: `@blp.alt_response(404, schema=ErrorSchema)`.

## What do clients actually use? `--usage` {#what-do-clients-actually-use-usage}

```bash
api-contract check --usage access.log --usage app-requests.jsonl
```

Each change gets a `traffic: N requests` line counted from the sample, so
"removed an endpoint nobody calls" and "renamed a field on the busiest
endpoint" no longer look alike. Add `--unused-severity potentially-breaking`
(or `safe`) to downgrade changes on endpoints with no traffic at all.

Accepted input, one request per line, formats mixed freely:

- Common/Combined Log Format (nginx, Apache, gunicorn, uvicorn access logs);
- JSON lines with a method and a path or URL under the usual keys
  (`method`/`request_method`/`http.method`, `path`/`url`/`uri`/`http.target`/`url.path`),
  including OpenTelemetry spans with those under `attributes`; an integer
  `count` field is honoured for pre-aggregated exports.

Concrete paths are matched to the spec's templates (`/orders/42` ->
`/orders/{id}`); static segments win over parameters. Traffic is a sample: an
endpoint used once a month by one partner may not be in it, so prefer
`potentially-breaking` over `safe` for `--unused-severity`.

## Do real responses match? `verify-samples` {#do-real-responses-match-verify-samples}

```bash
api-contract verify-samples staging-responses.jsonl
api-contract verify-samples session.har --fail-undocumented
```

Checks recorded responses against the snapshot (or `--source`, or
`--against REV`): the status code must be declared, and a JSON body must match
the declared schema (types, nullability, required and undeclared fields with
`additionalProperties: false`, enums, `allOf`/`anyOf`/`oneOf`, recursive
components). Formats and numeric limits are not checked: they are validation,
not shape.

Samples are JSON lines (`{"method", "path" or "url", "status", "body"}`, where
`body` may be JSON or a JSON string) or a HAR file exported from browser dev
tools or a proxy. Exit code 1 means a mismatch (or, with
`--fail-undocumented`, a request to an endpoint missing from the contract).
