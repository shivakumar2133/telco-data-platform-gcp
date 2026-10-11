import json
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "orchestration" / "dags"))

from telco_common import alerts  # noqa: E402

TI = SimpleNamespace(
    dag_id="telco_ingest_daily",
    task_id="extract_databases.extract_oracle",
    run_id="scheduled__2026-10-12T02:00:00+00:00",
    try_number=3,
)


def test_message_contains_what_on_call_needs():
    msg = alerts.build_message({"ti": TI, "exception": RuntimeError("ORA-12541: no listener")})
    for part in ("telco_ingest_daily", "extract_oracle", "try 3", "ORA-12541", "/runs/"):
        assert part in msg


def test_no_webhook_configured_does_not_post(monkeypatch):
    monkeypatch.delenv("ALERT_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        alerts, "post_webhook", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    alerts.notify_failure({"ti": TI})


def test_webhook_payload_works_for_slack_and_discord(monkeypatch):
    sent = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(req, timeout):
        sent["body"] = json.loads(req.data)
        return FakeResponse()

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.example.com/x")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", fake_urlopen)
    alerts.notify_failure({"ti": TI})
    assert "extract_oracle" in sent["body"]["text"] and "extract_oracle" in sent["body"]["content"]


def test_broken_webhook_never_raises(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://hooks.example.com/x")
    monkeypatch.setattr(alerts.urllib.request, "urlopen", boom)
    alerts.notify_failure({"ti": TI})  # must not raise
