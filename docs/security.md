# Security and trust boundaries

`api-contract` is a developer and CI tool. This page is its threat model: what
it trusts, what it treats as untrusted data, and how to run it safely in CI.
To report a vulnerability, see
[SECURITY.md](https://github.com/Pythondeveloper6/api-contract/blob/main/SECURITY.md).

## What is trusted

| Input | Trust | Why |
|---|---|---|
| The configured `source` (`fastapi:`, `flask:`, `flask-routes:`, `django`, `file:module:callable`) | **Code execution** | Loaders import your application to generate its schema, exactly like your test suite does. |
| `pyproject.toml` / `api-contract.toml` | Trusted | It chooses what code is imported. |
| The `install` and `args` inputs of the GitHub Action | Trusted | `install` is run by `bash`. They come from the workflow file, not from a pull request. |
| `git:` sources and `--against REV` | Trusted repository, any revision | Read with `git show`; the revision is passed as one argument and may not start with `-`. |

Anyone who can change the configured source, or the code it imports, can run
code wherever `api-contract` runs. That is the same trust you give your test
suite, and it sets the main rule for CI below.

## What is untrusted data

These are parsed as data and never executed:

- **Spec files** (`file:openapi.yaml`, `diff OLD NEW`, partner or legacy
  specs, Swagger 2.0): parsed with a safe YAML loader (no Python objects), with
  a limit on alias-expanded size and a refusal of self-referencing aliases, so
  a "billion laughs" document fails fast with exit code 2. External `$ref`s are
  recorded, never fetched: no network access, no reads outside the given file.
- **The allowlist** (`api-contract-allow.yml`): same YAML guards; duplicate keys
  are rejected.
- **Traffic samples** (`--usage`, `verify-samples`): read line by line as
  text or JSON, matched against path templates; nothing in them is evaluated.
- **Every string that ends up in a report** (paths, enum values, defaults,
  allowlist reasons): control characters are escaped in text reports, so a
  value can neither start a fake `::error::` workflow command in a CI log nor
  send terminal escape sequences. In Markdown reports (pull request comments)
  prose is escaped so it can't inject HTML or links, and `@mentions` are broken
  so a crafted value can't notify people. GitHub annotations escape values as
  the workflow-command format requires; JUnit and SARIF are written with an XML
  and a JSON serializer.
- **Deeply nested documents** that exceed Python's recursion limit end with a
  clean error (exit code 2), not a crash.

## Running it in CI safely

- Run the check on `pull_request`, **never on `pull_request_target`** or any
  trigger that checks out a fork's code with a write token or secrets: the
  loader imports that code.
- Give the job `permissions: contents: read`. The PR comment of the bundled
  action needs `pull-requests: write` (or `issues: write`); on pull requests
  from forks GitHub hands out a read-only token, and the action then only
  writes the job summary.
- The bundled action passes every `${{ }}` value through environment
  variables, never into a script body, and pins its own dependencies by commit.
- Pin `api-contract` (`version: "==X.Y.Z"` in the action, or a lock file) so a
  CI run uses the release you reviewed. Releases are published from tags with
  PyPI trusted publishing and carry build provenance attestations.

## Files it writes

The snapshot, the allowlist, reports (`--output`) and `init`'s files. Writes go
to a temporary file in the same directory that then replaces the target, so a
crash or a parallel job never leaves a half-written file. `init` never
overwrites an existing file.

## How the project checks itself

CI runs ruff's bandit rules (`S`), `pip-audit` on a full install, CodeQL
(security-extended queries) weekly and on every pull request, and mypy. All
GitHub Actions are pinned by commit SHA and updated by Dependabot. Security
fixes are listed under **Security** in the changelog, each with a regression
test in `tests/test_security.py`.
