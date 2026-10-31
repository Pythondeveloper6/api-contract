# api-contract and oasdiff

[oasdiff](https://github.com/oasdiff/oasdiff) is the reference tool for
OpenAPI breaking-change detection. This page compares the two honestly and
shows how to move an existing oasdiff setup over.

## Which one to use

**oasdiff is stronger on:** the number of checks (several hundred, versus 74
change kinds here), maturity, a single static Go binary, and a hosted service.
If your schema is already a committed file and you are happy with a Go binary
in CI, oasdiff covers most needs.

**api-contract adds:**

- **The schema comes from your Python app, in-process.** DRF
  (drf-spectacular), django-ninja, FastAPI (with mounted sub-apps), APIFlask,
  flask-smorest, flask-openapi3, and a route inventory for plain Flask: no
  server to start, no export script to keep in sync.
- **Attribution**: each change names the serializer, model or handler behind
  it, including where a removed endpoint used to live.
- **An allowlist with a mandatory reason and expiry**, expiry reminders, and
  `snapshot --accept` that records why a break was approved.
- **Python-side workflow**: a pytest plugin, a Django management command, a
  Python API, client profiles, frozen paths, traffic-aware severity and
  runtime response sampling.

## Flag equivalents

| oasdiff | api-contract |
|---|---|
| `oasdiff breaking base.yaml rev.yaml` | `api-contract diff base.yaml rev.yaml` |
| `oasdiff changelog` | `api-contract changelog OLD NEW` (consumer-facing) or `diff` (all changes) |
| `--fail-on ERR` / `WARN` | `--fail-on breaking` / `potentially-breaking` (or `fail_on` in config) |
| base from a git ref (`git show main:openapi.yaml`, `--base`) | `check --against main`, or a `git:main:openapi.yaml` source |
| `--err-ignore FILE` | the allowlist (`api-contract-allow.yml`), with reason and expiry |
| `--severity-levels FILE` | `[tool.api-contract.rules]` |
| `--format json` / `markdown` / `githubactions` / `junit` | `--format json` / `markdown` / `github` / `junit`, plus `sarif` |
| `--match-path`, `--filter-extension` | client profiles and `frozen` paths ([Configuration](configuration.md#clients)) |
| `--exclude-elements description,examples,...` | `ignore_keys` / `extra_ignore_keys` (docs-only keys are ignored by default) |
| GitHub Action | the bundled action ([Continuous integration](ci.md#github-action)) |

## Migrating

```bash
api-contract import-oasdiff --severity-levels severity-levels.txt
api-contract import-oasdiff --err-ignore err-ignore.txt \
  --reason "carried over from oasdiff" --expires 2026-12-31 --write
```

- `--severity-levels` prints a `[tool.api-contract.rules]` block for the
  checks that have an equivalent kind (`ERR` -> breaking, `WARN` -> potentially
  breaking, `INFO`/`NONE` -> safe; when several checks map to one kind, the
  strictest wins). Checks with no equivalent are listed on stderr.
- `--err-ignore` turns each `METHOD /path text` line into an allowlist entry
  `METHOD /path:*`. That is broader than oasdiff's per-message ignore (it covers
  every change on the endpoint), which is why each entry needs a reason and an
  expiry: review them before they expire. Without `--write` the entries are
  printed instead of added.
