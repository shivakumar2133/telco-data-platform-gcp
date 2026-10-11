import pytest

from ingestion.common.config import get_settings


def test_settings_read_from_env(monkeypatch):
    monkeypatch.setenv("GCP_PROJECT_ID", "demo-project")
    monkeypatch.setenv("GCP_REGION", "europe-west2")
    monkeypatch.delenv("BQ_LOCATION", raising=False)
    monkeypatch.delenv("ENV", raising=False)

    s = get_settings(load_env_file=False)

    assert s.project_id == "demo-project"
    assert s.region == "europe-west2"
    assert s.bq_location == "europe-west2"  # defaults to region
    assert s.env == "dev"
    assert s.tfstate_bucket == "demo-project-tfstate"


def test_missing_project_id_raises(monkeypatch):
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID is not set"):
        get_settings(load_env_file=False)
