"""Shared DAG settings: retry policy, alerting, and how tasks call the pipeline."""

from __future__ import annotations

from datetime import timedelta

from telco_common.alerts import notify_failure

# Every task: retry twice with growing delays (our ingestion is idempotent, so a
# retry is always safe), fail if it hangs, and alert on final failure.
DEFAULT_ARGS = {
    "owner": "data-eng",
    "retries": 2,
    "retry_delay": timedelta(minutes=2),
    "retry_exponential_backoff": True,
    "max_retry_delay": timedelta(minutes=15),
    "execution_timeout": timedelta(minutes=45),
    "on_failure_callback": notify_failure,
}


def pipeline(module_args: str) -> str:
    """Bash command that runs our code in the pipeline virtualenv.

    Environment variables (set in docker-compose) are expanded when the task RUNS,
    not when the DAG is parsed, so the DAG files stay static and fast to parse.
    """
    return f'cd "$PROJECT_DIR" && "$PIPELINE_PYTHON" -m {module_args}'


def ingest(args: str) -> str:
    """`python -m ingestion.run [--local DIR] <args>`."""
    return pipeline(f"ingestion.run $INGEST_EXTRA_ARGS {args}")
