"""Mock ServiceNow-style ticketing REST API.

Behaves like a real SaaS API so the extractor in Phase 3 has to handle:
  - API-key auth             (401 without X-API-Key)
  - pagination               (page / page_size / next_page)
  - incremental filter       (updated_since -> only changed tickets)
  - rate limiting            (429 + Retry-After when > RATE_LIMIT_PER_SEC)
  - random server errors     (503 at FAILURE_RATE, to exercise retries)

Run locally:  uvicorn sources.mock_api.app:app --port 8000
Docs:         http://localhost:8000/docs
"""

from __future__ import annotations

import json
import os
import random
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Header, Query
from fastapi.responses import JSONResponse


def _parse(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def create_app(
    tickets_file: str | None = None,
    api_key: str | None = None,
    failure_rate: float | None = None,
    rate_limit_per_sec: int | None = None,
) -> FastAPI:
    tickets_path = Path(tickets_file or os.getenv("TICKETS_FILE", "/data/tickets.json"))
    key = api_key or os.getenv("TICKETS_API_KEY", "local-dev-key")
    fail_p = failure_rate if failure_rate is not None else float(os.getenv("FAILURE_RATE", "0"))
    limit = rate_limit_per_sec or int(os.getenv("RATE_LIMIT_PER_SEC", "20"))

    app = FastAPI(title="Mock Ticketing API", version="1.0.0")
    state: dict = {"tickets": None, "window": 0, "count": 0}

    def tickets() -> list[tuple[datetime, dict]]:
        if state["tickets"] is None:  # lazy load so the app starts even before data exists
            raw = json.loads(tickets_path.read_text())
            rows = [(_parse(t["updated_at"]), t) for t in raw]
            # Stable order (updated_at, ticket_id): pages never skip/repeat rows
            rows.sort(key=lambda r: (r[0], r[1]["ticket_id"]))
            state["tickets"] = rows
        return state["tickets"]

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "tickets_file_exists": tickets_path.exists()}

    @app.get("/api/v1/tickets")
    def list_tickets(
        x_api_key: str | None = Header(default=None),
        updated_since: datetime | None = Query(default=None, description="ISO-8601, UTC"),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=500),
    ):
        if x_api_key != key:
            return JSONResponse({"error": "invalid or missing X-API-Key"}, status_code=401)

        now = int(time.time())
        if state["window"] != now:
            state["window"], state["count"] = now, 0
        state["count"] += 1
        if state["count"] > limit:
            return JSONResponse(
                {"error": "rate limit exceeded"}, status_code=429, headers={"Retry-After": "1"}
            )

        if fail_p and random.random() < fail_p:
            return JSONResponse({"error": "temporary upstream error"}, status_code=503)

        rows = tickets()
        if updated_since is not None:
            since = updated_since if updated_since.tzinfo else updated_since.replace(tzinfo=UTC)
            rows = [r for r in rows if r[0] > since]

        total = len(rows)
        start = (page - 1) * page_size
        data = [t for _, t in rows[start : start + page_size]]
        return {
            "data": data,
            "page": page,
            "page_size": page_size,
            "total": total,
            "next_page": page + 1 if start + page_size < total else None,
        }

    return app


app = create_app()
