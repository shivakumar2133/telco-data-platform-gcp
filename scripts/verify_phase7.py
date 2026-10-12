"""Phase 7 verification: data quality + reconciliation results in BigQuery.

  - the DQ / recon tables exist in ops, partitioned (cheap to query, 90-day history)
  - the latest DQ run checked all 24 rules; no ERROR rule breached its tolerance
  - the latest reconciliation run has no FAIL and no NO_DATA (source totals captured)
  - sa-reporting can read the results (dashboards) but cannot write them

Then run `make dq-report` for the record-by-record comparison with the defect manifest.
Runs as you; queries scan a few MB of the ops dataset.
"""

from __future__ import annotations

import sys

from google.api_core.exceptions import Forbidden
from google.cloud import bigquery

from ingestion.common.config import get_settings
from ingestion.common.gcp_auth import impersonate

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main() -> int:
    s = get_settings()
    bq = bigquery.Client(project=s.project_id, location=s.bq_location)
    ops = f"{s.project_id}.ops"

    def rows(sql: str) -> list:
        return list(bq.query(sql).result())

    for table, field in [
        ("dq_failures", "detected_date"),
        ("dq_scorecard", "dq_run_date"),
        ("recon_results", "recon_run_date"),
        ("source_control_totals", "captured_at"),
    ]:
        try:
            t = bq.get_table(f"{ops}.{table}")
            part = t.time_partitioning.field if t.time_partitioning else None
            check(f"ops.{table} partitioned on {field}", part == field, f"rows={t.num_rows:,}")
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            check(f"ops.{table} exists", False, str(exc).splitlines()[0])

    score = rows(f"""
        select rule_id, severity, status, failed_records, population, failed_pct, max_failure_pct
        from `{ops}.dq_scorecard`
        where dq_run_id = (select dq_run_id from `{ops}.dq_scorecard`
                           order by dq_run_at desc limit 1)""")
    check("latest DQ run checked every rule", len(score) == 24, f"{len(score)} rules")
    breached = [r.rule_id for r in score if r.severity == "error" and r.status == "BREACHED"]
    check("no ERROR rule above tolerance", not breached, ", ".join(breached) or "all within")
    by_status: dict[str, int] = {}
    for r in score:
        by_status[r.status] = by_status.get(r.status, 0) + 1
    check("scorecard summary", True, str(dict(sorted(by_status.items()))))

    recon = rows(f"""
        select check_id, status, expected, actual
        from `{ops}.recon_results`
        where recon_run_id = (select recon_run_id from `{ops}.recon_results`
                              order by recon_run_at desc limit 1)""")
    failed = [r.check_id for r in recon if r.status == "FAIL"]
    no_data = [r.check_id for r in recon if r.status == "NO_DATA"]
    check("reconciliation: no FAIL", not failed, ", ".join(failed[:5]) or f"{len(recon)} checks")
    check(
        "reconciliation: no NO_DATA",
        not no_data,
        ", ".join(no_data[:3]) or "source totals captured",
    )

    # least privilege: reporting reads results, cannot change them
    rep = bigquery.Client(
        project=s.project_id,
        location=s.bq_location,
        credentials=impersonate(s.sa_email("reporting")),
    )
    n = next(iter(rep.query(f"select count(*) from `{ops}.dq_scorecard`").result()))[0]
    check("sa-reporting can read dq_scorecard", n > 0, f"{n:,} rows")
    try:
        rep.query(f"delete from `{ops}.dq_scorecard` where false").result()
        check("sa-reporting cannot modify DQ results", False, "DELETE was allowed!")
    except Forbidden:
        check("sa-reporting cannot modify DQ results", True, "403 as expected")

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    n_failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - n_failed}/{len(results)} checks passed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
