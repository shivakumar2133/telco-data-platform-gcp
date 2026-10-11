#!/usr/bin/env bash
set -euo pipefail
PYTHON="${PYTHON:-python}"

echo "== Tool versions =="
for cmd in git python3 docker gcloud terraform make; do
  if command -v "$cmd" >/dev/null 2>&1; then
    printf "%-10s %s\n" "$cmd" "$("$cmd" --version 2>&1 | head -n1)"
  else
    echo "MISSING: $cmd"; exit 1
  fi
done

echo "== Docker daemon =="
docker info >/dev/null 2>&1 && echo "docker daemon OK" || { echo "Docker not reachable"; exit 1; }

echo "== gcloud =="
echo "active project: $(gcloud config get-value project 2>/dev/null)"
gcloud services list --enabled --format="value(config.name)" \
  | grep -E "^(bigquery|storage|secretmanager|pubsub)\.googleapis\.com$"

echo "== Python GCP smoke test =="
"$PYTHON" -m scripts.check_gcp
echo "Phase 0 verified."
