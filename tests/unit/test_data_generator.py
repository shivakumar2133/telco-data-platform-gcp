"""Generator tests: run a small dataset once, then check structure and defects."""

import json

import pandas as pd
import pytest

from data_generator.config import GenConfig
from data_generator.generate import generate

CFG = GenConfig(scale=0.05, cdr_days=4)


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    d = tmp_path_factory.mktemp("gen")
    generate(CFG, d)
    return d


@pytest.fixture(scope="module")
def manifest(out):
    return json.loads((out / "defects_manifest.json").read_text())


def test_all_outputs_exist(out):
    for rel in [
        "db/mssql/customers.csv",
        "db/mssql/products.csv",
        "db/mssql/subscriptions.csv",
        "db/oracle/billing_accounts.csv",
        "db/oracle/invoices.csv",
        "db/oracle/invoice_lines.csv",
        "db/oracle/payments.csv",
        "db/postgres/sites.csv",
        "db/postgres/cells.csv",
        "db/postgres/devices.csv",
        "files/sla/sla_targets.xlsx",
        "api/tickets.json",
        "generation_summary.json",
    ]:
        assert (out / rel).exists(), rel
    assert len(list((out / "files/cdr").glob("cdr_*.csv"))) == CFG.cdr_days
    assert len(list((out / "files/alarms").glob("alarms_*.json"))) == CFG.cdr_days


def test_primary_keys_unique(out):
    for rel, key in [
        ("db/mssql/customers.csv", "customer_id"),
        ("db/mssql/subscriptions.csv", "subscription_id"),
        ("db/oracle/invoices.csv", "invoice_id"),
        ("db/oracle/invoice_lines.csv", "line_id"),
        ("db/postgres/devices.csv", "device_id"),
    ]:
        assert pd.read_csv(out / rel)[key].is_unique, rel


def test_duplicate_customers_share_email_with_original(out, manifest):
    c = pd.read_csv(out / "db/mssql/customers.csv").set_index("customer_id")
    entry = manifest["crm_duplicate_customer"]
    for dup, orig in zip(entry["ids"], entry["original_ids"], strict=True):
        if pd.notna(c.loc[orig, "email"]):
            assert c.loc[dup, "email"] == c.loc[orig, "email"]


def test_cdr_duplicates_match_manifest(out, manifest):
    cdr = pd.concat(pd.read_csv(p) for p in (out / "files/cdr").glob("*.csv"))
    dup_ids = cdr.loc[cdr["cdr_id"].duplicated(), "cdr_id"]
    assert len(dup_ids) == manifest["cdr_duplicate"]["count"]


def test_revenue_leakage_is_explained(out, manifest):
    """Deduplicated CDR charges - billed usage = injected leakage + orphan subscriptions."""
    cdr = pd.concat(pd.read_csv(p) for p in (out / "files/cdr").glob("*.csv"))
    cdr = cdr.drop_duplicates("cdr_id")
    subs = pd.read_csv(out / "db/mssql/subscriptions.csv", dtype={"msisdn": str})
    cdr["msisdn_a"] = cdr["msisdn_a"].astype(str)
    rated = cdr.merge(subs[["msisdn", "subscription_id"]], left_on="msisdn_a", right_on="msisdn")

    inv = pd.read_csv(out / "db/oracle/invoices.csv")
    lines = pd.read_csv(out / "db/oracle/invoice_lines.csv")
    cdr_month = inv.loc[inv["period_start"] == str(CFG.cdr_start), "invoice_id"]
    billed = lines[(lines["charge_type"] == "USAGE") & lines["invoice_id"].isin(cdr_month)]

    orphans = set(manifest["crm_orphan_subscription"]["ids"])
    unbilled_orphans = rated.loc[rated["subscription_id"].isin(orphans), "charge_amount"].sum()
    gap = rated["charge_amount"].sum() - billed["amount"].sum()
    expected = manifest["billing_revenue_leakage"]["missing_amount"] + unbilled_orphans
    assert gap == pytest.approx(expected, abs=0.05)


def test_header_line_mismatch_matches_manifest(out, manifest):
    inv = pd.read_csv(out / "db/oracle/invoices.csv").set_index("invoice_id")
    lines = pd.read_csv(out / "db/oracle/invoice_lines.csv")
    line_sum = lines.groupby("invoice_id")["amount"].sum()
    diff = (inv["total_amount"] - line_sum).abs()
    mismatched = set(diff[diff > 0.005].index)
    assert mismatched == set(manifest["billing_header_line_mismatch"]["ids"])


def test_alarm_export_is_nested_with_header(out):
    f = sorted((out / "files/alarms").glob("*.json"))[0]
    export = json.loads(f.read_text())
    assert {"export_id", "record_count", "alarms"} <= export.keys()
    assert "device_id" in export["alarms"][0]["device"]


def test_generation_is_reproducible(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    small = GenConfig(scale=0.01, cdr_days=1)
    generate(small, a)
    generate(small, b)
    for rel in ["db/mssql/customers.csv", "db/oracle/invoices.csv", "api/tickets.json"]:
        assert (a / rel).read_bytes() == (b / rel).read_bytes(), rel
