"""
### Transform Bronze -> Silver with dbt

Runs automatically whenever `telco_ingest_daily` publishes the `bronze_ready`
asset (i.e. after ingestion AND reconciliation pass). No clock schedule.

1. `source_freshness` - alerts if a Bronze table has gone quiet (does not block)
2. `dbt_build` - staging views, incremental MERGE into Silver, SCD2 snapshots,
   and all data tests, in dependency order. A failing test stops downstream models.

dbt runs in its own virtualenv and impersonates `sa-transform` (see profiles.yml).
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from telco_common.assets import BRONZE_READY, SILVER_READY
from telco_common.settings import DEFAULT_ARGS, dbt

with DAG(
    dag_id="telco_transform",
    description="dbt build: Bronze -> Silver (staging, incremental merge, SCD2, tests)",
    schedule=[BRONZE_READY],
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={**DEFAULT_ARGS, "retries": 1},
    tags=["telco", "transform", "silver", "dbt"],
    doc_md=__doc__,
) as dag:
    # Freshness measures when data last ARRIVED; a quiet source can be stale while the
    # pipeline is healthy. So it alerts (failure callback) but does not block the build.
    freshness = BashOperator(
        task_id="source_freshness", bash_command=dbt("source freshness"), retries=0
    )

    build = BashOperator(
        task_id="dbt_build",
        bash_command=dbt("build --select tag:staging tag:silver"),
        trigger_rule="all_done",
        outlets=[SILVER_READY],
    )

    freshness >> build
