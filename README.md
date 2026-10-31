# api-contract

Catch breaking API changes in CI, for Django, FastAPI and Flask.

![Python 3.10–3.14](https://img.shields.io/badge/python-3.10%E2%80%933.14-3776AB?logo=python&logoColor=white)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Status: alpha](https://img.shields.io/badge/status-alpha-orange)

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
| Flask | APIFlask, flask-smorest, flask-openapi3; a route inventory for plain Flask |
| Anything else | an OpenAPI 3.0/3.1 or Swagger 2.0 JSON or YAML file |

## Example

Two small specs: the new one changes `total` from number to string, adds a
required `currency` field to a request, adds an enum value, and adds an
endpoint. The snapshot was taken from `old.yaml`
(`api-contract snapshot --source file:old.yaml`), and `source` points at
`new.yaml`.

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
  api-contract allow 'POST /api/orders/:request:currency:required-request-field-added' --reason "..." --expires 2026-11-24
$ echo $?
1
```

With a Django, FastAPI or Flask project, each change also gets an `at:` line:

```text
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: POST /orders:response:201:total:response-field-removed
```

## Install

```bash
pip install --pre "api-contract[django]"
```

The `--pre` is needed while releases are pre-releases (`0.1.0aN`).

Alternatively, install a tagged release straight from git:

```bash
pip install "git+https://github.com/Pythondeveloper6/api-contract.git@v0.1.0a1"
```

(Extras with git: `"api-contract[fastapi] @
git+https://github.com/Pythondeveloper6/api-contract.git@v0.1.0a1"`.)

Pick the extra for your stack:

| Extra | Installs | For |
|---|---|---|
| `django` | Django, DRF, drf-spectacular | Django REST framework (not django-ninja: that is `ninja`) |
| `ninja` | Django, django-ninja | django-ninja |
| `fastapi` | FastAPI | FastAPI |
| `flask` | Flask only | Not enough on its own: pick one of the three below, which bring Flask with them |
| `apiflask` | APIFlask | APIFlask |
| `smorest` | flask-smorest | flask-smorest |
| `flask-openapi3` | flask-openapi3 | flask-openapi3 |

Combine them if you need to: `"api-contract[fastapi,flask-openapi3]"`. With no
extra you can still compare `file:` sources. Python 3.10 or newer.

The loader imports your app, so run `api-contract` in the environment where
your project's dependencies are installed.

## Quickstart

Every framework follows the same steps: add `[tool.api-contract]` to
`pyproject.toml`, write a snapshot, commit it, and run `check` in CI. FastAPI
as the example:

```bash
api-contract init          # detects the framework, writes the config, the first
                           # snapshot and a GitHub Actions workflow
```

or by hand:

```toml
# pyproject.toml
[tool.api-contract]
source = "fastapi:app.main:app"    # module:FastAPI instance, or an app factory
```

```bash
api-contract snapshot                    # writes api-contract.json; commit it
api-contract check --against origin/main # exit 1 on a breaking change vs the target branch
```

`snapshot` refuses to overwrite a snapshot with breaking changes unless you
say why (`--accept "reason"`, recorded in the allowlist), so a break can't be
approved by regenerating the file.

When a change is intentional, acknowledge it instead of weakening the rules:

```bash
api-contract allow "GET /api/orders/{id}/:response:200:total:type-changed" \
  --reason "Mobile 4.2+ reads total_display instead" --expires 2026-12-01
```

Django (`manage.py api_contract`), Flask and plain `file:` sources work the
same way; see the [Quickstart](https://pythondeveloper6.github.io/api-contract/quickstart/).

## In CI and beyond

- **GitHub Action**: `uses: Pythondeveloper6/api-contract@<tag>` checks against
  the base branch, writes the job summary and keeps one PR comment updated.
- **pytest**: `pytest --api-contract`, or the `api_contract_check` fixture.
- **Reports**: text, Markdown, JSON, SARIF (code scanning), GitHub annotations,
  JUnit.
- **Client profiles and frozen versions**: stricter rules for the mobile app's
  endpoints, `/v1/*` frozen while `/v2/` evolves, removal allowed after an
  `x-sunset` date.
- **Beyond the schema**: `coverage` (how much is declared), `--usage
  access.log` (traffic per change), `verify-samples` (recorded responses vs the
  contract), `explain <change>` (how to ship it compatibly).

## Documentation

Full documentation: **<https://pythondeveloper6.github.io/api-contract/>** (an MkDocs Material site; run
`mkdocs serve` after `pip install -e ".[docs]"`).

- [Quickstart](https://pythondeveloper6.github.io/api-contract/quickstart/): install, snapshot, check, fix or allow, for each framework.
- [Frameworks](https://pythondeveloper6.github.io/api-contract/frameworks/): source strings, auto-detection, attribution and known gaps.
- [Configuration](https://pythondeveloper6.github.io/api-contract/configuration/): every `[tool.api-contract]` key.
- [Command line](https://pythondeveloper6.github.io/api-contract/cli/): every command and flag, exit codes, `manage.py api_contract`.
- [Allowlist](https://pythondeveloper6.github.io/api-contract/allowlist/): file format, wildcards, expiry, stale entries.
- [Reports](https://pythondeveloper6.github.io/api-contract/reports/): text, Markdown and JSON, grouping, the changelog.
- [Continuous integration](https://pythondeveloper6.github.io/api-contract/ci/): `init`, the GitHub Action, `--against`, pytest, GitLab CI, pre-commit, expiry reminders.
- [Beyond the schema](https://pythondeveloper6.github.io/api-contract/beyond-the-schema/): coverage, traffic, response sampling.
- [Troubleshooting](https://pythondeveloper6.github.io/api-contract/troubleshooting/): apps that won't import, `--against` in CI, refused snapshots.
- [Deployment](https://pythondeveloper6.github.io/api-contract/deployment/) and [Upgrading](https://pythondeveloper6.github.io/api-contract/upgrading/): where to run it, pinning, snapshot upgrades.
- [Rules](https://pythondeveloper6.github.io/api-contract/rules/): all 74 change kinds and their default severities.
- [Python API](https://pythondeveloper6.github.io/api-contract/python-api/): the public API and writing a custom loader.
- [Limitations](https://pythondeveloper6.github.io/api-contract/limitations/): what it does not catch, and the roadmap.
- [Stability policy](https://pythondeveloper6.github.io/api-contract/stability/), [Performance](https://pythondeveloper6.github.io/api-contract/performance/), [Security](https://pythondeveloper6.github.io/api-contract/security/), [Coming from oasdiff](https://pythondeveloper6.github.io/api-contract/oasdiff/).
- [Contributing](https://pythondeveloper6.github.io/api-contract/contributing/): dev setup, tests, golden cases, building the docs.

Changes between versions are in [`CHANGELOG.md`](https://github.com/Pythondeveloper6/api-contract/blob/main/CHANGELOG.md).
A runnable end-to-end example is in
[`examples/orders-contract`](https://github.com/Pythondeveloper6/api-contract/tree/main/examples/orders-contract).
A complete GitHub Actions workflow is in
[`examples/github-actions.yml`](https://github.com/Pythondeveloper6/api-contract/blob/main/examples/github-actions.yml).

## Security

The loader imports your application, so run it only on code you trust, and give
CI read-only permissions. It makes no network calls. See the
[security page](https://pythondeveloper6.github.io/api-contract/security/) and
[`SECURITY.md`](https://github.com/Pythondeveloper6/api-contract/blob/main/SECURITY.md)
to report a vulnerability.

## Limits

It compares declared schemas, so behaviour the schema does not describe
(semantics, side effects, undeclared fields) is not caught. This is an alpha:
see [Limitations](https://pythondeveloper6.github.io/api-contract/limitations/)
and the [stability policy](https://pythondeveloper6.github.io/api-contract/stability/).

## Contributing

Issues and pull requests are welcome. `make install && make test lint typecheck docs`
sets up and checks everything; details in the
[contributing guide](https://pythondeveloper6.github.io/api-contract/contributing/).

## License

MIT
