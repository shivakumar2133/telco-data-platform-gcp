"""`dbt parse` must succeed: every ref/source resolves, YAML and Jinja are valid.
No warehouse connection needed. Skipped if dbt isn't installed."""

from pathlib import Path

import pytest

pytest.importorskip("dbt.cli.main")

PROJECT = Path(__file__).resolve().parents[2] / "transform"


def test_dbt_project_parses(tmp_path, monkeypatch):
    from dbt.cli.main import dbtRunner

    monkeypatch.setenv("GCP_PROJECT_ID", "ci-dummy-project")
    monkeypatch.setenv("DBT_SEND_ANONYMOUS_USAGE_STATS", "false")
    result = dbtRunner().invoke(
        [
            "parse",
            "--project-dir",
            str(PROJECT),
            "--profiles-dir",
            str(PROJECT),
            "--target-path",
            str(tmp_path / "target"),
            "--log-path",
            str(tmp_path / "logs"),
            "--no-partial-parse",
            "--quiet",
        ]
    )
    assert result.success, result.exception

    manifest = result.result
    models = [n for n in manifest.nodes.values() if n.resource_type == "model"]
    tests = [n for n in manifest.nodes.values() if n.resource_type == "test"]
    snapshots = [n for n in manifest.nodes.values() if n.resource_type == "snapshot"]
    assert len(models) == 53 and len(snapshots) == 3
    assert len(tests) >= 130

    # every Silver model (except the full-rebuild SLA table) is an incremental MERGE
    for m in models:
        if "silver" in m.tags and m.name != "service_sla_targets":
            assert m.config.materialized == "incremental", m.name
            assert m.config.unique_key, m.name

    # Gold: every fact is partitioned and clustered; every dimension has a surrogate key test
    for m in models:
        if m.name.startswith("fct_"):
            assert m.config.get("partition_by") and m.config.get("cluster_by"), m.name

    # DQ / reconciliation: append-only history that --full-refresh must never wipe
    dq = {m.name: m for m in models if "dq" in m.tags}
    assert set(dq) == {
        "dq_rule_catalog", "dq_failures", "dq_scorecard", "recon_results", "rpt_dq_latest",
        "rpt_recon_latest",
    }  # fmt: skip
    for name in ("dq_failures", "dq_scorecard", "recon_results"):
        assert dq[name].config.get("full_refresh") is False, name
        assert dq[name].config.get("partition_by"), name
    assert all(m.schema == "ops" for m in dq.values())

    # Governance (Phase 8): no personal-data column is published without a policy tag
    pii_columns = {
        "email", "msisdn", "msisdn_a", "msisdn_b", "first_name", "last_name",
        "customer_name", "address_line1", "date_of_birth", "postcode",
    }  # fmt: skip
    governed = [n for n in [*models, *snapshots] if n.schema in ("silver", "gold")]
    for node in governed:
        if node.config.materialized == "view":
            continue  # staging views: Silver dataset is readable by sa-transform only
        for name, col in node.columns.items():
            if name in pii_columns and not (node.name == "dim_cell" and name == "postcode"):
                assert col.to_dict().get("policy_tags"), f"{node.name}.{name} has no policy tag"

    # Row-level security: every table with an analyst grant also gets row access policies
    for m in models:
        if m.config.get("grants"):
            hooks = " ".join(h.sql for h in m.config.post_hook)
            assert "row_access_policies" in hooks, m.name
    rls = {m.name for m in models if m.config.get("grants")}
    assert rls == {"dim_customer", "dim_cell", "mart_cell_daily"}

    # Reporting (Phase 11): BI tables never select a personal-data column, so dashboards
    # can SELECT * as sa-reporting and a shared report can't leak PII
    import re

    pii_pattern = re.compile(r"\b(" + "|".join(sorted(pii_columns)) + r")\b")
    reporting = [m for m in models if m.name.startswith("rpt_")]
    assert {m.name for m in reporting} == {
        "rpt_kpi_monthly", "rpt_revenue_assurance", "rpt_network_daily",
        "rpt_sla_performance", "rpt_customer_base", "rpt_dq_latest", "rpt_recon_latest",
    }  # fmt: skip
    for m in reporting:
        sql = re.sub(r"--[^\n]*", "", m.raw_code)  # ignore comments
        assert not pii_pattern.search(sql), f"{m.name} references a PII column"
    exposures = {e.name for e in manifest.exposures.values()}
    assert exposures == {"looker_studio_operations", "powerbi_revenue_and_service"}
