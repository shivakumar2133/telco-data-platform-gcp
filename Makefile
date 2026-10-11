# Read GCP_PROJECT_ID / GCP_REGION from .env (if present)
-include .env

VENV := .venv
PY   := $(VENV)/bin/python
COMPOSE_SOURCES := docker compose --env-file .env -f sources/docker-compose.sources.yml

TF        := terraform -chdir=infra/terraform
DEV_EMAIL  = $(shell gcloud config get-value account 2>/dev/null)
TF_VARS    = -var-file=envs/dev.tfvars -var="project_id=$(GCP_PROJECT_ID)" \
             -var="region=$(GCP_REGION)" -var="developer_email=$(DEV_EMAIL)"

.PHONY: setup lint format test check \
        generate generate-small sources-up sources-down sources-reset sources-status \
        load-sources verify1 phase1 \
        tf-init tf-fmt tf-validate tf-plan tf-apply tf-output tf-destroy secrets-push verify2 \
        drop-files ingest-db ingest-api ingest-files ingest ingest-full simulate-changes \
        ingest-local verify3

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

# ---------- Phase 2: infrastructure as code
tf-init:
	$(TF) init -backend-config="bucket=$(GCP_PROJECT_ID)-tfstate" -backend-config="prefix=envs/dev"

tf-fmt:
	$(TF) fmt -recursive

tf-validate:
	$(TF) fmt -recursive -check
	$(TF) validate

tf-plan:
	$(TF) plan $(TF_VARS) -out=dev.tfplan

tf-apply:
	$(TF) apply dev.tfplan

tf-output:
	$(TF) output

tf-destroy:  ## deletes the bucket, datasets and SAs (not the tfstate bucket)
	$(TF) destroy $(TF_VARS)

secrets-push:
	bash scripts/push_secrets.sh

verify2:
	$(PY) -m scripts.verify_phase2

# ---------- Phase 3: ingestion to Bronze (runs as sa-ingest via impersonation)
drop-files:
	$(PY) -m ingestion.run drop-files

ingest-db:
	$(PY) -m ingestion.run db --system all

ingest-full:  ## ignore watermarks and reload every table
	$(PY) -m ingestion.run db --system all --full

ingest-api:
	$(PY) -m ingestion.run api

ingest-files:
	$(PY) -m ingestion.run files

ingest:
	$(PY) -m ingestion.run all

simulate-changes:
	$(PY) -m sources.simulate_changes

ingest-local:  ## offline dry run: lake + metadata under ./local_run, no GCP
	$(PY) -m ingestion.run --local local_run drop-files
	$(PY) -m ingestion.run --local local_run all

verify3:
	$(PY) -m scripts.verify_phase3
