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

## GitHub Actions

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
    - run `api-contract snapshot` and commit the new `api-contract.json`. The
      new schema becomes the baseline, and the diff of that file is what
      reviewers read; or
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
