# Contributing

Notes for changing `api-contract` itself, rather than using it.

## Set up

All extras install side by side, so one virtual environment runs everything:

```bash
make install      # .venv with the dev, test-web, test-django and docs extras
make test         # the whole suite
make all          # lint, type check, tests, docs build
```

Other targets: `make lint`, `make typecheck` (mypy), `make cov` (coverage
with the CI threshold), `make docs`, `make build`, `make bench`.

Python 3.10 or newer. CI runs the core tests (no framework installed, so an
accidental framework import fails) on 3.10 to 3.14 and on Windows and macOS,
every loader with coverage on 3.12, and the whole suite against the lowest
versions the extras allow (`uv pip install --resolution lowest-direct`).

Tests that need a framework that is not installed are skipped, so a core-only
environment (`pip install -e '.[dev]'`) is a quick way to check that the core
still imports no framework.

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
