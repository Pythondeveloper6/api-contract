# Quickstart

Every framework follows the same steps:

1. [Install](#install) `api-contract` with the extra for your stack.
2. Add `[tool.api-contract]` to `pyproject.toml` with a `source`.
3. **Snapshot**: `api-contract snapshot` writes `api-contract.json`. Commit it.
4. **Check**: `api-contract check` compares the app against the snapshot.
5. **Fix or allow**: undo the change, or [acknowledge it](#fix-or-allow).
6. Run `check` in [CI](ci.md). When you change the API on purpose, run
   `snapshot` again.

## Install

```bash
pip install --pre "api-contract[django]"
```

The `--pre` is needed while the only release is the pre-release `0.1.0a1`.

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

Paths for `snapshot` and `allowlist` resolve against the config file's
directory. Options such as `--format` and `--config` go **after** the
subcommand: `api-contract check --format markdown`.

## Snapshot and check

=== "Django REST framework"

    ```bash
    pip install --pre "api-contract[django]"
    ```

    ```toml
    # pyproject.toml
    [tool.api-contract]
    source = "django"
    ```

    ```python
    # settings.py
    INSTALLED_APPS = [
        ...
        "rest_framework",
        "drf_spectacular",
        "api_contract.contrib.django",   # adds `manage.py api_contract`
    ]
    ```

    ```bash
    python manage.py api_contract snapshot     # writes api-contract.json
    git add api-contract.json
    python manage.py api_contract check
    ```

    Without the management command, set the settings module instead (the plain
    `api-contract` CLI has no `--settings` flag):

    ```bash
    DJANGO_SETTINGS_MODULE=myproject.settings api-contract check
    ```

    `source = "django"` uses drf-spectacular when it is installed and
    `rest_framework` is in `INSTALLED_APPS`. Use `django:drf` to be explicit.
    After removing `total` from a serializer, `check` prints (a ViewSet
    reports one change per operation and media type, so this is the grouped
    form):

    ```text
    API contract: 14 changes (5 breaking)

BREAKING
  GET /api/orders/  response field "[].total" removed
      at: orders.serializers.OrderSerializer (orders/serializers.py:20)
      id: GET /api/orders/:response:200:[].total:response-field-removed
  POST /api/orders/  response field "total" removed
      at: orders.serializers.OrderSerializer (orders/serializers.py:20)
      id: POST /api/orders/:response:201:total:response-field-removed
  response field "total" removed  (3 endpoints)
      GET /api/orders/{id}/
      PATCH /api/orders/{id}/
      PUT /api/orders/{id}/
      media types: application/json
      at: orders.serializers.OrderSerializer (orders/serializers.py:20)
      id: GET /api/orders/{}/:response:200:total:response-field-removed
      (+2 similar changes; --no-group or --format json lists every id)

POTENTIALLY BREAKING
  request field "total" removed  (3 endpoints)
      PATCH /api/orders/{id}/
      POST /api/orders/
      PUT /api/orders/{id}/
      media types: application/json, application/x-www-form-urlencoded, multipart/form-data
      at: orders.serializers.OrderSerializer (orders/serializers.py:20)
      id: POST /api/orders/:request:total:request-field-removed
      (+8 similar changes; --no-group or --format json lists every id)

Fix the change, or acknowledge it:
  manage.py api_contract allow 'GET /api/orders/:response:200:[].total:response-field-removed' --reason \"...\" --expires 2026-11-24
    ```

=== "django-ninja"

    ```bash
    pip install --pre "api-contract[ninja]"
    ```

    ```toml
    [tool.api-contract]
    source = "django:ninja:myproject.api:api"   # module:NinjaAPI instance
    ```

    `source = "django"` also works when exactly one `NinjaAPI` is mounted in
    your URLs. Add `api_contract.contrib.django` to `INSTALLED_APPS` for
    `manage.py api_contract`, or set `DJANGO_SETTINGS_MODULE` and use the CLI.

    ```bash
    python manage.py api_contract snapshot
    python manage.py api_contract check
    ```

=== "FastAPI"

    ```bash
    pip install --pre "api-contract[fastapi]"
    ```

    ```toml
    [tool.api-contract]
    source = "fastapi:app.main:app"    # module:FastAPI instance, or an app factory
    ```

    ```bash
    api-contract snapshot
    api-contract check
    ```

    After removing `total` from the `Order` model:

    ```text
    API contract: 3 changes (3 breaking)

BREAKING
  POST /orders  response field "total" removed
      at: app.main.Order (app/main.py:7)
      id: POST /orders:response:201:total:response-field-removed
  response field "total" removed  (2 endpoints)
      GET /orders/{order_id}
      PUT /orders/{order_id}
      media types: application/json
      at: app.main.Order (app/main.py:7)
      id: GET /orders/{}:response:200:total:response-field-removed
      (+1 similar changes; --no-group or --format json lists every id)

Fix the change, or acknowledge it:
  api-contract allow 'POST /orders:response:201:total:response-field-removed' --reason \"...\" --expires 2026-11-24
    ```

=== "Flask"

    ```bash
    pip install --pre "api-contract[smorest]"    # or apiflask / flask-openapi3
    ```

    ```toml
    [tool.api-contract]
    source = "flask:myapp:create_app"    # module:Flask instance, or a factory
    ```

    ```bash
    api-contract snapshot
    api-contract check
    ```

    The loader finds APIFlask, flask-smorest or flask-openapi3 on its own.
    Install the extra for the library your app uses; the `flask` extra
    installs only Flask and gives the loader no OpenAPI source. With
    flask-smorest, after removing `total` from a schema:

    ```text
    API contract: 3 changes (3 breaking)

BREAKING
  GET /orders/  response field "[].total" removed
      at: myapp.Orders.get (myapp.py:33)
      id: GET /orders/:response:200:[].total:response-field-removed
  POST /orders/  response field "total" removed
      at: myapp.Orders.post (myapp.py:38)
      id: POST /orders/:response:201:total:response-field-removed
  GET /orders/{order_id}  response field "total" removed
      at: myapp.OrderById.get (myapp.py:44)
      id: GET /orders/{}:response:200:total:response-field-removed

Fix the change, or acknowledge it:
  api-contract allow 'GET /orders/:response:200:[].total:response-field-removed' --reason \"...\" --expires 2026-11-24
    ```

=== "Any other source"

    ```toml
    [tool.api-contract]
    source = "file:openapi.yaml"            # or "file:pkg.module:build_spec"
    ```

    ```bash
    api-contract snapshot
    api-contract check
    ```

See [Frameworks](frameworks.md) for every source string.

## Fix or allow

`check` exits 1 when a change is breaking. You have two ways out.

**Fix it.** Undo the change, or make it backwards compatible (keep the old
field, make the new parameter optional). Run `check` again.

**Allow it.** When the break is intentional (the mobile app already handles it,
the endpoint was never used), acknowledge it with the id printed under the
change:

```bash
api-contract allow "GET /api/orders/{id}/:response:200:total:type-changed" \
  --reason "Mobile 4.2+ reads total_display instead" \
  --expires 2026-12-01
```

Both `--reason` and `--expires` are required. The entry goes into
`api-contract-allow.yml`; commit it. The change is still reported, but no
longer fails the check:

```console
$ api-contract check
API contract: 4 changes (2 breaking, 2 allowed)

BREAKING
  POST /api/orders/  new required request field "currency"
      allowed until 2026-11-15: Clients send currency since 4.0
  GET /api/orders/{id}/  response field "total" type changed: number -> string
      allowed until 2026-12-01: Mobile 4.2+ reads total_display instead

POTENTIALLY BREAKING
  GET /api/orders/{id}/  response field "status" enum value added: "on_hold"
      id: GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"

SAFE
  POST /api/coupons/  new endpoint
$ echo $?
0
```

The printed `allow` command is already shell-safe, including for ids that
contain double quotes (enum values do), so copy it as printed. See
[Allowlist](allowlist.md) for hand-typed ids.

Once the change has shipped, run `api-contract snapshot` and commit it: the new
schema becomes the baseline and the allowlist entry goes stale. This workflow
is described in [Continuous integration](ci.md#updating-the-snapshot).
