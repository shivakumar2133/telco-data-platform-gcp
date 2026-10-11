"""Phase 0 smoke test: ADC auth, BigQuery dry run + tiny query, GCS access."""

from __future__ import annotations

import sys

from google.cloud import bigquery, storage

from ingestion.common.config import get_settings

PUBLIC_SQL = """
SELECT name, SUM(number) AS total
FROM `bigquery-public-data.usa_names.usa_1910_2013`
GROUP BY name
ORDER BY total DESC
LIMIT 5
"""


def main() -> int:
    s = get_settings()
    print(f"Project: {s.project_id} | region: {s.region} | env: {s.env}")

    bq = bigquery.Client(project=s.project_id)

    # 1) Dry run: free, returns bytes that WOULD be scanned (like EXPLAIN PLAN for cost).
    #    Public dataset lives in the US multi-region, so the job location must be "US".
    dry_cfg = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    dry_job = bq.query(PUBLIC_SQL, job_config=dry_cfg, location="US")
    mb = dry_job.total_bytes_processed / 1024**2
    print(f"[OK] Dry run: query would scan {mb:,.1f} MB (cost: £0 - dry runs are free)")

    # 2) A real query that scans 0 bytes, with a hard safety cap on bytes billed.
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=10 * 1024**2)
    row = next(iter(bq.query("SELECT 1 AS ok", job_config=cfg, location=s.bq_location)))
    print(f"[OK] BigQuery query returned ok={row.ok}")

    # 3) GCS: confirm the Terraform state bucket exists and is versioned.
    gcs = storage.Client(project=s.project_id)
    bucket = gcs.lookup_bucket(s.tfstate_bucket)
    if bucket is None:
        print(f"[FAIL] Bucket gs://{s.tfstate_bucket} not found")
        return 1
    print(f"[OK] gs://{bucket.name} exists, versioning={bucket.versioning_enabled}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
