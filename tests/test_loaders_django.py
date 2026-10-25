"""Django loader tests (drf-spectacular and django-ninja).

Every test runs in a subprocess. Django settings can be configured only once
per process, the DRF and Ninja example projects need different settings, and
the "changed" variants are switched by an env var that is read at import time.
Subprocesses are also the real flow: they run ``python -m api_contract.cli`` and
``manage.py api_contract`` exactly as a user's CI would. (pytest-django would
need one settings module per pytest run and could not toggle the variants.)
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("django")


def require_ninja():
    # Importing ninja reads Django settings, which this (settings-less) process lacks,
    # so check for it without importing.
    if importlib.util.find_spec("ninja") is None:
        pytest.skip("django-ninja is not installed")


APPS = Path(__file__).parent / "apps"
DRF_DIR, NINJA_DIR = APPS / "django_drf", APPS / "django_ninja"
REMOVE_TOTAL = {"API_CONTRACT_TEST_REMOVE_TOTAL": "1"}

PROJECTS = {
    "drf": (DRF_DIR, "drfproj.settings"),
    "ninja": (NINJA_DIR, "ninjaproj.settings"),
}

_PROBE = """
import json, sys
from api_contract.loaders.django import DjangoLoader
loader = DjangoLoader(sys.argv[1])
spec = loader.load()
out = {"spec": spec, "ops": {}, "schemas": {}}
for path, item in spec["paths"].items():
    for method in item:
        out["ops"][method.upper() + " " + path] = loader.attribute(method.upper(), path)
for name in spec.get("components", {}).get("schemas", {}):
    out["schemas"][name] = loader.attribute_schema(name)
print(json.dumps(out))
"""


def run(project, args, *, env=None, settings=True):
    cwd, settings_module = PROJECTS[project]
    full_env = {**os.environ, "PYTHONPATH": str(cwd), **(env or {})}
    full_env.pop("DJANGO_SETTINGS_MODULE", None)
    if settings:
        full_env["DJANGO_SETTINGS_MODULE"] = settings_module
    return subprocess.run(
        [sys.executable, *args], cwd=cwd, env=full_env, capture_output=True, text=True, timeout=120
    )


def probe(project, target="", env=None):
    proc = run(project, ["-c", _PROBE, target], env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip().splitlines()[-1])


def write_config(tmp_path, source="django"):
    config = tmp_path / "api-contract.toml"
    config.write_text(f'source = "{source}"\n', encoding="utf-8")
    return config


def cli(project, tmp_path, *args, env=None, source="django"):
    config = write_config(tmp_path, source)
    return run(
        project, ["-m", "api_contract.cli", args[0], "--config", str(config), *args[1:]], env=env
    )


def flow(project, tmp_path, source, schema_name, needle):
    """snapshot -> remove `total` -> check fails naming `needle` -> revert -> passes."""
    assert cli(project, tmp_path, "snapshot", source=source).returncode == 0
    assert (tmp_path / "api-contract.json").exists()
    assert cli(project, tmp_path, "check", source=source).returncode == 0

    broken = cli(project, tmp_path, "check", source=source, env=REMOVE_TOTAL)
    assert broken.returncode == 1, broken.stdout + broken.stderr
    assert "total" in broken.stdout
    assert needle in broken.stdout

    assert cli(project, tmp_path, "check", source=source).returncode == 0


# --- DRF ----------------------------------------------------------------------


@pytest.fixture(scope="module")
def drf():
    pytest.importorskip("rest_framework")
    pytest.importorskip("drf_spectacular")
    return probe("drf")


def test_drf_schema_loads(drf):
    spec = drf["spec"]
    assert set(spec["paths"]) == {"/api/orders/", "/api/orders/{id}/"}
    assert set(spec["components"]["schemas"]["Order"]["properties"]) == {
        "id",
        "status",
        "total",
        "note",
    }


def test_drf_attribution_names_viewset_and_serializer(drf):
    text = drf["ops"]["GET /api/orders/{id}/"]
    assert text.startswith("orders.views.OrderViewSet.retrieve (orders/views.py:")
    assert text.endswith("· serializer: orders.serializers.OrderSerializer")
    assert drf["ops"]["POST /api/orders/"].startswith("orders.views.OrderViewSet.create ")


def test_drf_attribute_schema_maps_component_to_serializer(drf):
    assert drf["schemas"]["Order"].startswith(
        "orders.serializers.OrderSerializer (orders/serializers.py:"
    )
    assert drf["schemas"]["PatchedOrder"].startswith("orders.serializers.OrderSerializer ")


def test_drf_explicit_source_and_removed_field():
    changed = probe("drf", "drf", env=REMOVE_TOTAL)
    assert "total" not in changed["spec"]["components"]["schemas"]["Order"]["properties"]


@pytest.mark.parametrize("source", ["django", "django:drf"])
def test_drf_end_to_end(tmp_path, source):
    pytest.importorskip("rest_framework")
    pytest.importorskip("drf_spectacular")
    flow("drf", tmp_path, source, "Order", "OrderSerializer")


def test_missing_settings_gives_guidance(tmp_path):
    pytest.importorskip("rest_framework")
    proc = cli("drf", tmp_path, "snapshot")  # DJANGO_SETTINGS_MODULE is set by run()
    assert proc.returncode == 0
    proc = run(
        "drf",
        ["-m", "api_contract.cli", "snapshot", "--config", str(tmp_path / "api-contract.toml")],
        settings=False,
    )
    assert proc.returncode == 2
    assert "DJANGO_SETTINGS_MODULE" in proc.stderr
    assert "manage.py api_contract" in proc.stderr
    assert "--settings" not in proc.stderr


def test_management_command(tmp_path):
    pytest.importorskip("rest_framework")
    pytest.importorskip("drf_spectacular")
    # No `source` in the config: the command must default it to "django".
    config = tmp_path / "api-contract.toml"
    config.write_text('snapshot = "snap.json"\n', encoding="utf-8")

    def manage(*args, env=None):
        return run(
            "drf",
            ["manage.py", "api_contract", args[0], "--config", str(config), *args[1:]],
            env=env,
            settings=False,
        )

    assert manage("snapshot").returncode == 0, manage("snapshot").stderr
    assert manage("check").returncode == 0
    broken = manage("check", env=REMOVE_TOTAL)
    assert broken.returncode == 1
    assert "OrderSerializer" in broken.stdout
    assert manage("check", "--format", "json").returncode == 0


# --- Ninja --------------------------------------------------------------------


@pytest.fixture(scope="module")
def ninja():
    require_ninja()
    return probe("ninja", "ninja:orders.api:api")


def test_ninja_schema_loads(ninja):
    assert set(ninja["spec"]["paths"]) == {"/api/orders/", "/api/orders/{order_id}"}
    assert "total" in ninja["spec"]["components"]["schemas"]["OrderOut"]["properties"]


def test_ninja_attribution_names_function(ninja):
    assert ninja["ops"]["GET /api/orders/{order_id}"].startswith(
        "orders.api.get_order (orders/api.py:"
    )
    assert ninja["ops"]["POST /api/orders/"].startswith("orders.api.create_order ")
    assert ninja["schemas"]["OrderOut"].startswith("orders.api.OrderOut (orders/api.py:")


def test_ninja_autodetect_finds_single_api():
    require_ninja()
    auto = probe("ninja", "")  # drf_spectacular may be installed, but rest_framework isn't an app
    assert set(auto["spec"]["paths"]) == {"/api/orders/", "/api/orders/{order_id}"}


def test_ninja_end_to_end(tmp_path):
    require_ninja()
    flow("ninja", tmp_path, "django:ninja:orders.api:api", "OrderOut", "orders.api.OrderOut")


def test_ninja_end_to_end_autodetect(tmp_path):
    require_ninja()
    flow("ninja", tmp_path, "django", "OrderOut", "orders.api.OrderOut")
