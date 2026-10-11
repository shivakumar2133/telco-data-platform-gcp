"""Schema contract: turn source column types into an explicit Arrow/Parquet schema.

Why bother? If types are guessed from the data, a batch where a column happens
to be all NULL gets a 'null' type, and the next BigQuery append fails with
"field changed type". Reading the types from the source's own catalogue
(like querying ALL_TAB_COLUMNS in Oracle) gives the same schema every run.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pyarrow as pa
from sqlalchemy import types as sat

TS = pa.timestamp("us", tz="UTC")


def arrow_type_for(sql_type) -> pa.DataType:
    """Map a SQLAlchemy column type (from the inspector) to an Arrow type."""
    if isinstance(sql_type, sat.Float):
        return pa.float64()
    if isinstance(sql_type, sat.Numeric):  # also Oracle NUMBER, which subclasses Integer
        scale = getattr(sql_type, "scale", None)
        precision = getattr(sql_type, "precision", None)
        if scale:
            return pa.decimal128(min(precision or 38, 38), scale)
        return pa.int64()
    if isinstance(sql_type, sat.Integer):
        return pa.int64()
    if isinstance(sql_type, sat.Boolean):
        return pa.bool_()
    if isinstance(sql_type, sat.DateTime):  # before Date: Oracle DATE is a DateTime
        return TS
    if isinstance(sql_type, sat.Date):
        return pa.date32()
    return pa.string()


def _is_missing(v) -> bool:
    if v is None or v is pd.NaT:
        return True
    return isinstance(v, float) and math.isnan(v)


def _convert(values: pd.Series, typ: pa.DataType) -> pa.Array:
    vals = values.tolist()
    if pa.types.is_timestamp(typ):
        out = []
        for v in vals:
            if _is_missing(v):
                out.append(None)
                continue
            ts = pd.Timestamp(v)
            out.append(
                (
                    ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
                ).to_pydatetime()
            )
        return pa.array(out, type=typ)
    if pa.types.is_date32(typ):
        out = []
        for v in vals:
            if _is_missing(v):
                out.append(None)
            elif isinstance(v, datetime):
                out.append(v.date())
            elif isinstance(v, date):
                out.append(v)
            else:
                out.append(pd.Timestamp(v).date())
        return pa.array(out, type=typ)
    if pa.types.is_decimal(typ):
        q = Decimal(1).scaleb(-typ.scale)
        return pa.array(
            [None if _is_missing(v) else Decimal(str(v)).quantize(q) for v in vals], type=typ
        )
    if pa.types.is_integer(typ):
        return pa.array([None if _is_missing(v) else int(v) for v in vals], type=typ)
    if pa.types.is_floating(typ):
        return pa.array([None if _is_missing(v) else float(v) for v in vals], type=typ)
    if pa.types.is_boolean(typ):
        return pa.array([None if _is_missing(v) else bool(v) for v in vals], type=typ)
    return pa.array([None if _is_missing(v) else str(v) for v in vals], type=pa.string())


def to_arrow(df: pd.DataFrame, schema: pa.Schema) -> pa.Table:
    """Build a table with exactly `schema` (columns missing from df become NULL)."""
    arrays = []
    for field in schema:
        if field.name in df.columns:
            arrays.append(_convert(df[field.name], field.type))
        else:
            arrays.append(pa.nulls(len(df), type=field.type))
    return pa.Table.from_arrays(arrays, schema=schema)


def all_string_schema(columns) -> pa.Schema:
    """Files and API payloads land in Bronze as text: nothing is lost or mis-parsed.
    Silver does the typing (and reports what fails to cast)."""
    return pa.schema([pa.field(c, pa.string()) for c in columns])


def add_metadata(table: pa.Table, meta: dict[str, object], ingested_at: datetime) -> pa.Table:
    """Append audit columns (_run_id, _source_system, ... , _ingested_at)."""
    n = table.num_rows
    for name, value in meta.items():
        table = table.append_column(
            name, pa.array([None if value is None else str(value)] * n, type=pa.string())
        )
    return table.append_column("_ingested_at", pa.array([ingested_at] * n, type=TS))
