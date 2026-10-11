from types import SimpleNamespace

import pytest

from ingestion.common import secrets


@pytest.fixture(autouse=True)
def clear_cache():
    secrets._from_gcp.cache_clear()
    yield
    secrets._from_gcp.cache_clear()


def test_env_backend(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "env")
    monkeypatch.setenv("TICKETS_API_KEY", "abc123")
    assert secrets.get_secret("tickets-api-key") == "abc123"


def test_env_backend_missing_var(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "env")
    monkeypatch.delenv("ORACLE_ETL_READER_PASSWORD", raising=False)
    with pytest.raises(KeyError, match="ORACLE_ETL_READER_PASSWORD"):
        secrets.get_secret("oracle-etl-reader-password")


def test_unknown_backend(monkeypatch):
    monkeypatch.setenv("SECRETS_BACKEND", "vault")
    with pytest.raises(ValueError):
        secrets.get_secret("x")


def test_gcp_backend_builds_resource_name(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, credentials=None):
            pass

        def access_secret_version(self, name):
            calls.append(name)
            return SimpleNamespace(payload=SimpleNamespace(data=b"s3cret"))

    monkeypatch.setenv("SECRETS_BACKEND", "gcp")
    monkeypatch.setattr(secrets.secretmanager, "SecretManagerServiceClient", FakeClient)

    assert secrets.get_secret("tickets-api-key", project_id="demo") == "s3cret"
    assert secrets.get_secret("tickets-api-key", project_id="demo") == "s3cret"
    assert calls == ["projects/demo/secrets/tickets-api-key/versions/latest"]  # cached
