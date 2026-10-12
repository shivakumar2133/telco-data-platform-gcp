"""Central configuration. Reads environment variables (optionally from .env).

Oracle analogy: like a tnsnames.ora + init parameters, in one place,
so no script hard-codes a project ID, bucket or dataset name.
Names here must match infra/terraform.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

DATASETS = ("bronze", "silver", "gold", "ops", "scratch")
SERVICE_ACCOUNTS = ("ingest", "transform", "reporting", "analyst")


@dataclass(frozen=True)
class Settings:
    project_id: str
    region: str
    bq_location: str
    env: str

    @property
    def tfstate_bucket(self) -> str:
        return f"{self.project_id}-tfstate"

    @property
    def lake_bucket(self) -> str:
        return f"{self.project_id}-lake"

    def sa_email(self, name: str) -> str:
        if name not in SERVICE_ACCOUNTS:
            raise ValueError(
                f"Unknown service account {name!r}; expected one of {SERVICE_ACCOUNTS}"
            )
        return f"sa-{name}@{self.project_id}.iam.gserviceaccount.com"

    def table(self, dataset: str, table: str) -> str:
        """Fully qualified BigQuery table id: project.dataset.table"""
        return f"{self.project_id}.{dataset}.{table}"


def get_settings(load_env_file: bool = True) -> Settings:
    if load_env_file:
        load_dotenv()  # does not override variables already set in the shell

    project_id = os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID is not set. Copy .env.example to .env and fill it in.")

    region = os.getenv("GCP_REGION", "us-central1")
    return Settings(
        project_id=project_id,
        region=region,
        bq_location=os.getenv("BQ_LOCATION", region),
        env=os.getenv("ENV", "dev"),
    )
