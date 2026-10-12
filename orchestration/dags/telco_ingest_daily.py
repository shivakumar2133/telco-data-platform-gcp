"""
### Daily database ingestion -> Bronze

Extracts the three source databases incrementally (watermark CDC), captures
source control totals (row counts, money sums) for reconciliation, then runs
the Bronze reconciliation. If reconciliation passes, the `bronze_ready` asset is
updated, which triggers the dbt transformation DAG (`telco_transform`).

* **Schedule:** 02:00 UTC daily
* **Parallelism:** at most 2 source databases extracted at once (protects sources)
* **Retries:** 2, with exponential backoff; alerts on final failure
* **Reconciliation:** no retries - a mismatch needs a human, not another attempt
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG, TaskGroup
from telco_common.assets import BRONZE_READY
from telco_common.settings import DEFAULT_ARGS, ingest, pipeline

with DAG(
    dag_id="telco_ingest_daily",
    description="Incremental extract of Oracle, SQL Server and PostgreSQL into Bronze",
    schedule="0 2 * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    max_active_tasks=2,
    dagrun_timeout=timedelta(hours=2),
    default_args=DEFAULT_ARGS,
    tags=["telco", "ingestion", "bronze"],
    doc_md=__doc__,
) as dag:
    with TaskGroup("extract_databases") as extract_databases:
        for system in ("postgres", "mssql", "oracle"):
            BashOperator(
                task_id=f"extract_{system}",
                bash_command=ingest(f"db --system {system}"),
            )

    # Independent "expected" totals, read from the sources right after extraction.
    # dbt's recon_results compares them with Bronze and Silver (telco_transform).
    capture_totals = BashOperator(
        task_id="capture_source_totals",
        bash_command=pipeline("quality.capture_source_totals $INGEST_EXTRA_ARGS"),
    )

    reconcile = BashOperator(
        task_id="reconcile_bronze",
        bash_command=pipeline("scripts.verify_phase3"),
        retries=0,
        outlets=[BRONZE_READY],
    )

    extract_databases >> capture_totals >> reconcile
