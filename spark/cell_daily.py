"""Network quality per cell per day - the same result as dbt's mart_cell_daily,
computed with PySpark straight from Bronze. Phase 13: when is Spark the right tool?

Logic (mirrors stg_files__cdrs -> usage_cdrs -> fct_calls -> mart_cell_daily):
  1. type the all-STRING CDRs (bad values become NULL, like SAFE_CAST)
  2. one row per cdr_id (duplicate deliveries collapse, first ingested wins)
  3. current version of every cell and site (latest updated_at, then _ingested_at)
  4. left join calls -> cells -> sites; unknown cells keep their calls (region 'Unknown')
  5. aggregate per call_date x cell

    # locally, from the Parquet lake written by `make ingest-local` (needs Java 17)
    python -m spark.cell_daily --local local_run --output local_run/spark/cell_daily

    # on Dataproc Serverless, reading/writing BigQuery (make spark-submit)
    cell_daily.py --project <id> --output <id>.scratch.spark_cell_daily

Oracle analogy: the same aggregate you'd write in PL/SQL with BULK COLLECT, moved to a
distributed engine - worth it only when the data or the logic outgrows SQL.
"""

from __future__ import annotations

import argparse
import os
import sys
import time

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F
from pyspark.sql.types import DecimalType

NUMERIC = DecimalType(38, 9)  # BigQuery NUMERIC


# ------------------------------------------------------------------ pure transformations
def latest(df: DataFrame, key: str, *order: F.Column) -> DataFrame:
    """One row per key: the first row by `order` (QUALIFY ROW_NUMBER() = 1 in SQL)."""
    w = Window.partitionBy(key).orderBy(*order)
    return df.withColumn("_rn", F.row_number().over(w)).where("_rn = 1").drop("_rn")


def type_cdrs(raw: DataFrame) -> DataFrame:
    """Bronze CDRs are all STRING. Invalid values become NULL instead of failing the job."""
    start = F.col("start_time").cast("timestamp")
    return raw.select(
        "cdr_id",
        F.upper("call_type").alias("call_type"),
        start.alias("start_time"),
        F.to_date(start).alias("call_date"),
        F.col("duration_sec").cast("int").alias("duration_sec"),
        F.col("data_volume_mb").cast(NUMERIC).alias("data_volume_mb"),
        "cell_id",
        F.upper("call_result").alias("call_result"),
        "_ingested_at",
    )


def dedupe_cdrs(cdrs: DataFrame) -> DataFrame:
    return latest(cdrs, "cdr_id", F.col("_ingested_at").asc())


def current_cells(cells_raw: DataFrame, sites_raw: DataFrame) -> DataFrame:
    order = (F.col("updated_at").desc(), F.col("_ingested_at").desc())
    cells = latest(cells_raw, "cell_id", *order).select("cell_id", "site_id", "technology")
    sites = latest(sites_raw, "site_id", *order).select("site_id", "region")
    return cells.join(sites, "site_id", "left").select("cell_id", "technology", "region")


def cell_daily(cdrs: DataFrame, cells: DataFrame) -> DataFrame:
    calls = cdrs.join(F.broadcast(cells), "cell_id", "left")  # small dimension: broadcast join
    voice_secs = F.when(
        (F.col("call_type") == "VOICE") & (F.col("duration_sec") > 0), F.col("duration_sec")
    )
    return calls.groupBy("call_date", "cell_id").agg(
        F.first(F.col("region").isNotNull()).alias("is_known_cell"),
        F.coalesce(F.first("region"), F.lit("Unknown")).alias("region"),
        F.coalesce(F.first("technology"), F.lit("UNKNOWN")).alias("technology"),
        F.count(F.lit(1)).alias("call_attempts"),
        F.sum(F.when(F.col("call_type") == "VOICE", 1).otherwise(0)).alias("voice_calls"),
        F.sum(F.when(F.col("call_result") == "DROPPED", 1).otherwise(0)).alias("dropped_calls"),
        F.sum(F.when(F.col("call_result") == "FAILED", 1).otherwise(0)).alias("failed_calls"),
        F.round(F.sum(voice_secs) / 60, 1).alias("voice_minutes"),
        F.round(F.sum("data_volume_mb") / 1024, 3).alias("data_gb"),
    )


def build(cdr_raw: DataFrame, cells_raw: DataFrame, sites_raw: DataFrame) -> DataFrame:
    return cell_daily(dedupe_cdrs(type_cdrs(cdr_raw)), current_cells(cells_raw, sites_raw))


# ------------------------------------------------------------------ I/O
def read_local(spark: SparkSession, root: str) -> tuple[DataFrame, DataFrame, DataFrame]:
    raw = f"{root.rstrip('/')}/lake/raw"
    return tuple(  # type: ignore[return-value]
        spark.read.option("basePath", f"{raw}/{p}").parquet(f"{raw}/{p}")
        for p in ("files/cdr", "postgres/cells", "postgres/sites")
    )


def read_bigquery(spark: SparkSession, project: str) -> tuple[DataFrame, DataFrame, DataFrame]:
    """BigQuery Storage Read API: only the columns used are read (column pruning)."""

    def table(name: str, cols: list[str]) -> DataFrame:
        return spark.read.format("bigquery").load(f"{project}.bronze.{name}").select(*cols)

    versions = ["updated_at", "_ingested_at"]
    return (
        table("files__cdr", ["cdr_id", "call_type", "start_time", "duration_sec",
                             "data_volume_mb", "cell_id", "call_result", "_ingested_at"]),
        table("postgres__cells", ["cell_id", "site_id", "technology", *versions]),
        table("postgres__sites", ["site_id", "region", *versions]),
    )  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--local", help="folder with lake/raw (from make ingest-local)")
    src.add_argument("--project", help="GCP project: read bronze.* from BigQuery")
    p.add_argument("--output", required=True, help="local folder, or project.dataset.table")
    args = p.parse_args(argv)

    builder = SparkSession.builder.appName("telco-cell-daily").config(
        "spark.sql.session.timeZone", "UTC"
    )
    if args.local:
        os.environ.setdefault("PYSPARK_PYTHON", sys.executable)  # workers use this venv
        builder = builder.master("local[*]").config("spark.ui.enabled", "false")
    spark = builder.getOrCreate()

    t0 = time.time()
    sources = read_local(spark, args.local) if args.local else read_bigquery(spark, args.project)
    result = build(*sources)

    if args.local:
        result.write.mode("overwrite").partitionBy("call_date").parquet(args.output)
    else:
        (
            result.write.format("bigquery")
            .option("writeMethod", "direct")  # Storage Write API: no temp bucket needed
            .option("partitionField", "call_date")
            .option("partitionType", "DAY")
            .option("clusteredFields", "region,cell_id")
            .mode("overwrite")
            .save(args.output)
        )

    out = spark.read.parquet(args.output) if args.local else result
    totals = out.agg(
        F.count(F.lit(1)).alias("rows"),
        F.sum("call_attempts").alias("call_attempts"),
        F.sum("dropped_calls").alias("dropped_calls"),
    ).first()
    print(
        f"cell_daily: {totals['rows']:,} rows, {totals['call_attempts']:,} call attempts, "
        f"{totals['dropped_calls']:,} dropped -> {args.output} in {time.time() - t0:.0f}s"
    )
    spark.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
