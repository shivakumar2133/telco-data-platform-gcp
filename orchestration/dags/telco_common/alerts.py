"""Failure alerting for every task.

Logs the failure and, if ALERT_WEBHOOK_URL is set in .env, posts it to a chat
webhook. The payload carries both "text" (Slack, Google Chat, Teams workflows)
and "content" (Discord), so any of them works without code changes.

Pure standard library: no Airflow imports, so it is unit-testable anywhere.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

log = logging.getLogger(__name__)


def build_message(context: dict) -> str:
    ti = context.get("ti") or context.get("task_instance")
    dag_id = getattr(ti, "dag_id", "?")
    task_id = getattr(ti, "task_id", "?")
    run_id = getattr(ti, "run_id", "?")
    try_number = getattr(ti, "try_number", "?")
    base = os.getenv("AIRFLOW__API__BASE_URL", "http://localhost:8080").rstrip("/")
    url = getattr(ti, "log_url", None) or f"{base}/dags/{dag_id}/runs/{run_id}/tasks/{task_id}"
    exc = context.get("exception")
    reason = f"{type(exc).__name__}: {exc}"[:300] if exc else "see task log"
    return (
        f":red_circle: Airflow task failed\n"
        f"DAG: {dag_id}\nTask: {task_id}\nRun: {run_id} (try {try_number})\n"
        f"Error: {reason}\nLog: {url}"
    )


def post_webhook(url: str, message: str, timeout_s: int = 10) -> None:
    body = json.dumps({"text": message, "content": message[:1900]}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s):  # noqa: S310 - URL comes from our own config
        pass


def notify_failure(context: dict) -> None:
    """Airflow on_failure_callback. Must never raise: a broken alert must not hide the failure."""
    message = build_message(context)
    log.error(message)
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not url:
        return
    try:
        post_webhook(url, message)
    except Exception as exc:  # noqa: BLE001
        log.error("Could not send alert to webhook: %s", exc)
