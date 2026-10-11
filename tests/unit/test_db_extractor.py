from datetime import UTC, datetime

import pytest

from ingestion.extractors.db_extractor import (
    PARENT_WM_COL,
    ObjectSpec,
    _naive_utc,
    build_query,
    load_catalog,
)

WM = datetime(2026, 10, 1, 12, 0)


def spec(**kw):
    base = dict(
        system="oracle",
        schema="billing",
        name="invoices",
        primary_key=("invoice_id",),
        mode="incremental",
        watermark_column="updated_at",
    )
    base.update(kw)
    return ObjectSpec(**base)


def test_full_ignores_watermark():
    sql, params = build_query(spec(mode="full"), WM)
    assert sql == "SELECT * FROM billing.invoices" and params == {}


def test_incremental_first_run_reads_everything():
    sql, params = build_query(spec(), None)
    assert "WHERE" not in sql and params == {}


def test_incremental_uses_bind_parameter():
    sql, params = build_query(spec(), WM)
    assert sql.endswith("WHERE updated_at > :wm")  # bind variable, never string-formatted
    assert params == {"wm": WM}


def test_child_filters_on_parent_change():
    s = spec(name="invoice_lines", mode="child", parent="invoices", parent_key="invoice_id")
    sql, params = build_query(s, WM)
    assert "JOIN billing.invoices p ON p.invoice_id = c.invoice_id" in sql
    assert f"p.updated_at AS {PARENT_WM_COL}" in sql
    assert sql.endswith("WHERE p.updated_at > :wm")


def test_unknown_mode_raises():
    with pytest.raises(ValueError):
        build_query(spec(mode="cdc"), WM)


def test_catalog_is_valid():
    cfg, specs = load_catalog()
    assert {s.system for s in specs} == {"postgres", "mssql", "oracle"}
    for s in specs:
        assert s.primary_key, s.name
        if s.mode in ("incremental", "child"):
            assert s.watermark_column, s.name
        if s.mode == "child":
            assert s.parent and s.parent_key, s.name
    assert cfg["lookback_minutes"] >= 0


def test_watermark_bound_as_naive_utc():
    aware = datetime(2026, 10, 1, 13, 0, tzinfo=UTC)
    assert _naive_utc(aware) == datetime(2026, 10, 1, 13, 0)
    assert _naive_utc(None) is None
