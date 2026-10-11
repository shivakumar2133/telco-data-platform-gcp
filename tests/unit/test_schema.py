from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from sqlalchemy import types as sat
from sqlalchemy.dialects import mssql, oracle, postgresql

from ingestion.common.schema import TS, add_metadata, arrow_type_for, to_arrow


def test_type_mapping_across_databases():
    cases = [
        (oracle.NUMBER(12, 2), pa.decimal128(12, 2)),
        (oracle.NUMBER(10, 0), pa.int64()),
        (oracle.DATE(), TS),  # Oracle DATE carries a time part
        (oracle.TIMESTAMP(), TS),
        (oracle.VARCHAR2(20), pa.string()),
        (mssql.DATETIME2(), TS),
        (mssql.DECIMAL(10, 2), pa.decimal128(10, 2)),
        (mssql.NVARCHAR(100), pa.string()),
        (mssql.INTEGER(), pa.int64()),
        (sat.DATE(), pa.date32()),
        (postgresql.NUMERIC(8, 5), pa.decimal128(8, 5)),
        (postgresql.SMALLINT(), pa.int64()),
        (postgresql.TIMESTAMP(), TS),
        (sat.Float(), pa.float64()),
    ]
    for sql_type, expected in cases:
        assert arrow_type_for(sql_type) == expected, sql_type


def test_all_null_column_keeps_declared_type():
    """The bug this module exists to prevent: an all-NULL batch must not become type 'null'."""
    schema = pa.schema([("id", pa.string()), ("end_date", pa.date32())])
    df = pd.DataFrame({"id": ["a", "b"], "end_date": [None, None]})
    t = to_arrow(df, schema)
    assert t.schema.field("end_date").type == pa.date32()
    assert t.column("end_date").null_count == 2


def test_conversions():
    schema = pa.schema(
        [("amt", pa.decimal128(12, 2)), ("n", pa.int64()), ("d", pa.date32()), ("ts", TS)]
    )
    df = pd.DataFrame(
        {
            "amt": [Decimal("30"), 12.5, None],
            "n": [1.0, None, 3],
            "d": [date(2026, 9, 1), datetime(2026, 9, 2, 0, 0), None],
            "ts": [datetime(2026, 9, 1, 10, 0), pd.NaT, pd.Timestamp("2026-09-02 11:00")],
        }
    )
    t = to_arrow(df, schema).to_pylist()
    assert t[0]["amt"] == Decimal("30.00") and t[1]["amt"] == Decimal("12.50")
    assert t[1]["n"] is None and t[2]["n"] == 3
    assert t[1]["d"] == date(2026, 9, 2)
    assert t[0]["ts"].tzinfo is not None and t[1]["ts"] is None


def test_metadata_columns_added():
    t = to_arrow(pd.DataFrame({"a": ["x"]}), pa.schema([("a", pa.string())]))
    t = add_metadata(t, {"_run_id": "r1"}, datetime(2026, 10, 1))
    assert t.column_names == ["a", "_run_id", "_ingested_at"]
