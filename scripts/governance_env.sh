#!/usr/bin/env bash
# Copy the policy tag ids (Terraform outputs) and the data steward (you) into .env,
# replacing old values. dbt reads them to tag PII columns and grant you full access;
# Airflow gets them through env_file. Run after every `make tf-apply` that changes tags.
set -euo pipefail
cd "$(dirname "$0")/.."
touch .env
tags_json="$(terraform -chdir=infra/terraform output -json policy_tags)"
steward="user:$(gcloud config get-value account 2>/dev/null)"

python3 - "$tags_json" "$steward" <<'PY'
import json
import pathlib
import sys

tags, steward = json.loads(sys.argv[1]), sys.argv[2]
values = {f"DBT_POLICY_TAG_{k.upper()}": v for k, v in tags.items()}
values["DATA_STEWARD"] = steward
env = pathlib.Path(".env")
kept = [line for line in env.read_text().splitlines() if line.split("=", 1)[0] not in values]
env.write_text("\n".join(kept + [f"{k}={v}" for k, v in sorted(values.items())]) + "\n")
for k in sorted(values):
    print(f"set {k}")
PY
