import json

import pytest
from fastapi.testclient import TestClient

from sources.mock_api.app import create_app

KEY = "test-key"


@pytest.fixture
def client(tmp_path):
    tickets = [
        {"ticket_id": f"INC{i:07d}", "updated_at": f"2026-09-{i:02d}T10:00:00Z"}
        for i in range(1, 26)
    ]
    path = tmp_path / "tickets.json"
    path.write_text(json.dumps(tickets))
    app = create_app(tickets_file=str(path), api_key=KEY, failure_rate=0, rate_limit_per_sec=1000)
    return TestClient(app)


def get(client, **params):
    return client.get("/api/v1/tickets", headers={"X-API-Key": KEY}, params=params)


def test_missing_key_is_rejected(client):
    assert client.get("/api/v1/tickets").status_code == 401


def test_pagination_returns_every_ticket_once(client):
    seen, page = [], 1
    while page:
        body = get(client, page=page, page_size=10).json()
        seen += [t["ticket_id"] for t in body["data"]]
        page = body["next_page"]
    assert len(seen) == 25 and len(set(seen)) == 25


def test_updated_since_filters(client):
    body = get(client, updated_since="2026-09-20T10:00:00Z").json()
    assert body["total"] == 5  # 21st..25th (strictly greater than)


def test_page_size_is_capped(client):
    assert get(client, page_size=501).status_code == 422


def test_rate_limit(tmp_path):
    path = tmp_path / "t.json"
    path.write_text("[]")
    c = TestClient(create_app(tickets_file=str(path), api_key=KEY, rate_limit_per_sec=2))
    codes = [c.get("/api/v1/tickets", headers={"X-API-Key": KEY}).status_code for _ in range(5)]
    assert 429 in codes
