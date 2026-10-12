"""Spark transformations tested on tiny DataFrames (local Spark, no cloud).
Skipped where PySpark/Java aren't installed: make spark-test / CI 'Spark unit tests'."""

import os
import sys
from datetime import UTC, datetime

import pytest

pyspark = pytest.importorskip("pyspark")
from pyspark.sql import SparkSession  # noqa: E402

from spark.cell_daily import build, current_cells, dedupe_cdrs, type_cdrs  # noqa: E402

T1 = datetime(2026, 10, 1, 2, tzinfo=UTC)
T2 = datetime(2026, 10, 2, 2, tzinfo=UTC)


@pytest.fixture(scope="module")
def spark():
    os.environ.setdefault("PYSPARK_PYTHON", sys.executable)  # workers use this venv's Python
    s = (
        SparkSession.builder.master("local[1]")
        .config("spark.ui.enabled", "false")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "1")
        .getOrCreate()
    )
    yield s
    s.stop()


def cdr(cdr_id, cell="C1", call_type="voice", result="completed", dur="60", ts=T1):
    return (cdr_id, call_type, "2026-09-01 10:00:00", dur, "0.0", cell, result, ts)


CDR_COLS = ["cdr_id", "call_type", "start_time", "duration_sec", "data_volume_mb",
            "cell_id", "call_result", "_ingested_at"]  # fmt: skip


def frames(spark, cdrs):
    cdr_df = spark.createDataFrame(cdrs, CDR_COLS)
    cells = spark.createDataFrame(
        [("C1", "S1", "4G", T1, T1), ("C1", "S1", "5G", T2, T2)],  # C1 upgraded to 5G
        ["cell_id", "site_id", "technology", "updated_at", "_ingested_at"],
    )
    sites = spark.createDataFrame(
        [("S1", "North West", T1, T1)], ["site_id", "region", "updated_at", "_ingested_at"]
    )
    return cdr_df, cells, sites


def test_bad_values_become_null_not_errors(spark):
    df = spark.createDataFrame([cdr("A", dur="abc")], CDR_COLS)
    row = type_cdrs(df).first()
    assert row.duration_sec is None and row.call_type == "VOICE"
    assert str(row.call_date) == "2026-09-01"


def test_duplicate_deliveries_collapse(spark):
    df = spark.createDataFrame([cdr("A"), cdr("A", ts=T2), cdr("B")], CDR_COLS)
    assert dedupe_cdrs(type_cdrs(df)).count() == 2


def test_current_cell_version_wins(spark):
    _, cells, sites = frames(spark, [cdr("A")])
    row = current_cells(cells, sites).first()
    assert (row.technology, row.region) == ("5G", "North West")


def test_cell_daily_counts_and_unknown_cells(spark):
    rows = [
        cdr("A"),
        cdr("A", ts=T2),  # duplicate delivery: counted once
        cdr("B", result="dropped"),
        cdr("C", call_type="data", dur="0"),
        cdr("D", cell="NOPE", result="failed"),  # not in inventory: kept, region Unknown
    ]
    out = {r.cell_id: r for r in build(*frames(spark, rows)).collect()}
    c1 = out["C1"]
    assert (c1.call_attempts, c1.voice_calls, c1.dropped_calls) == (3, 2, 1)
    assert c1.voice_minutes == 2.0 and c1.is_known_cell and c1.technology == "5G"
    unknown = out["NOPE"]
    assert (unknown.region, unknown.failed_calls, unknown.is_known_cell) == ("Unknown", 1, False)
