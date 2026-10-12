"""DAG integrity tests. Skipped automatically where Airflow isn't installed
(your dev venv); run inside the Airflow image with:  make airflow-test
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("airflow")

DAGS_DIR = Path(__file__).resolve().parents[2] / "orchestration" / "dags"
EXPECTED = {"telco_ingest_daily", "telco_tickets_hourly", "telco_files_daily", "telco_transform"}


@pytest.fixture(scope="module")
def dagbag():
    # Airflow 3.3 moved DagBag; example DAGs are controlled by AIRFLOW__CORE__LOAD_EXAMPLES
    from airflow.dag_processing.dagbag import DagBag

    return DagBag(dag_folder=str(DAGS_DIR))


def test_no_import_errors(dagbag):
    assert dagbag.import_errors == {}, dagbag.import_errors


def test_expected_dags_present(dagbag):
    assert EXPECTED <= set(dagbag.dag_ids)


@pytest.mark.parametrize("dag_id", sorted(EXPECTED))
def test_dag_conventions(dagbag, dag_id):
    dag = dagbag.dags[dag_id]
    assert dag.catchup is False, "catchup must be explicit and off"
    assert dag.max_active_runs == 1, "runs share watermarks/landing: one at a time"
    assert "telco" in dag.tags
    assert dag.doc_md, "every DAG documents itself in the UI"
    for task in dag.tasks:
        assert task.on_failure_callback, f"{task.task_id} has no failure alert"
        assert task.execution_timeout is not None, f"{task.task_id} could hang forever"


def test_reconciliation_is_last_and_not_retried(dagbag):
    dag = dagbag.dags["telco_ingest_daily"]
    reconcile = dag.get_task("reconcile_bronze")
    assert reconcile.retries == 0
    assert {t.task_id for t in reconcile.upstream_list} == {"capture_source_totals"}
    capture = dag.get_task("capture_source_totals")
    assert {t.task_id for t in capture.upstream_list} == {
        "extract_databases.extract_postgres",
        "extract_databases.extract_mssql",
        "extract_databases.extract_oracle",
    }
    assert reconcile.outlets, "reconciliation should publish the bronze_ready asset"


def test_files_dag_delivers_the_logical_date(dagbag):
    task = dagbag.dags["telco_files_daily"].get_task("deliver_files")
    assert "{{ ds }}" in task.bash_command


def test_transform_runs_when_bronze_is_ready(dagbag):
    """Data-aware scheduling: dbt runs after ingestion publishes bronze_ready, not on a clock."""
    ingest = dagbag.dags["telco_ingest_daily"].get_task("reconcile_bronze")
    transform = dagbag.dags["telco_transform"]
    produced = {a.uri for a in ingest.outlets}
    assert "telco://bronze/ready" in produced
    assert type(transform.timetable).__name__ == "AssetTriggeredTimetable"
    assert "telco://bronze/ready" in repr(transform.timetable.asset_condition)
    assert [t.task_id for t in transform.tasks] == [
        "source_freshness",
        "dbt_build_silver",
        "dbt_build_gold",
        "dbt_build_dq",
    ]
    silver = transform.get_task("dbt_build_silver")
    assert silver.trigger_rule == "all_done", "freshness must not block"
    gold = transform.get_task("dbt_build_gold")
    assert gold.trigger_rule == "all_success", "gold must not build on a failed silver"
    assert not gold.outlets, "gold_ready waits for the quality gate"
    dq = transform.get_task("dbt_build_dq")
    assert {t.task_id for t in dq.upstream_list} == {"dbt_build_gold"}
    assert dq.retries == 0 and "tag:dq" in dq.bash_command
    assert {a.uri for a in dq.outlets} == {"telco://gold/ready"}
    # Tests that span layers must only run in the step that builds all their parents
    for task in (silver, gold, dq):
        assert "--indirect-selection buildable" in task.bash_command
