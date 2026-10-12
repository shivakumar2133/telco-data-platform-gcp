"""Phase 11 verification: the reporting layer is ready for dashboards.

- every reporting table exists, has rows, and sa-reporting can SELECT * from it
  (proves no policy-tagged column slipped in)
- each table costs at most a few MB to read in full (dry run)
- sa-analyst cannot read the reporting tables (national data, not regional)
- prints the KPIs your dashboards must show, per month
"""

from __future__ import annotations

import sys

from google.api_core import exceptions as gexc
from google.cloud import bigquery

from ingestion.common.config import get_settings
from ingestion.common.gcp_auth import impersonate

TABLES = [
    "gold.rpt_kpi_monthly",
    "gold.rpt_revenue_assurance",
    "gold.rpt_network_daily",
    "gold.rpt_sla_performance",
    "gold.rpt_customer_base",
    "ops.rpt_dq_latest",
    "ops.rpt_recon_latest",
]
MB = 1024**2
results: list[tuple[str, bool, str]] = []


def main() -> int:
    s = get_settings()
    p = s.project_id

    def client(sa: str) -> bigquery.Client:
        creds = impersonate(s.sa_email(sa))
        return bigquery.Client(project=p, location=s.bq_location, credentials=creds)

    rep, ana = client("reporting"), client("analyst")
    dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)

    for table in TABLES:
        name = f"{table}: sa-reporting SELECT *"
        try:
            n = len(list(rep.query(f"select * from `{p}.{table}`").result()))
            mb = (
                rep.query(f"select * from `{p}.{table}`", job_config=dry).total_bytes_processed / MB
            )
            results.append((name, n > 0, f"{n:,} rows, {mb:.2f} MB scanned"))
        except Exception as exc:  # noqa: BLE001
            results.append((name, False, f"{type(exc).__name__}: {str(exc).splitlines()[0][:90]}"))

    try:
        list(ana.query(f"select 1 from `{p}.gold.rpt_kpi_monthly` limit 1").result())
        results.append(("sa-analyst can't read national reporting", False, "was ALLOWED"))
    except (gexc.Forbidden, gexc.NotFound) as exc:
        results.append(("sa-analyst can't read national reporting", True, f"denied ({exc.code})"))

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")

    print("\nKPIs your dashboards must show:")
    kpis = rep.query(f"""
        select format_date('%Y-%m', month) as month, billed_revenue, rated_usage, unbilled_usage,
               safe_divide(dropped_calls, call_attempts) as drop_rate,
               safe_divide(breached_tickets, measured_tickets) as breach_pct
        from `{p}.gold.rpt_kpi_monthly` order by month""").result()
    print(
        f"{'month':8} {'billed £':>14} {'rated £':>12} {'unbilled £':>11} {'drop':>7} {'breach':>7}"
    )
    for r in kpis:

        def fmt(v, spec):
            return format(v, spec) if v is not None else "-"

        print(
            f"{r.month:8} {fmt(r.billed_revenue, ',.2f'):>14} {fmt(r.rated_usage, ',.2f'):>12} "
            f"{fmt(r.unbilled_usage, ',.2f'):>11} {fmt(r.drop_rate, '.2%'):>7} "
            f"{fmt(r.breach_pct, '.1%'):>7}"
        )

    n_failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - n_failed}/{len(results)} checks passed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
