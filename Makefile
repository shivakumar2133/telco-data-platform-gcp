VENV := .venv
PY   := $(VENV)/bin/python
COMPOSE_SOURCES := docker compose --env-file .env -f sources/docker-compose.sources.yml

.PHONY: setup lint format test check \
        generate generate-small sources-up sources-down sources-reset sources-status \
        load-sources verify1 phase1

# ---------- Phase 0
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

# ---------- Phase 1: synthetic data + local source systems
generate:
	$(PY) -m data_generator.generate

generate-small:
	$(PY) -m data_generator.generate --scale 0.1

sources-up:
	$(COMPOSE_SOURCES) up -d --build

sources-status:
	$(COMPOSE_SOURCES) ps

sources-down:
	$(COMPOSE_SOURCES) down

sources-reset:  ## deletes all source DB data volumes
	$(COMPOSE_SOURCES) down -v

load-sources:
	$(PY) -m sources.load_sources

verify1:
	$(PY) -m scripts.verify_phase1

phase1: generate sources-up load-sources verify1
