"""Security rules for the GitHub workflows, enforced as tests (policy as code)."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = sorted((Path(__file__).resolve().parents[2] / ".github" / "workflows").glob("*.yml"))


def load(path: Path) -> dict:
    wf = yaml.safe_load(path.read_text())
    wf["on"] = wf.get("on", wf.get(True))  # YAML 1.1 reads the key `on` as True
    return wf


def steps(wf: dict):
    for job in wf["jobs"].values():
        yield from job.get("steps", [])


def test_workflows_exist():
    assert {p.name for p in WORKFLOWS} == {"ci.yml", "terraform-plan.yml", "deploy-dbt.yml"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_least_privilege_token(path):
    wf = load(path)
    assert "permissions" in wf, "set permissions explicitly (default token is too broad)"
    assert wf["permissions"].get("contents") == "read"
    assert "pull_request_target" not in wf["on"], "runs fork code with secrets"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_actions_pinned_to_a_version(path):
    for step in steps(load(path)):
        if "uses" in step:
            assert "@v" in step["uses"], f"unpinned action {step['uses']}"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_keyless_auth_only(path):
    text = path.read_text()
    assert "credentials_json" not in text, "use Workload Identity Federation, not a JSON key"
    for step in steps(load(path)):
        if step.get("uses", "").startswith("google-github-actions/auth"):
            assert load(path)["permissions"].get("id-token") == "write"
            assert "workload_identity_provider" in step["with"]


def test_ci_has_no_cloud_access():
    wf = load(next(p for p in WORKFLOWS if p.name == "ci.yml"))
    assert "id-token" not in wf["permissions"]
    assert not any(s.get("uses", "").startswith("google-github-actions") for s in steps(wf))


def test_pull_requests_never_act_as_the_production_identity():
    plan = load(next(p for p in WORKFLOWS if p.name == "terraform-plan.yml"))
    assert "pull_request" in plan["on"]
    job = plan["jobs"]["plan"]
    assert "head.repo.full_name == github.repository" in job["if"], "forks must get no cloud access"
    auth = next(s for s in job["steps"] if s.get("uses", "").startswith("google-github-actions"))
    assert auth["with"]["service_account"] == "${{ vars.CICD_SA }}"
    assert "-lock=false" in str(job["steps"]), "read-only identity cannot take the state lock"
    runs = " ".join(s.get("run", "") for s in job["steps"])
    assert "terraform -chdir=infra/terraform apply" not in runs, "CI plans, humans apply"


def test_deploy_only_after_green_ci_on_main():
    wf = load(next(p for p in WORKFLOWS if p.name == "deploy-dbt.yml"))
    assert wf["on"]["workflow_run"]["workflows"] == ["CI"]
    assert wf["on"]["workflow_run"]["branches"] == ["main"]
    job = wf["jobs"]["dbt"]
    assert "conclusion == 'success'" in job["if"]
    assert job["env"]["DBT_IMPERSONATE_SA"] == ""
    auth = next(s for s in job["steps"] if s.get("uses", "").startswith("google-github-actions"))
    assert auth["with"]["service_account"] == "${{ vars.TRANSFORM_SA }}"
    assert wf["concurrency"]["cancel-in-progress"] is False, "never kill a build halfway"
