"""Phase 12 verification: monitoring, alerting and cost are in place.

- the two log-based metrics and alert policies exist, are enabled, and notify by email
- ops.rpt_pipeline_health shows every source object and how fresh it is
- dbt jobs carry cost labels (node_id), so cost can be attributed per model
- last 30 days of BigQuery usage is inside the free tier

  python -m scripts.verify_phase12           # checks
  python -m scripts.verify_phase12 --drill   # + run a deliberately failing job as
                                             #   sa-transform: expect an alert email in ~5-10 min
"""

from __future__ import annotations

import argparse
import sys

import google.auth
from google.api_core import exceptions as gexc
from google.auth.transport.requests import AuthorizedSession
from google.cloud import bigquery

from ingestion.common.config import get_settings
from ingestion.common.gcp_auth import impersonate

METRICS = ["bq_pipeline_job_errors", "bq_access_denied"]
POLICIES = ["Pipeline: BigQuery job failed", "Security: repeated BigQuery access denied"]
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--drill", action="store_true", help="trigger a failing pipeline job")
    args = ap.parse_args()

    s = get_settings()
    p = s.project_id
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    http = AuthorizedSession(creds)

    for m in METRICS:
        r = http.get(f"https://logging.googleapis.com/v2/projects/{p}/metrics/{m}")
        check(f"log-based metric {m}", r.ok, "exists" if r.ok else r.text[:100])

    r = http.get(f"https://monitoring.googleapis.com/v3/projects/{p}/alertPolicies")
    policies = {x["displayName"]: x for x in r.json().get("alertPolicies", [])} if r.ok else {}
    for name in POLICIES:
        pol = policies.get(name)
        ok = bool(pol) and pol.get("enabled", True) and bool(pol.get("notificationChannels"))
        detail = "enabled, notifies email" if ok else ("missing" if not pol else "no channel")
        check(f"alert policy '{name}'", ok, detail)

    bq = bigquery.Client(project=p, location=s.bq_location)
    rep = bigquery.Client(
        project=p, location=s.bq_location, credentials=impersonate(s.sa_email("reporting"))
    )

    try:
        rows = list(rep.query(f"select * from `{p}.ops.rpt_pipeline_health`").result())
        stale = [
            f"{x.source_system}.{x.object_name}" for x in rows if x.freshness_status != "FRESH"
        ]
        check("pipeline health view (as sa-reporting)", len(rows) >= 13, f"{len(rows)} objects")
        print("\nPipeline health:")
        for x in sorted(rows, key=lambda x: (x.source_system, x.object_name)):
            hrs = "-" if x.hours_since_success is None else f"{x.hours_since_success}h"
            print(
                f"  {x.source_system:9} {x.object_name:17} {x.freshness_status:15} "
                f"last success {hrs:>6} ago, problems 7d: {x.problems_last_7d}"
            )
        if stale:
            print(f"  (not fresh: {', '.join(stale)} - expected if the pipeline hasn't run today)")
        print()
    except Exception as exc:  # noqa: BLE001
        check("pipeline health view (as sa-reporting)", False, str(exc).splitlines()[0][:100])

    jobs = f"`region-{s.bq_location.lower()}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT"
    labelled = next(
        iter(
            bq.query(f"""
        select count(*) from {jobs}
        where creation_time >= timestamp_sub(current_timestamp(), interval 7 day)
          and exists (select 1 from unnest(labels) where key = 'node_id')""").result()
        )
    )[0]
    check(
        "dbt jobs carry node_id cost labels (7 days)",
        labelled > 0,
        f"{labelled:,} labelled jobs" if labelled else "none yet - run make dbt-build",
    )

    gib = next(
        iter(
            bq.query(f"""
        select coalesce(sum(total_bytes_billed), 0) / pow(1024, 3) from {jobs}
        where creation_time >= timestamp_sub(current_timestamp(), interval 30 day)
          and job_type = 'QUERY'""").result()
        )
    )[0]
    check("BigQuery usage inside free tier (30 days)", gib < 1024, f"{gib:,.2f} GiB of 1,024 GiB")

    if args.drill:
        tr = bigquery.Client(
            project=p, location=s.bq_location, credentials=impersonate(s.sa_email("transform"))
        )
        try:
            tr.query("select error('alert drill: deliberate pipeline failure')").result()
            check("alert drill job failed as sa-transform", False, "the job did not fail?")
        except gexc.BadRequest:
            check(
                "alert drill job failed as sa-transform",
                True,
                "expect email 'Pipeline: BigQuery job failed' in 5-10 min",
            )

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    n_failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - n_failed}/{len(results)} checks passed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
