# Python API

The CLI is a thin layer over a small Python API. Everything below is exported
from `api_contract`:

```python
from api_contract import (
    load_spec,
    normalize,
    diff,
    check,
    snapshot,
    attribute,
    load_config,
    get_loader,
    Config,
    CheckResult,
    Change,
    Severity,
    Direction,
    Rules,
    DEFAULT_RULES,
    AllowEntry,
    BaseLoader,
    Loader,
    LoaderError,
    ApiContractError,
)
```

The examples use the `old.yaml` and `new.yaml` specs and the `pyproject.toml`
from the [home page](index.md#a-30-second-example), run from their directory.

## Functions

### `load_spec(source, *, config=None) -> dict`

Load the raw OpenAPI document for a source string (or a loader instance).
Raises `LoaderError` if it cannot be loaded. Pass `config` so that `file:`
paths resolve against the config file's directory.

```python
old = load_spec("file:old.yaml")
new = load_spec("file:new.yaml")
```

### `normalize(spec, *, ignore_keys=None) -> dict`

The canonical form that snapshots store: `$ref`s resolved, keys sorted,
docs-only keys dropped. `ignore_keys` defaults to the
[default list](configuration.md#ignore_keys-and-extra_ignore_keys). Normalizing
a snapshot returns an equal document.

```python
snap = normalize(old)
```

### `diff(old, new, *, rules=None, loader=None, ignore_keys=None) -> list[Change]`

Changes from `old` to `new`, worst first. Both arguments can be raw specs or
snapshots. `rules` is a `Rules` or a plain `{kind: severity}` dict. When
`loader` (the new spec's loader) is given, each change is attributed to the
code behind it.

```python
changes = diff(old, new)
for c in changes:
    print(c.severity.value, c.kind, c.id)
```

```text
breaking required-request-field-added POST /api/orders/:request:currency:required-request-field-added
breaking type-changed GET /api/orders/{}/:response:200:total:type-changed
potentially-breaking response-enum-value-added GET /api/orders/{}/:response:200:status:response-enum-value-added:"on_hold"
safe endpoint-added POST /api/coupons/:endpoint-added
```

Overriding a rule:

```python
changes = diff(old, new, rules={"enum-value-added": "safe"})
[c.severity.value for c in changes]  # ['breaking', 'breaking', 'safe', 'safe']
```

### `snapshot(config=None, *, source=None, output=None) -> Path`

Write the normalized schema of `source` (default: the configured one) to
`output` (default: the configured snapshot path) and return the path.

```python
path = snapshot(load_config(), source="file:old.yaml")
```

### `check(config=None, *, source=None, fail_on=None, today=None) -> CheckResult`

Diff the current schema against the snapshot and apply the allowlist. `source`
may also be a loader instance. `fail_on` overrides the config (`"breaking"` or
`"potentially-breaking"`), and `today` pins the date used for allowlist expiry.
Raises `ApiContractError` if there is no snapshot or source.

```python
result = check()
result.exit_code  # 0 or 1
result.ok  # True when nothing fails and no allowlist entry expired
result.failing  # list[Change]: at or above fail_on, and not allowed
result.changes  # every Change
result.expired  # list[AllowEntry]
result.stale  # list[AllowEntry]
result.count(Severity.BREAKING)
```

### `attribute(changes, loader) -> None`

Fill `Change.attribution` in place. `diff(..., loader=...)` calls it for you.
It never raises: a loader that fails to attribute leaves `None`.

```python
loader = get_loader("fastapi:app.main:app")
attribute(changes, loader)
```

### `load_config(path=None, *, start=None) -> Config`

Load configuration from `path`, or discover it from `start` (the working
directory). `Config` has `source`, `snapshot`, `allowlist`, `rules`, `fail_on`,
`ignore_keys` and `path`. See [Configuration](configuration.md).

```python
config = load_config("pyproject.toml")
config.source, config.fail_on.value, config.snapshot.name
```

### `get_loader(source) -> Loader`

Instantiate the loader for a source string. Raises `LoaderError` for an empty
source or a missing framework (the message includes the `pip install` hint).

## Types

| Name | What it is |
|---|---|
| `Change` | One difference. Fields: `kind`, `severity`, `direction`, `method`, `path` (positional), `raw_path`, `location`, `pointer`, `detail`, `old`, `new`, `message`, `component`, `attribution`; properties `id`, `endpoint`, `allowed`; `to_dict()` gives the [JSON](reports.md#json) form |
| `CheckResult` | Returned by `check`: `changes`, `fail_on`, `expired`, `stale`, `failing`, `ok`, `exit_code`, `count()` |
| `Severity` | `BREAKING`, `POTENTIALLY_BREAKING`, `SAFE` (values `"breaking"`, `"potentially-breaking"`, `"safe"`) |
| `Direction` | `REQUEST`, `RESPONSE`, `NONE` |
| `Rules` | Severity overrides; `Rules({...}).severity(kind)` |
| `DEFAULT_RULES` | `dict[str, Severity]` of all [74 kinds](rules.md) |
| `AllowEntry` | An [allowlist](allowlist.md) entry: `id`, `reason`, `expires` (a `datetime.date`) |
| `Config` | The loaded configuration |
| `ApiContractError` | Base class of user-facing errors. The CLI exits 2 on it |
| `LoaderError` | An `ApiContractError` for failures to load a schema |

## Writing a custom loader

A loader turns the target part of a source string into an OpenAPI document. A
source is `<kind>:<target>`; the kind picks the loader class from a registry,
and the target (everything after the first colon) is passed to its
constructor untouched.

A loader needs:

- `__init__(target)`;
- `load() -> dict`, returning the raw, un-normalized OpenAPI document;
- optionally `attribute(method, path)`, returning a string that names the code
  behind an operation, and `attribute_schema(component_name)`, doing the same
  for `#/components/schemas/<name>`.

`BaseLoader` provides the constructor (it stores `self.target`) and
attribution methods that return `None`, so subclass it and write `load()`.
`api_contract.loaders.base` also provides:

- `register_loader(kind, "module:Class")` to add a kind. It is also exported
  from `api_contract.loaders`, along with `import_string`, which imports
  `"pkg.mod:attr"` with the working directory on `sys.path`.
- `describe_callable(func)`, which returns `"module.func (relative/file.py:LINE)"`
  for a function, or `None`. Use it to build attribution strings in the same
  format as the built-in loaders.

```python
# shopspec.py
from api_contract.loaders import BaseLoader, LoaderError, import_string, register_loader
from api_contract.loaders.base import describe_callable


class RegistryLoader(BaseLoader):
    """``registry:shop.routes:router`` reads ``router.openapi()``."""

    def load(self) -> dict:
        try:
            router = import_string(self.target)
        except ImportError as exc:
            raise LoaderError(str(exc)) from exc
        return router.openapi()

    def attribute(self, method: str, path: str) -> str | None:
        router = import_string(self.target)
        handler = router.handlers.get((method, path))
        return describe_callable(handler) if handler else None


register_loader("registry", "shopspec:RegistryLoader")
```

With that registered, `registry:routes:router` works anywhere a source is
accepted (`load_spec`, `check(source=...)`, `diff`). Real output of `check` with
the loader above, where `routes.get_order` is the handler:

```text
  GET /api/orders/{id}/  response field "total" type changed: number -> string
      at: routes.get_order (routes.py:2)
      id: GET /api/orders/{}/:response:200:total:type-changed
```

Rules for loaders:

- Raise `LoaderError` for anything the user must fix; the CLI turns it into
  exit code 2. A missing framework (`ModuleNotFoundError`) is turned into a
  `pip install` hint for you.
- `path` passed to `attribute` is the template from the raw spec with its
  original parameter names (`/orders/{order_id}/`), and `method` is upper case.
- Attribution is best effort: exceptions from `attribute()` and
  `attribute_schema()` are swallowed, because attribution must never fail a
  check.
- The CLI does not load plugins, so `register_loader` must run before the
  source is resolved: import your module first, as in a small wrapper
  script that calls `api_contract.cli.main(argv)`. If you do not need
  attribution, a `file:module:callable` source (a function returning the spec
  dict) needs no custom loader at all.
