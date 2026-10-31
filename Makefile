# One virtualenv with every extra: the Django and FastAPI/Flask stacks coexist.
VENV ?= .venv
PY := $(VENV)/bin/python

.PHONY: install test lint typecheck cov docs build bench all

install:
	uv venv $(VENV) || python3 -m venv $(VENV)
	uv pip install -p $(VENV) -e ".[dev,test-web,test-django,docs]" || $(PY) -m pip install -e ".[dev,test-web,test-django,docs]"

test:
	$(VENV)/bin/pytest -q

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

typecheck:
	$(VENV)/bin/mypy

cov:
	$(VENV)/bin/pytest -q --cov=api_contract --cov-report=term-missing:skip-covered --cov-fail-under=75

docs:
	$(VENV)/bin/mkdocs build --strict

build:
	$(PY) -m build

bench:
	$(PY) benchmarks/bench.py

all: lint typecheck test docs
