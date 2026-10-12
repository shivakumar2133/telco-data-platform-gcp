#!/usr/bin/env bash
# Copy what the GitHub workflows need into GitHub *repository variables* (not secrets:
# none of these values is secret - access is controlled by Workload Identity, not by
# hiding names). Needs the GitHub CLI logged in: `gh auth login`.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID missing in .env}"
: "${DBT_POLICY_TAG_EMAIL:?run make governance-env first}"
command -v gh >/dev/null || { echo "Install the GitHub CLI first: sudo apt install gh"; exit 1; }

TF="terraform -chdir=infra/terraform"
setvar() { gh variable set "$1" --body "$2" >/dev/null && echo "set $1"; }

setvar GCP_PROJECT_ID "$GCP_PROJECT_ID"
setvar BQ_LOCATION "${BQ_LOCATION:-us-central1}"
setvar DEVELOPER_EMAIL "$(gcloud config get-value account 2>/dev/null)"
setvar WIF_PROVIDER "$($TF output -raw wif_provider)"
setvar CICD_SA "sa-cicd@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
setvar TRANSFORM_SA "sa-transform@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
setvar DATA_STEWARD "$DATA_STEWARD"
for t in EMAIL PHONE NAME BIRTH_DATE POSTCODE RAW_RECORD; do
  name="DBT_POLICY_TAG_${t}"
  setvar "$name" "${!name}"
done
echo
gh variable list
