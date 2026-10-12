"""What does this platform cost to run? Measured from BigQuery's own job history.

    python -m scripts.cost_report                # last 30 days, terminal
    python -m scripts.cost_report --days 7
    python -m scripts.cost_report --markdown     # paste into the README / docs

Sections: per day, per identity (pipeline vs dashboards vs you), the most expensive dbt
models (dbt labels every job with node_id - see query-comment in dbt_project.yml) and the
most expensive single queries. Runs as you: needs bigquery.jobs.listAll (project owner).
The report itself reads INFORMATION_SCHEMA metadata only: a few MB.
"""

from __future__ import annotations

import argparse
import sys

from google.cloud import bigquery

from ingestion.common.config import get_settings

USD_PER_TIB = 6.25  # BigQuery on-demand list price; the first 1 TiB per month is free
TIB = 1024**4


def usd(bytes_billed: int | None) -> float:
    return (bytes_billed or 0) / TIB * USD_PER_TIB


def table(rows: list[tuple], head: list[str], markdown: bool) -> str:
    if markdown:
        out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
        out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
        return "\n".join(out)
    widths = [max(len(str(x)) for x in [h, *[r[i] for r in rows]]) for i, h in enumerate(head)]
    lines = ["  ".join(str(h).ljust(w) for h, w in zip(head, widths, strict=True))]
    lines += ["  ".join(str(c).ljust(w) for c, w in zip(r, widths, strict=True)) for r in rows]
    return "\n".join(lines)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--markdown", action="store_true")
    args = p.parse_args()

    s = get_settings()
    bq = bigquery.Client(project=s.project_id, location=s.bq_location)
    jobs = f"`region-{s.bq_location.lower()}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT"
    where = f"""creation_time >= timestamp_sub(current_timestamp(), interval {args.days} day)
                and job_type = 'QUERY' and state = 'DONE'"""
    cfg = bigquery.QueryJobConfig(maximum_bytes_billed=200 * 1024**2)

    def q(sql: str) -> list:
        return list(bq.query(sql, job_config=cfg).result())

    def who(email: str) -> str:
        return email.split("@")[0] if email.startswith("sa-") else f"{email.split('@')[0]} (you)"

    md = args.markdown
    print(f"## BigQuery cost, last {args.days} days ({s.project_id})\n")

    totals = q(f"select count(*) n, sum(total_bytes_billed) b from {jobs} where {where}")[0]
    gib = (totals.b or 0) / 1024**3
    print(
        f"{totals.n:,} queries, {gib:,.2f} GiB billed = ${usd(totals.b):.2f} at list price; "
        f"{gib / 1024 * 100:.2f}% of the free 1 TiB/month.\n"
    )

    print("### By identity")
    rows = q(f"""
        select user_email, count(*) n, sum(total_bytes_billed) b, sum(total_slot_ms) slot_ms
        from {jobs} where {where} group by 1 order by b desc""")
    print(
        table(
            [
                (who(r.user_email), f"{r.n:,}", f"{(r.b or 0) / 1024**3:,.2f}", f"${usd(r.b):.3f}")
                for r in rows
            ],
            ["identity", "queries", "GiB billed", "list cost"],
            md,
        )
    )

    print("\n### Most expensive dbt models and tests (job label node_id)")
    rows = q(f"""
        select (select value from unnest(labels) where key = 'node_id') node, count(*) n,
               sum(total_bytes_billed) b, avg(total_slot_ms) / 1000 avg_slot_s
        from {jobs} where {where}
          and exists (select 1 from unnest(labels) where key = 'node_id')
        group by 1 order by b desc limit 10""")
    print(
        table(
            [(r.node, r.n, f"{(r.b or 0) / 1024**2:,.1f}", f"{r.avg_slot_s:,.1f}") for r in rows]
            or [("(no labelled jobs yet - run make dbt-build)", "", "", "")],
            ["dbt node", "runs", "MiB billed", "avg slot-s"],
            md,
        )
    )

    print("\n### Top 5 single queries")
    rows = q(f"""
        select user_email, total_bytes_billed b,
               regexp_replace(substr(query, 1, 90), r'\\s+', ' ') q
        from {jobs} where {where} order by b desc limit 5""")
    print(
        table(
            [(who(r.user_email), f"{(r.b or 0) / 1024**2:,.1f}", r.q) for r in rows],
            ["identity", "MiB billed", "query (start)"],
            md,
        )
    )
    print(
        "\nGuards in place: 2 GB max per dbt query, 30 GiB/day project quota, "
        "budget alert, partition filters, 7-day expiry on scratch tables."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
