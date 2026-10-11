# ADR 0001: Region and free-tier strategy

**Status:** Accepted

## Context
Portfolio project on synthetic data, budget under £20. GCS always-free storage
applies only in us-east1, us-west1 and us-central1.

## Decision
Deploy all resources to `us-central1` (GCS buckets and BigQuery datasets in the
same region to avoid cross-location load errors). Run Airflow locally in Docker
instead of Cloud Composer. Budget alert at £20 (credits excluded) and a 30 GiB/day
BigQuery query quota.

## Consequences
- Near-zero cost; all code is Composer-compatible.
- In production with real UK customer data, I would use `europe-west2` (London)
  for data residency/UK GDPR, and Composer for managed orchestration.
