"""Central configuration. Reads environment variables (optionally from .env).

Oracle analogy: like a tnsnames.ora + init parameters, in one place,
so no script hard-codes a project ID or region.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    project_id: str
    region: str
    bq_location: str
    env: str

    @property
    def tfstate_bucket(self) -> str:
        return f"{self.project_id}-tfstate"


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
