"""
### Daily file delivery -> Bronze (backfillable)

Each run represents ONE business day (the run's logical date, `{{ ds }}`):

1. `deliver_files` - the mediation platform and NMS "deliver" that day's CDR CSV
   and alarm JSON into `landing/` (simulated by copying the generated files)
2. `process_files` - validate, quarantine or load to Bronze, archive

Because the logical date drives which files are delivered, this DAG can be
**backfilled**: replaying 1-30 September re-delivers each day in order. Files
already loaded are recognised by MD5 and SKIPPED, so a backfill is safe to repeat.

* **Schedule:** daily, for the September 2026 data window
* **max_active_runs=1:** `landing/` is shared, so days are processed one at a time
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from telco_common.settings import DEFAULT_ARGS, ingest

with DAG(
    dag_id="telco_files_daily",
    description="Deliver one day's CDR + alarm files and load them to Bronze",
    schedule="@daily",
    start_date=pendulum.datetime(2026, 9, 1, tz="UTC"),
    end_date=pendulum.datetime(2026, 9, 30, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(hours=1),
    default_args=DEFAULT_ARGS,
    tags=["telco", "ingestion", "bronze", "files"],
    doc_md=__doc__,
) as dag:
    deliver = BashOperator(
        task_id="deliver_files",
        bash_command=ingest("drop-files --from {{ ds }} --to {{ ds }}"),
    )
    process = BashOperator(task_id="process_files", bash_command=ingest("files"))

    deliver >> process
