# Rules

Every change `api-contract` reports has a **kind**. Each kind has a default
severity:

- **breaking** fails `check` by default.
- **potentially breaking** is reported, and fails only with `--fail-on
  potentially-breaking` (or `fail_on` in the config).
- **safe** is reported and never fails.

The tables below list all 74 kinds (25 breaking, 16 potentially breaking, 33
safe). They are generated from `api_contract.rules.DEFAULT_RULES`; if this page
and the code ever disagree, the code wins.

## Direction: why most schema kinds come in `request-` / `response-` pairs

A client **sends** requests and **reads** responses, and the server does the
opposite. So the same edit to a schema can break clients in one direction and
be harmless in the other:

- In a **request**, the server became stricter if it now needs something
  clients may not send: a new required field, a removed enum value, a
  `maxLength` that shrank. Clients that worked before can now be rejected.
  Accepting more (a new optional field, a new enum value) is safe.
- In a **response**, the server became less predictable if it may now return
  something clients do not expect: a removed field, a field that may be
  `null`, a new enum value a strict client cannot parse. Returning more
  (a new field) or less variety (a removed enum value) is safe.

| Edit | In a request body | In a response body |
|---|---|---|
| Add a required field | breaking | safe |
| Remove a field | potentially breaking | breaking |
| Add an enum value | safe | potentially breaking |
| Remove an enum value | breaking | safe |
| Become nullable | safe | breaking |
| Tighten a constraint (`maxLength`, ...) | potentially breaking | safe |

Here is one pair of specs where the same two edits are made on the request and
on the response of `POST /echo`: a required `currency` field is added, and
`on_hold` is added to the `status` enum.

```console
$ api-contract diff old.yaml new.yaml
API contract: 4 changes (1 breaking)

BREAKING
  POST /echo  new required request field "currency"
      id: POST /echo:request:currency:required-request-field-added

POTENTIALLY BREAKING
  POST /echo  response field "status" enum value added: "on_hold"
      id: POST /echo:response:200:status:response-enum-value-added:"on_hold"

SAFE
  POST /echo  request field "status" enum value added: "on_hold"
  POST /echo  new response field "currency"

Fix the change, or acknowledge it:
  api-contract allow 'POST /echo:request:currency:required-request-field-added' --reason \"...\" --expires 2026-11-24
```

Each edit appears twice, once per direction, with a different severity: the new
required `currency` is breaking in the request and safe in the response, and the
new `on_hold` value is safe in the request and potentially breaking in the
response (a strict client may not know it). That is why the kind names carry
`request-` or `response-`, and why a severity override can target one
direction (see [Overriding severities](#overriding-severities)).

Kinds with no direction in their name (`type-changed`, `format-changed`,
`default-changed`, ...) have the same severity either way.

## Change ids

Every change has a stable id, printed by `check` for anything that is not safe:

```text
GET /api/orders/{}/:response:200:total:type-changed
POST /api/orders/:request:currency:required-request-field-added
GET /api/orders/{}/:response:200:status:response-enum-value-added:on_hold
```

The shape is `METHOD path:location:field:kind[:detail]`. Path parameters are
positional (`{}`), so renaming `{id}` to `{order_id}` is not a change.
`application/json` is left out of the location; other media types stay in.

A few details have their own format:

- Enum value details are JSON-encoded, so string values are quoted, for
  example `...:request-enum-value-removed:"void"`.
- Anonymous `oneOf` / `anyOf` variant details are the member's type, or
  `type#<8-char hash>` when that is ambiguous.
- A security alternative detail may be `scheme[scopes]`, for example
  `oauth[read]`.

Ids are what the [allowlist](allowlist.md) matches on.

## Overriding severities

Set severities under `[tool.api-contract.rules]`. A key is either a full kind
or a direction-less alias:

```toml
[tool.api-contract.rules]
# Exact kind: only the response direction.
response-enum-value-added = "breaking"
# Alias (kind without "request-"/"response-"): both directions.
enum-value-added = "safe"
# Single-kind keys work too.
param-removed = "safe"
```

- An exact kind beats an alias, so the first two lines above combine as
  "response enum additions are breaking, request ones are safe".
- Values are `breaking`, `potentially-breaking` or `safe`.
- An unknown kind or severity is a configuration error (exit code 2). It is not
  ignored.

## Kinds

### Endpoints

| Kind | Default severity | Meaning |
|---|---|---|
| `endpoint-added` | safe | A new path appears. |
| `endpoint-removed` | breaking | A path disappears. |
| `method-added` | safe | A new HTTP method on an existing path. |
| `method-removed` | breaking | An HTTP method disappears from a path. |
| `endpoint-deprecated` | safe | An operation is marked `deprecated`. |

### Parameters (query, path, header, cookie)

| Kind | Default severity | Meaning |
|---|---|---|
| `required-param-added` | breaking | A new required parameter. |
| `optional-param-added` | safe | A new optional parameter. |
| `param-removed` | potentially-breaking | A parameter is removed. Clients that still send it may be ignored or rejected, depending on the server. |
| `param-became-required` | breaking | An optional parameter becomes required. |
| `param-became-optional` | safe | A required parameter becomes optional. |
| `param-serialization-changed` | potentially-breaking | `style`, `explode`, `allowReserved` or `allowEmptyValue` changed. |
| `param-deprecated` | safe | A parameter is marked `deprecated`. |

### Request body

| Kind | Default severity | Meaning |
|---|---|---|
| `required-request-body-added` | breaking | An operation that took no body now requires one. |
| `optional-request-body-added` | safe | An operation gains an optional body. |
| `request-body-removed` | potentially-breaking | The body is removed. |
| `request-body-became-required` | breaking | An optional body becomes required. |
| `request-body-became-optional` | safe | A required body becomes optional. |
| `request-content-type-added` | safe | A new accepted media type. |
| `request-content-type-removed` | breaking | An accepted media type is removed. |

### Responses

| Kind | Default severity | Meaning |
|---|---|---|
| `response-success-added` | potentially-breaking | A new 2xx status code. Clients that switch on the status may not expect it. |
| `response-success-removed` | breaking | A 2xx status code disappears. |
| `response-status-added` | safe | A new non-2xx status code. |
| `response-status-removed` | potentially-breaking | A non-2xx status code disappears. |
| `response-content-type-added` | safe | A new media type is returned. |
| `response-content-type-removed` | breaking | A returned media type disappears. |
| `response-header-added` | safe | A new response header. |
| `response-header-removed` | breaking | A response header disappears. |
| `response-header-became-optional` | breaking | A response header that was required may now be missing. |
| `response-header-became-required` | safe | A response header that was optional is now always present. |

### Security

| Kind | Default severity | Meaning |
|---|---|---|
| `auth-added` | breaking | An operation that was public now requires authentication. |
| `auth-removed` | safe | An operation no longer requires authentication. |
| `auth-alternative-added` | safe | A new way to authenticate is accepted. |
| `auth-alternative-removed` | breaking | An accepted way to authenticate is removed. |
| `auth-scopes-added` | breaking | An operation now requires more OAuth scopes. |
| `auth-scopes-removed` | safe | An operation requires fewer OAuth scopes. |

### Schema: fields (object properties)

| Kind | Default severity | Meaning |
|---|---|---|
| `required-request-field-added` | breaking | A new required field in a request body. |
| `optional-request-field-added` | safe | A new optional field in a request body. |
| `request-field-removed` | potentially-breaking | A request field is removed. |
| `request-field-became-required` | breaking | An optional request field becomes required. |
| `request-field-became-optional` | safe | A required request field becomes optional. |
| `response-field-added` | safe | A new field in a response. |
| `response-field-removed` | breaking | A response field is removed. |
| `response-field-became-optional` | breaking | A response field that was always present may now be absent. |
| `response-field-became-required` | safe | A response field that might be absent is now always present. |
| `field-deprecated` | safe | A field is marked `deprecated`. |

### Schema: types and formats

| Kind | Default severity | Meaning |
|---|---|---|
| `type-changed` | breaking | The type changed (for example number to string), or a request type was narrowed, or a response type was widened. |
| `request-type-widened` | safe | A request type now accepts more types. |
| `response-type-narrowed` | safe | A response type now returns fewer types. |
| `format-changed` | breaking | `format` changed (for example int32 to int64). |
| `format-added` | potentially-breaking | A `format` was added to a schema that had none. |
| `format-removed` | potentially-breaking | The `format` was removed. |

### Schema: enums

| Kind | Default severity | Meaning |
|---|---|---|
| `request-enum-value-added` | safe | A request enum accepts a new value. |
| `request-enum-value-removed` | breaking | A request enum no longer accepts a value. |
| `response-enum-value-added` | potentially-breaking | A response enum may return a new value. Strict clients can fail on values they do not know. |
| `response-enum-value-removed` | safe | A response enum can no longer return a value. |
| `request-enum-added` | breaking | A free-form request value is now restricted to an enum. |
| `request-enum-removed` | safe | A request enum restriction is lifted. |
| `response-enum-added` | safe | A response value is now documented as an enum. |
| `response-enum-removed` | potentially-breaking | A response enum restriction is lifted, so any value may come back. |

### Schema: nullability

| Kind | Default severity | Meaning |
|---|---|---|
| `request-became-nullable` | safe | A request value may now be null. |
| `request-became-non-nullable` | breaking | A request value may no longer be null. |
| `response-became-nullable` | breaking | A response value may now be null. |
| `response-became-non-nullable` | safe | A response value is never null any more. |

### Schema: constraints (`maxLength`, `minimum`, `pattern`, `additionalProperties`, ...)

| Kind | Default severity | Meaning |
|---|---|---|
| `request-constraint-tightened` | potentially-breaking | A request constraint is stricter. |
| `request-constraint-loosened` | safe | A request constraint is looser. |
| `response-constraint-tightened` | safe | A response constraint is stricter (a stronger guarantee). |
| `response-constraint-loosened` | potentially-breaking | A response constraint is looser (a weaker guarantee). |
| `default-changed` | potentially-breaking | A `default` value changed. |

### Schema: composition (`oneOf`, `anyOf`, `allOf`, `not`) and the fallback

| Kind | Default severity | Meaning |
|---|---|---|
| `request-variant-added` | safe | A request accepts one more variant. |
| `request-variant-removed` | breaking | A request no longer accepts a variant. |
| `response-variant-added` | potentially-breaking | A response may return one more variant. |
| `response-variant-removed` | safe | A response can no longer return a variant. |
| `composition-changed` | potentially-breaking | A composition keyword changed in a way that cannot be matched variant by variant. |
| `schema-changed` | potentially-breaking | Fallback for any schema difference with no more specific kind. It is never dropped silently. |

