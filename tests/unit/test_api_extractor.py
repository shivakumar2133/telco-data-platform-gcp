from datetime import UTC, datetime

import httpx
import pytest

from ingestion.extractors.api_extractor import ApiError, fetch_tickets, get_with_retry

TICKETS = [
    {"ticket_id": f"INC{i:07d}", "updated_at": f"2026-09-{i:02d}T10:00:00Z"} for i in range(1, 8)
]


def paginated_handler(request: httpx.Request) -> httpx.Response:
    if request.headers.get("X-API-Key") != "k":
        return httpx.Response(401)
    page = int(request.url.params["page"])
    size = int(request.url.params["page_size"])
    data = TICKETS[(page - 1) * size : page * size]
    nxt = page + 1 if page * size < len(TICKETS) else None
    return httpx.Response(
        200,
        json={
            "data": data,
            "page": page,
            "page_size": size,
            "total": len(TICKETS),
            "next_page": nxt,
        },
    )


def test_follows_pagination():
    client = httpx.Client(transport=httpx.MockTransport(paginated_handler))
    rows, stats = fetch_tickets(client, "http://api", "k", None, page_size=3, sleep=lambda s: None)
    assert [r["ticket_id"] for r in rows] == [t["ticket_id"] for t in TICKETS]
    assert stats["pages"] == 3 and stats["reported_total"] == 7


def test_sends_watermark_as_utc_iso():
    seen = {}

    def handler(request):
        seen.update(request.url.params)
        return httpx.Response(200, json={"data": [], "total": 0, "next_page": None})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetch_tickets(client, "http://api", "k", datetime(2026, 9, 30, 12, tzinfo=UTC))
    assert seen["updated_since"] == "2026-09-30T12:00:00Z"


def test_retries_429_and_503_then_succeeds():
    responses = iter(
        [
            httpx.Response(429, headers={"Retry-After": "2"}),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    waits = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: next(responses)))
    body, retries = get_with_retry(client, "http://api/x", {}, {}, sleep=waits.append)
    assert body == {"ok": True} and retries == 2
    assert waits == [2.0, 2.0]  # Retry-After honoured; then backoff 2^(2-1)


def test_bad_key_fails_fast_without_retry():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ApiError, match="401"):
        get_with_retry(client, "http://api/x", {}, {}, sleep=lambda s: None)
    assert len(calls) == 1


def test_gives_up_after_max_attempts():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(ApiError, match="giving up"):
        get_with_retry(client, "http://api/x", {}, {}, max_attempts=3, sleep=lambda s: None)
