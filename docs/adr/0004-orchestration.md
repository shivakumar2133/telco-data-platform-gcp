# ADR 0004: Orchestration with Airflow 3 (local Docker, Composer-compatible)

**Status:** Accepted

## Context
Ingestion must run on schedules, retry transient failures, alert a human on real
failures, and be able to re-run past days. Cloud Composer (managed Airflow) costs
hundreds of pounds a month even when idle.

## Decisions
1. **Airflow 3.3.2 in Docker**, adapted from the official docker-compose with the
   **LocalExecutor** (no Celery/Redis), to fit a laptop next to Oracle and SQL Server.
   The DAG code is standard Airflow 3 and would run unchanged on Cloud Composer 3.
2. **Pipeline code runs in its own virtualenv** inside the image, called by
   BashOperator. Airflow's pinned dependencies and ours never mix. DAG files import
   nothing from the pipeline, so parsing stays fast and a pipeline bug can't break
   the scheduler. (On Composer, the equivalent is KubernetesPodOperator.)
3. **Schedules follow the data**: databases daily at 02:00 UTC, tickets hourly,
   files per business day. Each DAG has `max_active_runs=1` because runs share
   watermarks and the landing folder.
4. **Retries for transient errors, none for reconciliation.** Ingestion is idempotent,
   so tasks retry twice with exponential backoff. The reconciliation gate never retries:
   a mismatch needs investigation, not another attempt.
5. **Alerting** via `on_failure_callback` to any chat webhook (Slack/Discord/Google Chat),
   configured by one env var. The callback never raises.
6. **Backfill by logical date.** The files DAG delivers the files for `{{ ds }}`, so
   `airflow backfill create` replays history; MD5 de-duplication makes replays safe.
7. **Data-aware hand-off.** A passing reconciliation updates the `bronze_ready`
   Asset, which the transformation DAG (Phase 5) will be scheduled on.
8. **SLAs**: Airflow 3 removed the old SLA mechanism; we rely on `execution_timeout`
   and `dagrun_timeout` so nothing can hang silently.

## Consequences
- Same DAGs locally and on Composer; only the deployment differs.
- The image must be rebuilt when requirements.txt changes (`make airflow-build`).
