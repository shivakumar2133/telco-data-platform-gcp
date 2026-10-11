"""Extract trouble tickets from the REST API into Bronze.

Handles what real SaaS APIs throw at you:
  401          -> fail fast (bad key; retrying won't help)
  429          -> wait for Retry-After, then retry
  5xx / network errors -> exponential backoff (1s, 2s, 4s ...), up to N attempts
  pagination   -> follow next_page until null
  incremental  -> updated_since = last watermark
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pandas as pd

from ingestion.common.context import RunContext
from ingestion.common.lake import raw_prefix, write_parquet
from ingestion.common.log import get_logger
from ingestion.common.metadata import AuditRecord, frame_checksum
from ingestion.common.schema import add_metadata, all_string_schema, to_arrow
from ingestion.common.secrets import get_secret

log = get_logger(__name__)
SYSTEM, OBJECT = "api", "tickets"


class ApiError(RuntimeError):
    pass


def get_with_retry(
    client: httpx.Client,
    url: str,
    params: dict,
    headers: dict,
    max_attempts: int = 6,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[dict, int]:
    """GET a JSON page. Returns (body, number_of_retries)."""
    retries = 0
    for attempt in range(1, max_attempts + 1):
        try:
            r = client.get(url, params=params, headers=headers, timeout=30)
        except httpx.TransportError as exc:
            wait, reason = min(30.0, 2.0 ** (attempt - 1)), f"network: {exc}"
        else:
            if r.status_code == 200:
                return r.json(), retries
            if r.status_code in (401, 403):
                raise ApiError(f"HTTP {r.status_code}: check the API key")
            if r.status_code == 429:
                wait, reason = float(r.headers.get("Retry-After", "1")), "rate limited"
            elif r.status_code >= 500:
                wait, reason = min(30.0, 2.0 ** (attempt - 1)), f"HTTP {r.status_code}"
            else:
                raise ApiError(f"HTTP {r.status_code}: {r.text[:200]}")
        if attempt == max_attempts:
            raise ApiError(f"giving up after {max_attempts} attempts ({reason})")
        retries += 1
        log.warning(
            "retrying",
            extra={
                "fields": {"reason": reason, "wait_s": wait, "attempt": attempt, "params": params}
            },
        )
        sleep(wait)
    raise ApiError("unreachable")


def fetch_tickets(
    client: httpx.Client,
    base_url: str,
    api_key: str,
    updated_since: datetime | None,
    page_size: int = 200,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[list[dict], dict]:
    url = f"{base_url.rstrip('/')}/api/v1/tickets"
    headers = {"X-API-Key": api_key}
    rows: list[dict] = []
    stats = {"pages": 0, "retries": 0, "reported_total": None}
    page: int | None = 1
    while page:
        params = {"page": page, "page_size": page_size}
        if updated_since is not None:
            params["updated_since"] = updated_since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        body, retries = get_with_retry(client, url, params, headers, sleep=sleep)
        rows.extend(body["data"])
        stats["pages"] += 1
        stats["retries"] += retries
        stats["reported_total"] = body["total"]
        page = body["next_page"]
    return rows, stats


def run_api(ctx: RunContext, force_full: bool = False) -> list[AuditRecord]:
    wm = None if force_full else ctx.meta.get_watermarks().get((SYSTEM, OBJECT))
    rec = AuditRecord(
        ctx.run_id, SYSTEM, OBJECT, "FULL" if wm is None else "INCREMENTAL", watermark_from=wm
    )
    try:
        base_url = os.getenv("TICKETS_API_URL", "http://localhost:8000")
        api_key = get_secret("tickets-api-key", sa_email=ctx.ingest_sa)
        with httpx.Client() as client:
            rows, stats = fetch_tickets(client, base_url, api_key, wm)

        rec.source_row_count = stats["reported_total"]
        df = pd.DataFrame(rows)
        rec.source_checksum = frame_checksum(df)
        if df.empty:
            rec.loaded_row_count = 0
            ctx.meta.write_audit(rec.finish("SUCCESS"))
            return [rec]

        table = add_metadata(
            to_arrow(df, all_string_schema(df.columns)),
            {
                "_run_id": ctx.run_id,
                "_source_system": SYSTEM,
                "_source_object": OBJECT,
                "_extract_mode": rec.load_type,
            },
            ctx.started_at,
        )
        prefix = raw_prefix(SYSTEM, OBJECT, ctx.started_at, ctx.run_id)
        write_parquet(ctx.lake, f"{prefix}/part-00000.parquet", table)
        rec.gcs_uri = ctx.lake.uri(f"{prefix}/*.parquet")
        rec.loaded_row_count = ctx.loader.load(f"{SYSTEM}__{OBJECT}", rec.gcs_uri)

        if not (rec.source_row_count == len(df) == rec.loaded_row_count):
            ctx.meta.write_audit(
                rec.finish(
                    "FAILED",
                    f"count mismatch: api_total={rec.source_row_count} fetched={len(df)} "
                    f"loaded={rec.loaded_row_count}",
                )
            )
            return [rec]

        new_wm = pd.to_datetime(df["updated_at"], utc=True).max().to_pydatetime()
        ctx.meta.set_watermark(SYSTEM, OBJECT, "updated_at", new_wm)
        rec.watermark_to = new_wm
        log.info("extracted", extra={"fields": {"object": "tickets", "rows": len(df), **stats}})
        ctx.meta.write_audit(rec.finish("SUCCESS"))
    except Exception as exc:  # noqa: BLE001
        log.exception("api extract failed")
        ctx.meta.write_audit(rec.finish("FAILED", f"{type(exc).__name__}: {exc}"))
    return [rec]
