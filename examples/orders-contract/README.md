# Orders contract example

A runnable, dependency-free walk through the api-contract loop. It uses two
small OpenAPI files for an invented "Shop API": `specs/v1.yaml` is the released
contract, and `specs/v2.yaml` changes `total` from number to string.

```bash
pip install --pre api-contract
./run.sh
```

`run.sh` works in a temporary copy, so nothing in this directory changes. It:

1. writes a snapshot from v1 (`api-contract snapshot`);
2. checks v1 against it: no changes, exit 0;
3. checks v2 (the `source` in `pyproject.toml`): a breaking change, exit 1;
4. acknowledges the change with `api-contract allow`, after which `check`
   exits 0.

For a real framework app, replace `source` with `django-drf:...`, `fastapi:...`
or a Flask source; see the [quickstart](../../docs/quickstart.md). The test
suite runs this script (`tests/test_example.py`).
