"""Data-lake storage behind one small interface, with two implementations:

  GcsLake    the real bucket (gs://<project>-lake)
  LocalLake  a folder on disk: unit tests and `--local` dry runs, no cloud needed

Path layout (see infra/terraform/storage.tf):
  landing/<kind>/<file>                          incoming files
  raw/<system>/<object>/dt=YYYY-MM-DD/run_id=<id>/part-00000.parquet   Bronze
  archive/<kind>/<file>    quarantine/<kind>/<file>
"""

from __future__ import annotations

import io
import shutil
from datetime import datetime
from pathlib import Path
from typing import Protocol

import pyarrow as pa
import pyarrow.parquet as pq


class Lake(Protocol):
    def write_bytes(self, path: str, data: bytes) -> None: ...
    def read_bytes(self, path: str) -> bytes: ...
    def list(self, prefix: str) -> list[str]: ...
    def move(self, src: str, dst: str) -> None: ...
    def exists(self, path: str) -> bool: ...
    def uri(self, path: str) -> str: ...


def raw_prefix(system: str, obj: str, ingested_at: datetime, run_id: str) -> str:
    return f"raw/{system}/{obj}/dt={ingested_at:%Y-%m-%d}/run_id={run_id}"


def write_parquet(lake: Lake, path: str, table: pa.Table) -> None:
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    lake.write_bytes(path, buf.getvalue())


class LocalLake:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, path: str) -> Path:
        return self.root / path

    def write_bytes(self, path: str, data: bytes) -> None:
        p = self._p(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def read_bytes(self, path: str) -> bytes:
        return self._p(path).read_bytes()

    def list(self, prefix: str) -> list[str]:
        base = self._p(prefix)
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())

    def move(self, src: str, dst: str) -> None:
        d = self._p(dst)
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self._p(src), d)

    def exists(self, path: str) -> bool:
        return self._p(path).exists()

    def uri(self, path: str) -> str:
        return str(self._p(path))


class GcsLake:
    def __init__(self, bucket: str, credentials=None, project: str | None = None) -> None:
        from google.cloud import storage

        self._client = storage.Client(project=project, credentials=credentials)
        self._bucket = self._client.bucket(bucket)
        self.bucket_name = bucket

    def write_bytes(self, path: str, data: bytes) -> None:
        self._bucket.blob(path).upload_from_string(data)

    def read_bytes(self, path: str) -> bytes:
        return self._bucket.blob(path).download_as_bytes()

    def list(self, prefix: str) -> list[str]:
        return sorted(
            b.name
            for b in self._client.list_blobs(self._bucket, prefix=prefix)
            if not b.name.endswith("/")
        )

    def move(self, src: str, dst: str) -> None:
        self._bucket.rename_blob(self._bucket.blob(src), dst)  # copy + delete

    def exists(self, path: str) -> bool:
        return self._bucket.blob(path).exists()

    def uri(self, path: str) -> str:
        return f"gs://{self.bucket_name}/{path}"
