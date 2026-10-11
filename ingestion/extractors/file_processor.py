"""Process files dropped in landing/ into Bronze.

For every file in landing/<kind>/:
  - already processed (same MD5 seen before)? -> archive, status SKIPPED
  - validate the FILE-level contract (header, control totals, readable)
      fails  -> move to quarantine/, status REJECTED (whole file, not partial)
      passes -> Parquet in raw/, load Bronze, move original to archive/

Row-level problems (negative durations, unknown cells ...) are NOT rejected here.
Bronze keeps everything as received; Silver checks rows (Phase 7).
"""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ingestion.common.context import RunContext
from ingestion.common.lake import Lake, raw_prefix, write_parquet
from ingestion.common.log import get_logger
from ingestion.common.metadata import AuditRecord, file_md5
from ingestion.common.schema import add_metadata, all_string_schema, to_arrow

log = get_logger(__name__)
SYSTEM = "files"

CDR_COLUMNS = [
    "cdr_id",
    "msisdn_a",
    "msisdn_b",
    "call_type",
    "start_time",
    "duration_sec",
    "data_volume_mb",
    "cell_id",
    "call_result",
    "charge_amount",
]
SLA_HEADER_MARKER = "SLA Tier"


class FileRejected(ValueError):
    """The file breaks its contract and must not be loaded at all."""


def _snake(name: str) -> str:
    out = "".join(ch.lower() if ch.isalnum() else "_" for ch in str(name).strip())
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def parse_cdr(data: bytes) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.BytesIO(data), dtype=str, keep_default_na=False, na_values=[""])
    except Exception as exc:  # noqa: BLE001
        raise FileRejected(f"unreadable CSV: {exc}") from exc
    if list(df.columns) != CDR_COLUMNS:
        raise FileRejected(f"header mismatch: expected {CDR_COLUMNS}, got {list(df.columns)}")
    if df.empty:
        raise FileRejected("file has a header but no rows")
    return df


def parse_alarms(data: bytes) -> pd.DataFrame:
    try:
        doc = json.loads(data)
    except json.JSONDecodeError as exc:
        raise FileRejected(f"invalid JSON: {exc}") from exc
    for key in ("export_id", "record_count", "alarms"):
        if key not in doc:
            raise FileRejected(f"missing header field '{key}'")
    if int(doc["record_count"]) != len(doc["alarms"]):
        raise FileRejected(
            f"control total mismatch: header record_count={doc['record_count']}, "
            f"alarms in file={len(doc['alarms'])}"
        )
    df = pd.json_normalize(doc["alarms"], sep="__")  # device.device_id -> device__device_id
    header = {
        "export_id": "export_id",
        "exported_at": "exported_at",
        "export_source_system": "source_system",
        "export_record_count": "record_count",
    }
    for column, key in header.items():
        df[column] = doc.get(key)
    return df


def parse_sla(data: bytes) -> pd.DataFrame:
    try:
        raw = pd.read_excel(io.BytesIO(data), sheet_name="SLA Targets", header=None, dtype=str)
    except Exception as exc:  # noqa: BLE001
        raise FileRejected(f"unreadable workbook or missing 'SLA Targets' sheet: {exc}") from exc
    header_rows = raw.index[raw[0].astype(str).str.strip() == SLA_HEADER_MARKER].tolist()
    if not header_rows:
        raise FileRejected(f"no header row starting with '{SLA_HEADER_MARKER}'")
    h = header_rows[0]
    df = raw.iloc[h + 1 :].copy()
    df.columns = [_snake(c) for c in raw.iloc[h]]
    df = df.dropna(how="all").reset_index(drop=True)
    if df.empty:
        raise FileRejected("no data rows under the header")
    return df


KINDS = {  # landing folder -> (parser, bronze object name)
    "cdr": (parse_cdr, "cdr"),
    "alarms": (parse_alarms, "alarms"),
    "sla": (parse_sla, "sla_targets"),
}


def process_landing(ctx: RunContext) -> list[AuditRecord]:
    seen = ctx.meta.processed_file_checksums()
    results: list[AuditRecord] = []
    for kind, (parser, obj) in KINDS.items():
        for path in ctx.lake.list(f"landing/{kind}/"):
            name = path.rsplit("/", 1)[-1]
            rec = AuditRecord(ctx.run_id, SYSTEM, f"{obj}/{name}", "FILE")
            try:
                data = ctx.lake.read_bytes(path)
                rec.source_checksum = file_md5(data)
                if rec.source_checksum in seen:
                    ctx.lake.move(path, f"archive/{kind}/duplicates/{ctx.run_id}_{name}")
                    rec.finish("SKIPPED", "identical file already loaded")
                else:
                    try:
                        df = parser(data)
                    except FileRejected as exc:
                        ctx.lake.move(path, f"quarantine/{kind}/{name}")
                        rec.finish("REJECTED", str(exc))
                        log.warning(
                            "file rejected", extra={"fields": {"file": name, "why": str(exc)}}
                        )
                    else:
                        rec.source_row_count = len(df)
                        table = add_metadata(
                            to_arrow(df, all_string_schema(df.columns)),
                            {
                                "_run_id": ctx.run_id,
                                "_source_system": SYSTEM,
                                "_source_object": obj,
                                "_source_file": name,
                                "_source_file_md5": rec.source_checksum,
                            },
                            ctx.started_at,
                        )
                        stem = name.rsplit(".", 1)[0]
                        out = (
                            f"{raw_prefix(SYSTEM, obj, ctx.started_at, ctx.run_id)}/{stem}.parquet"
                        )
                        write_parquet(ctx.lake, out, table)
                        rec.gcs_uri = ctx.lake.uri(out)
                        rec.loaded_row_count = ctx.loader.load(f"{SYSTEM}__{obj}", rec.gcs_uri)
                        if rec.loaded_row_count != rec.source_row_count:
                            rec.finish(
                                "FAILED",
                                f"count mismatch: file={rec.source_row_count} "
                                f"loaded={rec.loaded_row_count}",
                            )
                        else:
                            ctx.lake.move(path, f"archive/{kind}/{name}")
                            seen.add(rec.source_checksum)
                            rec.finish("SUCCESS")
            except Exception as exc:  # noqa: BLE001 - leave the file in landing for a retry
                log.exception("file processing failed", extra={"fields": {"file": name}})
                rec.finish("FAILED", f"{type(exc).__name__}: {exc}")
            ctx.meta.write_audit(rec)
            results.append(rec)
    return results


def drop_files(
    lake: Lake, files_dir: Path, date_from: str | None = None, date_to: str | None = None
) -> int:
    """Simulate source systems delivering files: copy generated files into landing/."""
    lo = (date_from or "00000000").replace("-", "")
    hi = (date_to or "99999999").replace("-", "")
    n = 0
    for kind, pattern in (("cdr", "cdr_*.csv"), ("alarms", "alarms_*.json")):
        for f in sorted((files_dir / kind).glob(pattern)):
            day = f.stem.split("_")[-1]
            if lo <= day <= hi:
                lake.write_bytes(f"landing/{kind}/{f.name}", f.read_bytes())
                n += 1
    sla = files_dir / "sla" / "sla_targets.xlsx"
    if sla.exists():
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        lake.write_bytes(f"landing/sla/sla_targets_{stamp}.xlsx", sla.read_bytes())
        n += 1
    return n
