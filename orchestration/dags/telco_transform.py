"""
### Transform Bronze -> Silver -> Gold with dbt

Runs automatically whenever `telco_ingest_daily` publishes the `bronze_ready`
asset (i.e. after ingestion AND reconciliation pass). No clock schedule.

1. `source_freshness` - alerts if a Bronze table has gone quiet (does not block)
2. `dbt_build_silver` - staging views, incremental MERGE into Silver, SCD2 snapshots
   and their tests. A failing test stops everything downstream.
3. `dbt_build_gold` - star schema (dimensions, facts, marts) and its reconciliation
   tests.
4. `dbt_build_dq` - 24 data quality rules (record-level failures + scorecard) and
   cross-layer reconciliation (source -> Bronze -> Silver -> Gold). An ERROR rule above
   tolerance or a reconciliation mismatch fails here, so `gold_ready` (dashboards,
   extracts) is only published for data that passed the quality gate.

dbt runs in its own virtualenv and impersonates `sa-transform` (see profiles.yml).
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from telco_common.assets import BRONZE_READY, GOLD_READY, SILVER_READY
from telco_common.settings import DEFAULT_ARGS, dbt

with DAG(
    dag_id="telco_transform",
    description="dbt build: Bronze -> Silver (merge, SCD2) -> Gold (star schema), with tests",
    schedule=[BRONZE_READY],
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args={**DEFAULT_ARGS, "retries": 1},
    tags=["telco", "transform", "silver", "gold", "dbt"],
    doc_md=__doc__,
) as dag:
    # Freshness measures when data last ARRIVED; a quiet source can be stale while the
    # pipeline is healthy. So it alerts (failure callback) but does not block the build.
    freshness = BashOperator(
        task_id="source_freshness", bash_command=dbt("source freshness"), retries=0
    )

    build_silver = BashOperator(
        task_id="dbt_build_silver",
        bash_command=dbt("build --select tag:staging tag:silver --indirect-selection buildable"),
        trigger_rule="all_done",
        outlets=[SILVER_READY],
    )

    build_gold = BashOperator(
        task_id="dbt_build_gold",
        bash_command=dbt("build --select tag:gold --indirect-selection buildable"),
    )

    # Quality gate (circuit breaker): consumers hear about Gold only after DQ + recon pass
    build_dq = BashOperator(
        task_id="dbt_build_dq",
        bash_command=dbt("build --select tag:dq --indirect-selection buildable"),
        retries=0,  # a breached rule needs a human, not another attempt
        outlets=[GOLD_READY],
    )

    freshness >> build_silver >> build_gold >> build_dq
