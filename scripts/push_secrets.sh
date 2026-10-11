#!/usr/bin/env bash
# Copy local credentials from .env into Secret Manager.
# Adds a new version only when the value changed (the free tier covers a few
# active versions, so we don't create a new one on every run).
# Values are piped via stdin: never on the command line, never in Terraform state.
set -euo pipefail

cd "$(dirname "$0")/.."
set -a
# shellcheck disable=SC1091
source .env
set +a

: "${GCP_PROJECT_ID:?GCP_PROJECT_ID missing in .env}"
: "${ETL_READER_PASSWORD:?ETL_READER_PASSWORD missing in .env}"
: "${TICKETS_API_KEY:?TICKETS_API_KEY missing in .env}"

push() {
  local secret="$1" value="$2" current
  current="$(gcloud secrets versions access latest --secret="$secret" \
               --project="$GCP_PROJECT_ID" 2>/dev/null || true)"
  if [[ "$current" == "$value" ]]; then
    echo "unchanged  $secret"
  else
    printf '%s' "$value" | gcloud secrets versions add "$secret" \
      --project="$GCP_PROJECT_ID" --data-file=- >/dev/null
    echo "updated    $secret"
  fi
}

push oracle-etl-reader-password   "$ETL_READER_PASSWORD"
push mssql-etl-reader-password    "$ETL_READER_PASSWORD"
push postgres-etl-reader-password "$ETL_READER_PASSWORD"
push tickets-api-key              "$TICKETS_API_KEY"
