from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from ingestion.common.metadata import LocalMetaStore
from ingestion.extractors.db_extractor import ObjectSpec
from quality.capture_source_totals import capture_system, totals_query


def spec(name):
    return ObjectSpec("oracle", "billing", name, (f"{name}_id",), "full")


def test_totals_query_sums_money_only_where_configured():
    assert totals_query(spec("invoices"), "total_amount") == (
        "SELECT COUNT(*) AS row_count, SUM(total_amount) AS sum_amount FROM billing.invoices"
    )
    assert "NULL AS sum_amount" in totals_query(spec("billing_accounts"), None)


@pytest.fixture
def engine():
    # SQLite with an attached database named "billing" stands in for the Oracle schema
    eng = create_engine("sqlite://", poolclass=StaticPool)
    with eng.begin() as c:
        c.execute(text("ATTACH DATABASE ':memory:' AS billing"))
        c.execute(text("CREATE TABLE billing.invoices (invoice_id TEXT, total_amount NUMERIC)"))
        c.execute(text("INSERT INTO billing.invoices VALUES ('I1', 10.50), ('I2', 4.25)"))
        c.execute(text("CREATE TABLE billing.billing_accounts (account_id TEXT)"))
        c.execute(text("INSERT INTO billing.billing_accounts VALUES ('A1')"))
    return eng


def test_capture_counts_and_sums(engine, tmp_path):
    rows = capture_system(engine, [spec("invoices"), spec("billing_accounts")], "run-1")
    by_obj = {r["object_name"]: r for r in rows}
    assert by_obj["invoices"]["row_count"] == 2
    assert Decimal(by_obj["invoices"]["sum_amount"]) == Decimal("14.75")
    assert by_obj["invoices"]["amount_column"] == "total_amount"
    assert by_obj["billing_accounts"]["sum_amount"] is None

    meta = LocalMetaStore(tmp_path)
    meta.append_rows("source_control_totals", rows)
    assert [r["object_name"] for r in meta.rows("source_control_totals")] == [
        "invoices",
        "billing_accounts",
    ]
