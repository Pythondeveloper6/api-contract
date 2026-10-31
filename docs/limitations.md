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
- **Runtime behaviour that does not match the schema** is invisible to the
  diff. Auth logic in the view body, rate limits, pagination defaults and
  error payloads not described in the OpenAPI document are not compared.
  `api-contract coverage` shows how much the schema declares, and
  `verify-samples` checks recorded responses against it; see
  [Beyond the schema](beyond-the-schema.md).
- **Semantic changes with the same shape.** A field that still has type
  `number` but now returns cents instead of dollars is not a schema change.
- **Secondary apps.** Only the first of several flask-smorest `Api` objects is
  read. (FastAPI sub-apps added with `app.mount()` are merged in.)
- **Heavily shared components.** A component that would be inlined more than
  200 times, or sits more than 40 references deep, is stored once in the
  snapshot (like a recursive one) and compared once, where it is first
  reached; a change inside it is reported at that first use rather than at
  every endpoint.
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

Attribution is best effort and never affects the result. DRF attribution
depends on a private drf-spectacular registry, Flask schemas created with
`Schema.from_dict` have no class to name, and removed endpoints are attributed
only when the snapshot was taken by a version that records handlers. See
[Frameworks](frameworks.md#attribution).

## Roadmap

- Field-level deprecation dates (`x-sunset` works on operations today).
- A standalone binary for CI images without Python (today: `pipx run` or
  `uvx` with the `file:` and `git:` sources).
- A browser playground for trying two specs without installing anything.
