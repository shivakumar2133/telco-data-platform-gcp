"""Pipeline metadata: load audit trail, watermarks, and Bronze loading.

BigQuery implementations write with LOAD JOBS (free), never DML or streaming
inserts. Watermarks are append-only: the current value is the latest row per
object. That makes every write an insert, with history for free.

Local implementations (JSON lines + Parquet on disk) power tests and --local runs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import pandas as pd
import pyarrow.parquet as pq


@dataclass
class AuditRecord:
    run_id: str
    source_system: str
    object_name: str
    load_type: str  # FULL | INCREMENTAL | FILE
    status: str = "RUNNING"  # SUCCESS | FAILED | REJECTED | SKIPPED
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    watermark_from: datetime | None = None
    watermark_to: datetime | None = None
    source_row_count: int | None = None
    loaded_row_count: int | None = None
    source_checksum: str | None = None
    gcs_uri: str | None = None
    error_message: str | None = None

    def finish(self, status: str, error: str | None = None) -> AuditRecord:
        self.status = status
        self.error_message = error[:1000] if error else None
        self.finished_at = datetime.now(UTC)
        return self

    def to_json(self) -> dict:
        return {
            k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in asdict(self).items()
        }


def frame_checksum(df: pd.DataFrame) -> str:
    """Order-independent fingerprint of a DataFrame's content.
    Same rows in any order -> same value, so source and target can be compared."""
    if df.empty:
        return "0" * 16
    row_hashes = pd.util.hash_pandas_object(df.astype(str), index=False)
    return f"{int(row_hashes.sum()) & 0xFFFFFFFFFFFFFFFF:016x}"


def file_md5(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()  # noqa: S324 - fingerprint, not security


# ------------------------------------------------------------------ interfaces
class MetaStore(Protocol):
    def get_watermarks(self) -> dict[tuple[str, str], datetime]: ...
    def set_watermark(self, system: str, obj: str, column: str, value: datetime) -> None: ...
    def write_audit(self, record: AuditRecord) -> None: ...
    def processed_file_checksums(self) -> set[str]: ...


class BronzeLoader(Protocol):
    def load(self, table_name: str, uri: str) -> int: ...


# ------------------------------------------------------------------ local
class LocalMetaStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.audit_path = self.root / "load_audit.jsonl"
        self.wm_path = self.root / "watermarks.jsonl"

    def _rows(self, path: Path) -> list[dict]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def get_watermarks(self) -> dict[tuple[str, str], datetime]:
        out: dict[tuple[str, str], datetime] = {}
        for r in self._rows(self.wm_path):  # file order = write order; last wins
            out[(r["source_system"], r["object_name"])] = datetime.fromisoformat(r["last_value"])
        return out

    def set_watermark(self, system: str, obj: str, column: str, value: datetime) -> None:
        row = {
            "source_system": system,
            "object_name": obj,
            "watermark_column": column,
            "last_value": value.isoformat(),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        with self.wm_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def write_audit(self, record: AuditRecord) -> None:
        with self.audit_path.open("a") as f:
            f.write(json.dumps(record.to_json()) + "\n")

    def processed_file_checksums(self) -> set[str]:
        return {
            r["source_checksum"]
            for r in self._rows(self.audit_path)
            if r["source_system"] == "files" and r["status"] == "SUCCESS"
        }

    def audit_rows(self) -> list[dict]:
        return self._rows(self.audit_path)


class LocalBronzeLoader:
    """Counts rows in the Parquet file(s) instead of loading BigQuery."""

    def load(self, table_name: str, uri: str) -> int:
        p = Path(uri)
        files = sorted(p.parent.glob(p.name)) if "*" in p.name else [p]
        return sum(pq.ParquetFile(f).metadata.num_rows for f in files)


# ------------------------------------------------------------------ BigQuery
class BigQueryMetaStore:
    def __init__(self, project: str, location: str, credentials=None) -> None:
        from google.cloud import bigquery

        self.bq = bigquery
        self.client = bigquery.Client(project=project, credentials=credentials, location=location)
        self.audit_table = f"{project}.ops.load_audit"
        self.wm_table = f"{project}.ops.watermarks"
        self._schemas: dict[str, list] = {}

    def _append_json(self, table_id: str, rows: list[dict]) -> None:
        if table_id not in self._schemas:
            self._schemas[table_id] = self.client.get_table(table_id).schema
        cfg = self.bq.LoadJobConfig(
            schema=self._schemas[table_id],
            source_format=self.bq.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=self.bq.WriteDisposition.WRITE_APPEND,
        )
        self.client.load_table_from_json(rows, table_id, job_config=cfg).result()

    def get_watermarks(self) -> dict[tuple[str, str], datetime]:
        sql = f"""
            SELECT source_system, object_name, last_value
            FROM `{self.wm_table}`
            QUALIFY ROW_NUMBER() OVER (
              PARTITION BY source_system, object_name ORDER BY updated_at DESC) = 1"""
        return {
            (r.source_system, r.object_name): r.last_value
            for r in self.client.query(sql).result()
            if r.last_value is not None
        }

    def set_watermark(self, system: str, obj: str, column: str, value: datetime) -> None:
        self._append_json(
            self.wm_table,
            [
                {
                    "source_system": system,
                    "object_name": obj,
                    "watermark_column": column,
                    "last_value": value.isoformat(),
                    "updated_at": datetime.now(UTC).isoformat(),
                }
            ],
        )

    def write_audit(self, record: AuditRecord) -> None:
        self._append_json(self.audit_table, [record.to_json()])

    def processed_file_checksums(self) -> set[str]:
        sql = f"""
            SELECT DISTINCT source_checksum FROM `{self.audit_table}`
            WHERE source_system = 'files' AND status = 'SUCCESS'"""
        return {r.source_checksum for r in self.client.query(sql).result()}


class BigQueryBronzeLoader:
    """Append Parquet from GCS to bronze.<table>, partitioned by ingestion day.
    New columns in the source are added automatically (schema evolution)."""

    def __init__(self, project: str, location: str, credentials=None) -> None:
        from google.cloud import bigquery

        self.bq = bigquery
        self.client = bigquery.Client(project=project, credentials=credentials, location=location)
        self.project = project

    def load(self, table_name: str, uri: str) -> int:
        bq = self.bq
        cfg = bq.LoadJobConfig(
            source_format=bq.SourceFormat.PARQUET,
            write_disposition=bq.WriteDisposition.WRITE_APPEND,
            time_partitioning=bq.TimePartitioning(field="_ingested_at"),
            schema_update_options=[
                bq.SchemaUpdateOption.ALLOW_FIELD_ADDITION,
                bq.SchemaUpdateOption.ALLOW_FIELD_RELAXATION,
            ],
        )
        job = self.client.load_table_from_uri(
            uri, f"{self.project}.bronze.{table_name}", job_config=cfg
        )
        job.result()
        return int(job.output_rows or 0)
