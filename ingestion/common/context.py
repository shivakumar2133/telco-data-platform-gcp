"""Everything one pipeline run needs, built once and passed to every extractor."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from ingestion.common.config import Settings, get_settings
from ingestion.common.lake import GcsLake, Lake, LocalLake
from ingestion.common.metadata import (
    BigQueryBronzeLoader,
    BigQueryMetaStore,
    BronzeLoader,
    LocalBronzeLoader,
    LocalMetaStore,
    MetaStore,
)


def new_run_id(now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return f"{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}"


@dataclass
class RunContext:
    settings: Settings
    lake: Lake
    meta: MetaStore
    loader: BronzeLoader
    ingest_sa: str  # service account to act as ('' = your own credentials)
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    run_id: str = field(default_factory=new_run_id)


def build_context(local_dir: Path | None = None) -> RunContext:
    s = get_settings()

    if local_dir is not None:
        # Offline mode: lake + metadata on disk, secrets from .env
        os.environ.setdefault("SECRETS_BACKEND", "env")
        reader_pw = os.getenv("ETL_READER_PASSWORD", "")
        for system in ("oracle", "mssql", "postgres"):
            os.environ.setdefault(f"{system.upper()}_ETL_READER_PASSWORD", reader_pw)
        local_dir = Path(local_dir)
        return RunContext(
            settings=s,
            lake=LocalLake(local_dir / "lake"),
            meta=LocalMetaStore(local_dir / "meta"),
            loader=LocalBronzeLoader(),
            ingest_sa="",
        )

    from ingestion.common.gcp_auth import impersonate

    ingest_sa = os.getenv("INGEST_SA", s.sa_email("ingest"))
    creds = impersonate(ingest_sa) if ingest_sa else None
    return RunContext(
        settings=s,
        lake=GcsLake(s.lake_bucket, credentials=creds, project=s.project_id),
        meta=BigQueryMetaStore(s.project_id, s.bq_location, credentials=creds),
        loader=BigQueryBronzeLoader(s.project_id, s.bq_location, credentials=creds),
        ingest_sa=ingest_sa,
    )
