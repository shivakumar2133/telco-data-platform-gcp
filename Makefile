VENV := .venv
PY   := $(VENV)/bin/python

.PHONY: setup lint format test check

setup:
	python3.12 -m venv $(VENV)
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements-dev.txt
	$(VENV)/bin/pre-commit install

lint:
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

format:
	$(VENV)/bin/ruff check --fix .
	$(VENV)/bin/ruff format .

test:
	$(VENV)/bin/pytest -q

check:
	PYTHON=$(PY) bash scripts/verify_phase0.sh
