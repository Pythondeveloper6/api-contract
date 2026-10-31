# Continuous integration

`api-contract check` exits 0 when nothing fails and 1 when something does, so
it works in any CI system as a plain step:

```bash
api-contract check            # exit 1 fails the job
```

Whatever the system, three things must be true:

1. `api-contract.json` (and `api-contract-allow.yml`, if you use one) is
   committed.
2. Your project's own dependencies are installed, because the check imports your
   app to generate the schema, followed by `pip install --pre "api-contract[<extra>]"`.
3. For Django, the settings module is known: set `DJANGO_SETTINGS_MODULE`, or
   run `python manage.py api_contract check`.

## Set it up in one command

```bash
api-contract init            # config, first snapshot, .github/workflows/api-contract.yml
api-contract init --pre-commit
```

`init` detects the framework (Django, FastAPI, Flask and which OpenAPI library,
or an `openapi.json`/`.yaml` file), writes `[tool.api-contract]`, takes the
first snapshot and writes a workflow that runs `check --against` the pull
request's target branch. Nothing that exists is overwritten; `--source`
overrides the detection, `--no-snapshot` and `--no-workflow` skip steps.

## GitHub Action {#github-action}

The repository is also a composite action. It installs `api-contract`, runs
`check` against the snapshot on the pull request's base branch, writes the
Markdown report to the job summary and keeps one pull request comment up to
date:

```yaml
name: API contract
on: pull_request
permissions:
  contents: read
  pull-requests: write   # for the comment; drop it to only use the job summary
jobs:
  api-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: Pythondeveloper6/api-contract@v0.2.0   # pin a release tag or commit
        with:
          extras: fastapi
          install: pip install -r requirements.txt
```

| Input | Default | Meaning |
|---|---|---|
| `extras` | empty | api-contract extras (`django`, `fastapi`, `smorest`, ...) |
| `version` | latest | pip specifier, e.g. `==0.2.0` |
| `install` | empty | Command that installs your project (the check imports it) |
| `python-version` | `3.12` | Empty to keep the runner's Python |
| `against` | `origin/<base branch>` | Baseline revision; `none` uses the working-tree snapshot |
| `fail-on` | config | `breaking` or `potentially-breaking` |
| `working-directory` | `.` | Where the configuration is |
| `comment` | `true` | Post and update the pull request comment |
| `args` | empty | Extra `check` arguments (split on spaces, never evaluated) |

Outputs: `exit-code` (0, 1, 2) and `report` (path of the Markdown report). The
job fails on exit codes 1 and 2. On pull requests from forks GitHub gives a
read-only token: the comment is skipped with a warning and the summary is still
written. Never run it on `pull_request_target`; see [Security](security.md).

## Comparing with the target branch: `--against` {#comparing-with-the-target-branch-against}

```bash
api-contract check --against origin/main
```

reads the snapshot **as committed on `origin/main`** instead of the working
tree. A branch that changes the API and regenerates its own snapshot can't
hide the break: the baseline is whatever the target branch promised. Any git
revision works; the checkout needs it (`fetch-depth: 0`). `changelog` and
`verify-samples` accept `--against` too, and any source can be read from a
revision with `git:REV:path`.

## Plain GitHub Actions workflow

This is [`examples/github-actions.yml`](https://github.com/Pythondeveloper6/api-contract/blob/main/examples/github-actions.yml).
Copy it to `.github/workflows/api-contract.yml`. It runs the check on every pull
request, shows the Markdown report on the run's summary page, and fails the job
when the check fails.

```yaml
--8<-- "examples/github-actions.yml"
```

The exit code is kept in `status` instead of letting the step die, so the
report is still published when the check fails. Exit 2 (a configuration or load
error) writes no report; read the job log.

## GitLab CI

```yaml
api-contract:
  image: python:3.12
  stage: test
  script:
    - pip install -r requirements.txt
    - pip install --pre "api-contract[fastapi]"
    - api-contract check --format markdown --output api-contract-report.md || status=$?
    - '[ -f api-contract-report.md ] && cat api-contract-report.md'
    - exit "${status:-0}"
  artifacts:
    when: always
    paths:
      - api-contract-report.md
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

For Django, add `variables: DJANGO_SETTINGS_MODULE: myproject.settings`.

## SARIF, annotations and JUnit

`--format sarif` feeds GitHub code scanning, `--format github` prints workflow
annotations on the changed lines, and `--format junit` gives GitLab and Jenkins
a test report. See [Reports](reports.md).

## pytest

The package ships a pytest plugin, inactive unless asked:

```bash
pytest --api-contract                       # also check the contract; fails the run on a break
pytest --api-contract-against origin/main   # same, with the baseline from a revision
```

or as an assertion in a test of your own:

```python
def test_api_contract(api_contract_check):
    api_contract_check()  # AssertionError with the report on failure
```

Teams without a CI workflow for it, or who want the failure locally before
pushing, get the check with the rest of the suite.

## Allowlist expiry reminders {#allowlist-expiry-reminders}

An expired entry fails `check`, by design. To hear about it before release day:

```bash
api-contract expiring --within 14d                  # text
api-contract expiring --within 2w --format slack    # {"text": ...} for a Slack webhook
api-contract expiring --format json --fail          # exit 1 if anything is listed
```

[`examples/allowlist-expiry.yml`](https://github.com/Pythondeveloper6/api-contract/blob/main/examples/allowlist-expiry.yml)
is a weekly scheduled workflow that opens (or updates) an issue listing the
entries.

## pre-commit hook

`api-contract` ships no pre-commit hook definition. Use a `local` hook, which
runs in your own environment where the app can be imported:

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: api-contract
        name: API contract
        entry: api-contract check
        language: system
        pass_filenames: false
        always_run: true
```

`always_run` is needed because the hook depends on the whole app rather than on
the staged files. Importing the app on every commit can be slow; if so, run it
at the `pre-push` stage (`stages: [pre-push]`) instead.

## Updating the snapshot

The snapshot is the contract you have promised. Change it on purpose, in the
same pull request as the API change, so reviewers see the contract diff:

1. Change the API. `api-contract check` fails if the change is breaking.
2. **Fix** it so it is compatible, if you can.
3. Otherwise, accept it deliberately in one of two ways:
    - run `api-contract snapshot --accept "why" --expires YYYY-MM-DD` and
      commit the new `api-contract.json` together with the allowlist entries
      it records. A plain `snapshot` refuses to overwrite failing changes, so a
      break can't be blessed by accident (`--force` skips the guard); or
    - if the break must wait (clients are still migrating), add an
      [allowlist](allowlist.md) entry with `api-contract allow` and an expiry
      date. CI passes until then.
4. After a change has shipped, run `api-contract snapshot` and remove the
   allowlist entry, which has gone stale.

`api-contract changelog` turns the same difference into release notes; see
[Reports](reports.md#changelog).

!!! tip
    Do not regenerate the snapshot automatically in CI. That would make `check`
    always pass and defeat its purpose.
