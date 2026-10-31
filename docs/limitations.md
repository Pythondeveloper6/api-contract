# Limitations

`api-contract` compares schemas. It is useful exactly as far as the schema
describes what your API really does.

## What it does not catch

- **It checks the schema, not the code.** If the schema is missing something,
  so is the check. Examples: a DRF `SerializerMethodField` with no type hint or
  `@extend_schema_field` is described as a string whatever it returns; a view
  that returns something other than what its serializer or `response_model`
  declares; a handler that raises a status code the schema does not list.
- **Limited ORM and database coverage.** Model and migration changes are not
  inspected. A change to a model field only appears if it changes the generated
  schema (for example through a `ModelSerializer` field). Changes to
  validation in `save()`, signals, or the database never appear.
- **Runtime behaviour that does not match the schema** is invisible. Auth
  logic in the view body, rate limits, pagination defaults and error payloads
  not described in the OpenAPI document are not compared.
- **Semantic changes with the same shape.** A field that still has type
  `number` but now returns cents instead of dollars is not a schema change.
- **Mounted and secondary apps.** FastAPI sub-apps added with `app.mount()` are
  not in the parent's schema, and only the first of several flask-smorest `Api`
  objects is read. See [Frameworks](frameworks.md) for the workarounds.
- **Swagger 2.0** documents are converted to OpenAPI 3.0 before comparison.
  The conversion covers what affects the wire contract (body and form
  parameters, `consumes`/`produces`, `basePath`, security definitions,
  `x-nullable`); a few rarely used details are approximated: `tsv`
  `collectionFormat` is treated as `csv`, nested `items.collectionFormat` is
  dropped, and path-item `$ref`s are not followed.
- **Ignored keys.** Documentation-only keys (`description`, `example`, `x-*`,
  ...) are deliberately left out of the comparison. Changing the meaning of an
  endpoint in its description is not a change. See
  [`ignore_keys`](configuration.md#ignore_keys-and-extra_ignore_keys).

When the differ finds a schema difference it has no specific rule for, it
reports `schema-changed` (potentially breaking) instead of dropping it. See
[Rules](rules.md).

## Attribution gaps

Attribution is best effort and never affects the result. Flask apps get no
schema-level attribution, removed endpoints are never attributed, and DRF
attribution depends on a private drf-spectacular registry. See
[Frameworks](frameworks.md#attribution).

## Roadmap

Planned for phase 2 (none of this exists yet):

- `--against <git ref>`: build the baseline schema from a git ref instead of a
  committed snapshot.
- A GitHub Action that comments the contract diff on pull requests.
- Per-version checks, so `/v1/` can be frozen while `/v2/` evolves.
- Deprecation dates: mark a field deprecated with a removal date, and fail when
  it is removed early.
- Runtime response sampling in staging, to catch responses that do not match
  the schema.
