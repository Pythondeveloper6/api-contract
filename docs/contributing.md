# Contributing

Notes for changing `api-contract` itself, rather than using it.

## Set up: three virtual environments

The core never imports a web framework, and the Django and FastAPI/Flask
loaders are developed against separate installs. So the repository uses three
environments, each with the same editable install of the package plus a
different test extra. All three are ignored by git (`.venv*/`).

| Environment | Install | What it runs |
|---|---|---|
| `.venv` (core) | `pip install -e '.[dev]'` | Core tests only; any accidental framework import fails here. Also used for lint and docs |
| `.venv-web` | `pip install -e '.[dev,test-web]'` | FastAPI, APIFlask, flask-smorest and flask-openapi3 loader tests |
| `.venv-django` | `pip install -e '.[dev,test-django]'` | The Django loader, against the DRF and django-ninja example projects in `tests/apps/` |

```bash
python -m venv .venv         && .venv/bin/pip install -e '.[dev]'
python -m venv .venv-web     && .venv-web/bin/pip install -e '.[dev,test-web]'
python -m venv .venv-django  && .venv-django/bin/pip install -e '.[dev,test-django]'
```

Python 3.10 or newer. CI runs the core tests on 3.10 to 3.13 and the web and
Django suites on 3.12.

## Tests

Run the suite in each environment. Tests that need a framework that is not
installed are skipped, so each environment covers a different part:

```bash
.venv/bin/pytest -q
.venv-web/bin/pytest -q
.venv-django/bin/pytest -q
```

### Golden cases

`tests/golden/<case>/` holds `old.json`, `new.json` and `expected.json`: the
changes (`id`, `severity`, `message`) that diffing old to new must produce.
Cases whose name starts with `noise-` must produce no changes at all. Another
test requires every rule in `DEFAULT_RULES` to appear in some golden case, so a
new kind needs a case.

To add a case, create `old.json` and `new.json`, then let pytest write the
expected output:

```bash
.venv/bin/pytest tests/test_golden.py --update-golden
```

`--update-golden` rewrites every `expected.json` from the current output, so
**review the diff** before committing it.

## Lint

```bash
.venv/bin/ruff check .
.venv/bin/ruff format --check .
```

`ruff` is pinned in the `dev` extra. The configuration is in `pyproject.toml`
(line length 100, target Python 3.10).

## Documentation

This site is built with MkDocs Material.

```bash
.venv/bin/pip install -e '.[docs]'
.venv/bin/mkdocs serve            # live preview on http://127.0.0.1:8000
.venv/bin/mkdocs build --strict   # writes ./site (gitignored)
```

`strict: true` is set in `mkdocs.yml`, so a broken link, a missing nav entry or
a broken in-page anchor fails the build. The `Docs` workflow builds the site on
every pull request and deploys it to GitHub Pages from `main`, once the
repository is public.

Every output sample and help text in these pages comes from running the real
CLI. When you change behaviour, regenerate the sample instead of editing it by
hand, and read the source before documenting what a setting does.

## Building the package

```bash
.venv/bin/python -m build
```

The sdist uses an explicit include list (`src`, `tests`, `docs`, `examples`,
the README, changelog, licence and `mkdocs.yml`) so that whatever a local tool
leaves in the directory is not shipped.
