"""
### Hourly ticket ingestion -> Bronze

Tickets change all day, so they get their own, faster schedule than the
databases. Each run asks the API only for tickets updated since the last
watermark, so an hourly run is a few rows and a few seconds.

* **Schedule:** 15 minutes past every hour
* **Retries:** the extractor already retries 429/5xx itself; Airflow retries
  the whole task twice more if it still fails
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG
from telco_common.settings import DEFAULT_ARGS, ingest

with DAG(
    dag_id="telco_tickets_hourly",
    description="Incremental pull of trouble tickets from the REST API",
    schedule="15 * * * *",
    start_date=pendulum.datetime(2026, 10, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    dagrun_timeout=timedelta(minutes=30),
    default_args={**DEFAULT_ARGS, "execution_timeout": timedelta(minutes=15)},
    tags=["telco", "ingestion", "bronze", "api"],
    doc_md=__doc__,
) as dag:
    BashOperator(task_id="extract_tickets", bash_command=ingest("api"))
