# api-contract

Catch breaking API changes in CI, for Django, FastAPI and Flask.

A developer renames a serializer field, makes a parameter required, or changes
`id` from int to string. Tests pass, the deploy goes out, and the mobile app
(which can't be force-updated) starts crashing. API changes get reviewed as
Python diffs, not as contract diffs.

`api-contract` generates the OpenAPI schema from your app, compares it with a
committed snapshot, classifies each change as **breaking**, **potentially
breaking** or **safe**, and fails the build on breaking ones. It names the
serializer, model or handler behind each change.

| Framework | Schema from |
|---|---|
| Django REST framework | drf-spectacular |
| Django | django-ninja |
| FastAPI | FastAPI itself |
| Flask | APIFlask, flask-smorest, flask-openapi3 |
| Anything else | an OpenAPI 3.0/3.1 JSON or YAML file |

!!! note "Alpha"
    The only release is the pre-release `0.1.0a1`, so install with `--pre`.
    See [Quickstart](quickstart.md#install).

## A 30-second example

Two small specs. The new one changes `total` from number to string, adds a
required `currency` field to a request, adds an enum value, and adds an
endpoint. The snapshot was taken from `old.yaml`
(`api-contract snapshot --source file:old.yaml`), and `source` in
`pyproject.toml` points at `new.yaml`.

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
$ echo $?
1
```

With a Django, FastAPI or Flask project, each change also gets an `at:` line
that names the code behind it:

```text
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: POST /orders:response:201:total:response-field-removed
```

## How it works

```text
spec  ->  normalize  ->  diff  ->  classify  ->  allowlist  ->  report
```

1. **Spec.** A [loader](frameworks.md) imports your app and asks your OpenAPI
   library for the schema. Or it reads a JSON or YAML file.
2. **Normalize.** `$ref`s are resolved, keys are sorted, docs-only keys such as
   `description` and `example` are dropped, and order-insensitive lists
   (`required`, `enum`, ...) are sorted. Reordering fields or rewording a
   description never shows up as a change, and neither does renaming a path
   parameter. The snapshot file stores this normalized form.
3. **Diff.** The normalized snapshot and the normalized current schema are
   compared endpoint by endpoint and schema by schema.
4. **Classify.** Each difference gets a [kind](rules.md) and a severity.
   Direction matters: adding a required field is breaking in a request and safe
   in a response.
5. **Allowlist.** Changes you have [acknowledged](allowlist.md), with a reason
   and an expiry date, no longer fail the check.
6. **Report.** [Text, Markdown or JSON](reports.md), and an
   [exit code](cli.md#exit-codes) for CI.

## Where next

- [Quickstart](quickstart.md): snapshot, check, fix or allow, for each framework.
- [Frameworks](frameworks.md): source strings, auto-detection, attribution and known gaps.
- [Configuration](configuration.md) and the [command line](cli.md).
- [Allowlist](allowlist.md) and [Reports](reports.md).
- [Continuous integration](ci.md): GitHub Actions, GitLab CI, pre-commit.
- [Rules](rules.md): all 74 change kinds and their default severities.
- [Python API](python-api.md), including how to write a custom loader.
- [Limitations](limitations.md) and the roadmap.
- [Contributing](contributing.md).
