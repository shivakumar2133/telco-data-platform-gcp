"""Extract tables from Oracle / SQL Server / PostgreSQL into Bronze.

For each object in sources.yml:
  1. build the query (full, incremental since watermark, or child-of-changed-parent)
  2. count the rows the source says match         -> source_row_count
  3. read them, convert with the source's own column types (schema contract)
  4. write Parquet to raw/<system>/<object>/dt=.../run_id=.../
  5. load into bronze.<system>__<object> and compare row counts
  6. only then move the watermark forward

If anything fails, the watermark is NOT moved, so the next run re-reads the
same rows (at-least-once delivery; duplicates are removed in Silver).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pyarrow as pa
import yaml
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from ingestion.common.context import RunContext
from ingestion.common.lake import raw_prefix, write_parquet
from ingestion.common.log import get_logger
from ingestion.common.metadata import AuditRecord, frame_checksum
from ingestion.common.schema import add_metadata, arrow_type_for, to_arrow
from ingestion.common.secrets import get_secret

log = get_logger(__name__)
CATALOG = Path(__file__).resolve().parents[1] / "sources.yml"
CHUNK_ROWS = 100_000
PARENT_WM_COL = "x_parent_wm"


@dataclass(frozen=True)
class ObjectSpec:
    system: str
    schema: str
    name: str
    primary_key: tuple[str, ...]
    mode: str  # full | incremental | child
    watermark_column: str | None = None
    parent: str | None = None
    parent_key: str | None = None

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"

    @property
    def bronze_table(self) -> str:
        return f"{self.system}__{self.name}"


def load_catalog(path: Path = CATALOG) -> tuple[dict, list[ObjectSpec]]:
    cfg = yaml.safe_load(path.read_text())
    specs = []
    for system in ("postgres", "mssql", "oracle"):
        sys_cfg = cfg[system]
        for o in sys_cfg["objects"]:
            specs.append(
                ObjectSpec(
                    system=system,
                    schema=sys_cfg["schema"],
                    name=o["name"],
                    primary_key=tuple(o["primary_key"]),
                    mode=o["mode"],
                    watermark_column=o.get("watermark_column"),
                    parent=o.get("parent"),
                    parent_key=o.get("parent_key"),
                )
            )
    return cfg, specs


def build_query(spec: ObjectSpec, watermark: datetime | None) -> tuple[str, dict]:
    """Return (SQL, bind params). Watermark=None means read everything."""
    if spec.mode == "full":
        return f"SELECT * FROM {spec.qualified}", {}

    if spec.mode == "incremental":
        sql = f"SELECT * FROM {spec.qualified}"
        if watermark is None:
            return sql, {}
        return f"{sql} WHERE {spec.watermark_column} > :wm", {"wm": watermark}

    if spec.mode == "child":
        parent = f"{spec.schema}.{spec.parent}"
        sql = (
            f"SELECT c.*, p.{spec.watermark_column} AS {PARENT_WM_COL} "
            f"FROM {spec.qualified} c JOIN {parent} p ON p.{spec.parent_key} = c.{spec.parent_key}"
        )
        if watermark is None:
            return sql, {}
        return f"{sql} WHERE p.{spec.watermark_column} > :wm", {"wm": watermark}

    raise ValueError(f"Unknown mode {spec.mode!r} for {spec.qualified}")


def engine_for(system: str, cfg: dict, sa_email: str) -> Engine:
    from sources.load_sources import mssql_url, oracle_url, pg_url

    password = get_secret(f"{system}-etl-reader-password", sa_email=sa_email)
    if system == "postgres":
        url = pg_url("etl_reader", password, cfg["postgres"]["database"])
    elif system == "mssql":
        url = mssql_url("etl_reader", password, cfg["mssql"]["database"])
    else:
        url = oracle_url("etl_reader", password)
    return create_engine(url, pool_pre_ping=True)


def source_schema(engine: Engine, spec: ObjectSpec) -> pa.Schema:
    cols = inspect(engine).get_columns(spec.name, schema=spec.schema)
    return pa.schema([pa.field(c["name"].lower(), arrow_type_for(c["type"])) for c in cols])


def _naive_utc(ts: datetime | None) -> datetime | None:
    """DB columns are 'timestamp without time zone' holding UTC; bind naive values."""
    if ts is None:
        return None
    return ts.astimezone(UTC).replace(tzinfo=None) if ts.tzinfo else ts


def extract_object(
    ctx: RunContext,
    engine: Engine,
    spec: ObjectSpec,
    watermarks: dict,
    lookback_minutes: int = 0,
    force_full: bool = False,
) -> AuditRecord:
    current_wm = (
        None if (force_full or spec.mode == "full") else watermarks.get((spec.system, spec.name))
    )
    load_type = "FULL" if current_wm is None else "INCREMENTAL"
    rec = AuditRecord(ctx.run_id, spec.system, spec.name, load_type, watermark_from=current_wm)

    try:
        query_wm = _naive_utc(current_wm)
        if query_wm is not None and lookback_minutes:
            query_wm -= timedelta(minutes=lookback_minutes)
        sql, params = build_query(spec, query_wm)
        schema = source_schema(engine, spec)

        with engine.connect() as conn:
            rec.source_row_count = int(
                conn.execute(text(f"SELECT COUNT(*) FROM ({sql}) q"), params).scalar_one()
            )
            frames = list(pd.read_sql(text(sql), conn, params=params, chunksize=CHUNK_ROWS))

        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        df.columns = [c.lower() for c in df.columns]

        new_wm = None
        wm_col = PARENT_WM_COL if spec.mode == "child" else spec.watermark_column
        if spec.mode != "full" and not df.empty:
            new_wm = pd.Timestamp(pd.to_datetime(df[wm_col]).max())
            new_wm = (
                new_wm.tz_localize("UTC") if new_wm.tzinfo is None else new_wm
            ).to_pydatetime()
        if spec.mode == "child" and PARENT_WM_COL in df.columns:
            df = df.drop(columns=[PARENT_WM_COL])

        rec.source_checksum = frame_checksum(df)
        if df.empty:
            rec.loaded_row_count = 0
            log.info(
                "no new rows", extra={"fields": {"object": spec.qualified, "run_id": ctx.run_id}}
            )
            return rec.finish("SUCCESS")

        table = add_metadata(
            to_arrow(df, schema),
            {
                "_run_id": ctx.run_id,
                "_source_system": spec.system,
                "_source_object": spec.name,
                "_extract_mode": load_type,
            },
            ctx.started_at,
        )
        prefix = raw_prefix(spec.system, spec.name, ctx.started_at, ctx.run_id)
        write_parquet(ctx.lake, f"{prefix}/part-00000.parquet", table)
        rec.gcs_uri = ctx.lake.uri(f"{prefix}/*.parquet")

        rec.loaded_row_count = ctx.loader.load(spec.bronze_table, rec.gcs_uri)
        if not (rec.source_row_count == len(df) == rec.loaded_row_count):
            return rec.finish(
                "FAILED",
                f"count mismatch: source={rec.source_row_count} extracted={len(df)} "
                f"loaded={rec.loaded_row_count}",
            )

        if new_wm is not None:
            ctx.meta.set_watermark(spec.system, spec.name, spec.watermark_column, new_wm)
            rec.watermark_to = new_wm
        log.info(
            "extracted",
            extra={
                "fields": {
                    "object": spec.qualified,
                    "mode": load_type,
                    "rows": len(df),
                    "run_id": ctx.run_id,
                }
            },
        )
        return rec.finish("SUCCESS")
    except Exception as exc:  # noqa: BLE001 - record any failure in the audit trail
        log.exception("extract failed", extra={"fields": {"object": spec.qualified}})
        return rec.finish("FAILED", f"{type(exc).__name__}: {exc}")


def run_db(
    ctx: RunContext, systems: list[str], only: str | None = None, force_full: bool = False
) -> list[AuditRecord]:
    cfg, specs = load_catalog()
    watermarks = ctx.meta.get_watermarks()  # one read per run
    results: list[AuditRecord] = []
    for system in systems:
        todo = [s for s in specs if s.system == system and (only is None or s.name == only)]
        if not todo:
            continue
        try:
            engine = engine_for(system, cfg, ctx.ingest_sa)
        except Exception as exc:  # noqa: BLE001
            for spec in todo:
                rec = AuditRecord(ctx.run_id, system, spec.name, "FULL")
                results.append(rec.finish("FAILED", f"connection setup: {exc}"))
            continue
        for spec in todo:
            rec = extract_object(
                ctx, engine, spec, watermarks, cfg.get("lookback_minutes", 0), force_full
            )
            ctx.meta.write_audit(rec)
            results.append(rec)
        engine.dispose()
    return results
