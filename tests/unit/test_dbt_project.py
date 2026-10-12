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
    assert len(models) == 42 and len(snapshots) == 3
    assert len(tests) >= 110

    # every Silver model (except the full-rebuild SLA table) is an incremental MERGE
    for m in models:
        if "silver" in m.tags and m.name != "service_sla_targets":
            assert m.config.materialized == "incremental", m.name
            assert m.config.unique_key, m.name

    # Gold: every fact is partitioned and clustered; every dimension has a surrogate key test
    for m in models:
        if m.name.startswith("fct_"):
            assert m.config.get("partition_by") and m.config.get("cluster_by"), m.name
