# Troubleshooting

## "loading 'fastapi:app.main:app' failed" / the app won't import

The loader imports your app the way your tests do, so it needs the same
environment:

- **Run it in your project's environment**, with your dependencies installed,
  from the directory your imports are relative to (the working directory is
  put on `sys.path`). `--verbose` shows what is loaded and how long it took.
- **Settings read at import time.** Apps that read a database URL, secret key
  or similar while importing need those variables set, even though
  `api-contract` never connects to anything. In CI, set dummy values:

    ```yaml
    env:
      DATABASE_URL: sqlite:///unused.db
      SECRET_KEY: not-a-secret
    ```

- **Import side effects.** Generating the schema doesn't start the app or run
  its lifespan/startup hooks. If your module connects to a database or starts
  threads at import, move that into the lifespan or a factory. With a factory,
  point the source at it: `fastapi:app.main:create_app`.
- **Docs disabled in production settings** (`openapi_url=None`): FastAPI's
  `app.openapi()` still works, so this does not matter for the FastAPI loader.
- **Django**: set `DJANGO_SETTINGS_MODULE`, or use
  `python manage.py api_contract check`.

## "the 'flask' loader ... Could not find an OpenAPI source"

The app has no APIFlask, flask-smorest or flask-openapi3 spec. Use
`flask-routes:` to compare endpoints and methods only, or export a spec through
`file:module:callable`.

## The check passes but I expected a failure

- Run `api-contract coverage`: the field may not be in the schema at all.
- `check` prints a warning when the schema has no operations, or none with a
  typed response.
- Was the snapshot regenerated in the same branch? `snapshot` refuses to
  overwrite failing changes without `--accept`, and `check --against
  origin/main` compares with the snapshot on the target branch instead.

## `--against` fails with "invalid object name" in CI

The revision isn't in the checkout. Use `actions/checkout` with
`fetch-depth: 0`, or fetch the base branch:
`git fetch origin main:refs/remotes/origin/main`.

## "refusing to overwrite the snapshot"

The new schema has changes that would fail `check`. Fix them, or approve them
with a reason, which records allowlist entries:
`api-contract snapshot --accept "clients moved to v2" --expires 2026-12-31`.
`--force` overwrites without a record.

## An allowlist entry expired and CI fails

Entries expire on purpose. Remove the entry if the change has shipped and the
snapshot was updated, or extend it with a new reason. `api-contract expiring
--within 14d` lists entries before they expire; see
[Continuous integration](ci.md#allowlist-expiry-reminders).

## The snapshot was written by a newer version

"uses snapshot format N, but this api-contract reads up to format M": upgrade
`api-contract` in that environment. After upgrading, `api-contract snapshot
--upgrade` rewrites an existing snapshot in the current format.
