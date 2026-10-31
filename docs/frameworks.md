# Frameworks

`api-contract` never reads your source code. It imports your app, asks your
OpenAPI library for the schema, and compares that. The `source` setting tells it
how.

| Framework | Library | Extra | `source` |
|---|---|---|---|
| Django REST framework | drf-spectacular | `django` | `django` or `django:drf` |
| Django | django-ninja | `ninja` | `django`, `django:ninja` or `django:ninja:pkg.module:api` |
| FastAPI | built in | `fastapi` | `fastapi:pkg.module:app` |
| Flask | APIFlask | `apiflask` | `flask:pkg.module:app` |
| Flask | flask-smorest | `smorest` | `flask:pkg.module:app` |
| Flask | flask-openapi3 | `flask-openapi3` | `flask:pkg.module:app` |
| Anything else | | none | `file:openapi.json`, or `file:pkg.module:build_spec` |

A source is `<kind>:<target>`. A source with no known kind is treated as a file
path, so `source = "openapi.yaml"` works.

The loaders import your app, so install your project's own dependencies in the
environment that runs `api-contract`. The extras only add what is needed to
generate the schema.

Module paths are resolved against the directory you run the command from (the
working directory is added to `sys.path`).

## Source strings

| Source | Meaning |
|---|---|
| `django` | Django: drf-spectacular if usable, else the one NinjaAPI in the URLs |
| `django:drf` | Django REST framework with drf-spectacular |
| `django:ninja` | The one NinjaAPI in the URLs |
| `django:ninja:pkg.module:api` | An explicit NinjaAPI instance |
| `fastapi:pkg.module:app` | A FastAPI instance, or a callable returning one |
| `flask:pkg.module:app` | A Flask instance, or a factory such as `create_app` |
| `flask-routes:pkg.module:app` | Endpoints and methods only, from a Flask app's URL map (no OpenAPI library needed) |
| `file:path/to/openapi.json` | A JSON or YAML file (OpenAPI 3.0/3.1, or Swagger 2.0) |
| `git:origin/main:openapi.json` | A JSON or YAML file as committed at a git revision |
| `file:pkg.module:callable` | A callable that returns the OpenAPI dict |

`--source` overrides the configured source for one run. Any other `<kind>`
registered with [`register_loader`](python-api.md#writing-a-custom-loader)
works the same way.

## Auto-detection

Detection happens in two places, and only for Django and Flask:

- **Django** (`source = "django"`): drf-spectacular is used when it can be
  imported and `rest_framework` is in `INSTALLED_APPS`; otherwise the loader
  looks for a single `NinjaAPI` in the URL patterns.
- **Flask**: the OpenAPI library is detected from the app, in the order
  APIFlask, flask-smorest, flask-openapi3.

FastAPI and `file:` sources need no detection.

## Attribution

For each change, `api-contract` tries to name the code behind it, so the
failure points at a file and not only at a URL:

| Framework | Change inside a named schema | Any other change |
|---|---|---|
| DRF | the serializer class | the view method, plus the serializer |
| django-ninja | the `Schema` class (when its name is unique) | the view function |
| FastAPI | the pydantic model | the endpoint function |
| APIFlask, flask-smorest | the marshmallow `Schema` class | the view function or `MethodView` method |
| flask-openapi3 | the pydantic model | the view function |

Attribution appears as an `at:` line in the [text report](reports.md#text)
and in the `attribution` field of the [JSON report](reports.md#json), in the
form `dotted.name (relative/file.py:LINE)`. DRF adds the serializer after the
view, as shown below.

Attribution is best effort. If it fails, the change is still reported, without
the `at:` line. A removed endpoint's code is gone, so `snapshot` records each
operation's handler in the snapshot: when the endpoint later disappears, the
report names where it used to be (`at: orders.views.legacy (orders/views.py:12)
(removed)`). Snapshots taken before this was added have no record, so their
removed endpoints are not attributed until the snapshot is retaken.

## Django REST framework (drf-spectacular)

```bash
pip install --pre "api-contract[django]"
```

- Source `django` picks drf-spectacular when it is importable **and**
  `rest_framework` is in `INSTALLED_APPS`. Otherwise it looks for a single
  django-ninja API. Use `django:drf` to force drf-spectacular.
- Django must be configured. Set `DJANGO_SETTINGS_MODULE`, or run through
  `manage.py api_contract` (see below).
- The schema is generated with `SchemaGenerator().get_schema(request=None,
  public=True)`, so your `SPECTACULAR_SETTINGS` apply. Because `public=True`,
  endpoints are not filtered by the current user's permissions.
- Attribution looks like
  `orders.views.OrderViewSet.retrieve (orders/views.py:24) · serializer:
  orders.serializers.OrderSerializer`.
- File locations are shown only for code inside the working directory. Code
  from site-packages is named without a path.

### The management command

Add the app so Django finds the command:

```python
INSTALLED_APPS = [
    ...
    "rest_framework",
    "drf_spectacular",
    "api_contract.contrib.django",
]
```

Then:

```bash
python manage.py api_contract snapshot
python manage.py api_contract check --format markdown
```

It runs the same CLI. Since `manage.py` has already set Django up, you do not
need `DJANGO_SETTINGS_MODULE` in the environment. If your config has no
`source`, the command defaults to `django`.

**Flags go after the subcommand.** `api-contract` options (`--format`,
`--config`, `--source`, `--fail-on`, `--output`) must come after `snapshot` /
`check` / ..., because the command forwards everything after it unchanged:

```bash
python manage.py api_contract check --format markdown     # works
python manage.py api_contract --format markdown check     # error: unrecognized arguments
```

Django's own options (`--settings`, `--pythonpath`) go before the subcommand:

```bash
python manage.py api_contract --settings=myproject.settings check
```

### Known gaps

- Serializer attribution reads a **private** drf-spectacular registry
  (`SchemaGenerator.registry._components`). A drf-spectacular upgrade can break
  it. When it does, attribution falls back to the view, and the check itself is
  unaffected.
- A change to one serializer is reported once per operation and media type that
  uses it. Removing one field from a serializer used by a ViewSet can produce
  more than a dozen changes (list, create, retrieve, update, partial update, and
  the form-encoded variants). Allowlist them with a wildcard (see
  [Allowlist](allowlist.md)).

## django-ninja

```bash
pip install --pre "api-contract[ninja]"
```

| Source | Meaning |
|---|---|
| `django:ninja` | The one `NinjaAPI` found in the URL patterns. An error if there are none, or several. |
| `django:ninja:myproject.api:api` | An explicit `NinjaAPI` instance. Use this with several APIs. |
| `django` | drf-spectacular if usable (see above), else the same as `django:ninja`. |

Schema classes are matched by name across all `ninja.Schema` subclasses. If two
classes share a name, the change is attributed to the view function instead.

## FastAPI

```bash
pip install --pre "api-contract[fastapi]"
```

```toml
source = "fastapi:app.main:app"
```

The target is a `FastAPI` instance, or a callable that returns one (an app
factory such as `fastapi:app.main:create_app`).

### Mounted sub-apps

FastAPI leaves apps added with `app.mount("/v1", sub_app)` out of the parent's
OpenAPI document. The loader merges every mounted FastAPI app back in
(including mounts inside mounts): its paths get the mount prefix
(`/v1/orders/{id}`) and its components join the parent's. When a sub-app's
component has the same name as a different parent component, it is renamed
`<Name>__<prefix>` (`Order__v1`) and its references follow; identical
components are shared. A sub-app's top-level `security` is applied to its own
operations. Other mounted ASGI apps (`StaticFiles`, ...) are skipped.
Endpoints and models inside sub-apps are attributed like the parent's.

### Known gaps

- Model attribution matches pydantic model names reachable from route response
  models and body parameters. Models used only in other ways are attributed to
  the endpoint function.

## Flask

```bash
pip install --pre "api-contract[smorest]"        # or apiflask, flask-openapi3
```

```toml
source = "flask:myapp:create_app"
```

The target is a `Flask` instance or a factory (`create_app`) that takes no
arguments. The library is detected from the app, in this order:

1. APIFlask (`app.spec`)
2. flask-smorest (the `Api` registered on the app)
3. flask-openapi3 (`app.api_doc`)

If none is found, the loader fails with an error that lists the three. For
anything else (Flasgger, hand-written specs, ...), export the spec yourself and
use a `file:` source that points at a callable returning the OpenAPI dict:
`file:myapp.spec:build_spec`. flask-restx and other Swagger 2.0 generators work
through such a callable too: Swagger 2.0 is converted to OpenAPI 3.0 first.

### Route inventory: `flask-routes:`

A Flask app with no OpenAPI library still has a URL map. `flask-routes:` builds
a minimal document from it: every rule and method (except `HEAD`, `OPTIONS` and
`static`), with path parameters typed from their converters (`int` ->
integer, `float` -> number, `uuid` -> string/uuid, anything else -> string).

```toml
source = "flask-routes:myapp:create_app"
```

That catches removed and renamed endpoints and methods, and changed path
parameter types, which are the breaks a mobile client notices first. It cannot
see request or response bodies, so `check` warns that no operation declares a
typed response. Move to `flask:` once an OpenAPI library describes the bodies.

The plain `flask` extra installs only Flask; it does not add an OpenAPI
library. Install the extra that matches the library your app uses.

### Known gaps

- **flask-smorest with several `Api` objects**: only the first registered one
  is read. The others are not compared.
- **Schema attribution goes by name.** apispec names a component after its
  marshmallow class minus a `Schema` suffix; a schema built with
  `Schema.from_dict` has no class to point at, so its changes fall back to the
  view function.
- Blueprints are covered.

## Files and other frameworks

```toml
source = "file:openapi.yaml"                    # JSON or YAML, relative to the config file
source = "file:myapp.spec:build_spec"           # a callable (or dict) in a module
```

Use this for any stack that can produce an OpenAPI 3.0 or 3.1 document, or a
Swagger 2.0 one (converted to OpenAPI 3.0 before comparing: body and form
parameters, `consumes`/`produces`, `basePath`, security definitions,
`x-nullable`). Attribution is not available for files.

You can also compare any two documents or snapshots directly:

```bash
api-contract diff old.json new.yaml
api-contract diff old.json fastapi:app.main:app
```

## Known gaps at a glance

| Framework | Gap |
|---|---|
| DRF | Serializer attribution reads a private drf-spectacular registry; one serializer change is reported once per operation and media type |
| django-ninja | Schema classes with the same name are attributed to the view function instead |
| FastAPI | Models used outside response models and bodies are attributed to the endpoint |
| Flask | Only the first flask-smorest `Api` is read; `Schema.from_dict` schemas are attributed to the view |
| All | See [Limitations](limitations.md) |
