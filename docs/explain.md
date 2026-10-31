# Explaining a change

`api-contract explain` takes a change kind, a direction-less alias, or a full
change id as printed by `check`, and says what the change does to clients, why
it has its severity, and how to make the same change without breaking anyone.

```console
$ api-contract explain 'GET /api/orders/{}/:response:200:total:response-field-removed'
response-field-removed
======================
Where:      GET /api/orders/{}/:response:200:total
Severity:   breaking (default)
Direction:  response

What it means: A response field is removed.
Why this severity: Clients that worked before this change can fail after it.

How to ship it compatibly:
  1. Mark it deprecated in the schema (`deprecated: true`, and for endpoints an `x-sunset: YYYY-MM-DD` date) and tell clients what replaces it.
  2. Ship the replacement next to it and wait until clients have moved (check your traffic: `api-contract check --usage access.log`).
  3. Remove it after the sunset date; api-contract treats removing a deprecated endpoint after its `x-sunset` date as safe.
  4. For anything else, acknowledge the final removal with `api-contract allow <id> --reason ... --expires ...`.
```

- A **kind** (`type-changed`) explains that kind.
- An **alias** without the direction (`enum-value-added`) explains both the
  request and the response kind.
- A **change id** also shows where the change is (`Where:`).
- When `[tool.api-contract.rules]` overrides the severity, both the project's
  severity and the default are shown.

An unknown name suggests the closest kinds. Every kind is listed in
[Rules](rules.md).
