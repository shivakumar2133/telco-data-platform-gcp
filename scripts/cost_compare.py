"""Measure what partitioning + clustering actually save, with real BigQuery jobs.

Builds an UNpartitioned, UNclustered copy of gold.fct_calls in the scratch dataset
(auto-deleted after 7 days), then runs the same queries against both tables and
reports bytes processed. Columnar storage is shown too: SELECT * vs 3 columns.

    python -m scripts.cost_compare             # table in the terminal
    python -m scripts.cost_compare --markdown  # paste into your README

Cost: one-off copy (~the size of fct_calls) + a few small queries. Free tier.
"""

from __future__ import annotations

import argparse
import sys

from google.cloud import bigquery

from ingestion.common.config import get_settings

MB = 1024**2


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--markdown", action="store_true")
    args = p.parse_args()

    s = get_settings()
    bq = bigquery.Client(project=s.project_id, location=s.bq_location)
    gold = f"`{s.project_id}.gold.fct_calls`"
    flat = f"`{s.project_id}.scratch.fct_calls_unpartitioned`"

    bq.query(f"CREATE TABLE IF NOT EXISTS {flat} AS SELECT * FROM {gold}").result()
    cell_sk = next(
        iter(
            bq.query(
                f"SELECT cell_sk FROM {gold} WHERE call_date = '2026-09-15' "
                "GROUP BY 1 ORDER BY COUNT(*) DESC LIMIT 1"
            ).result()
        )
    )[0]

    queries = [
        (
            "One day, one cell",
            "SELECT COUNT(*), SUM(charge_amount) FROM {t} "
            f"WHERE call_date = '2026-09-15' AND cell_sk = {cell_sk}",
        ),
        (
            "One week, all cells",
            "SELECT cell_sk, COUNT(*), COUNTIF(is_dropped) FROM {t} "
            "WHERE call_date BETWEEN '2026-09-08' AND '2026-09-14' GROUP BY 1",
        ),
        (
            "Whole month (no date filter)",
            "SELECT cell_sk, COUNT(*), COUNTIF(is_dropped) FROM {t} GROUP BY 1",
        ),
    ]

    cfg = bigquery.QueryJobConfig(use_query_cache=False, maximum_bytes_billed=2 * 1024**3)
    rows = []
    for label, sql in queries:
        optimised = bq.query(sql.format(t=gold), job_config=cfg)
        baseline = bq.query(sql.format(t=flat), job_config=cfg)
        optimised.result()
        baseline.result()
        rows.append((label, baseline.total_bytes_processed, optimised.total_bytes_processed))

    dry = bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
    star = bq.query(f"SELECT * FROM {gold}", job_config=dry).total_bytes_processed
    three = bq.query(
        f"SELECT cdr_id, call_date, charge_amount FROM {gold}", job_config=dry
    ).total_bytes_processed
    rows.append(("SELECT * vs 3 columns (columnar)", star, three))

    if args.markdown:
        print("| Query | Without optimisation | With optimisation | Saving |")
        print("|---|---:|---:|---:|")
    else:
        print(f"\n{'query':34} {'without':>12} {'with':>12} {'saving':>8}")
    for label, without, with_ in rows:
        saving = f"{(1 - with_ / without) * 100:.0f}%" if without else "n/a"
        w, o = f"{without / MB:,.1f} MB", f"{with_ / MB:,.1f} MB"
        if args.markdown:
            print(f"| {label} | {w} | {o} | {saving} |")
        else:
            print(f"{label:34} {w:>12} {o:>12} {saving:>8}")
    print("\n'without' = unpartitioned, unclustered copy (or SELECT *); 'with' = gold.fct_calls")
    print("Note: BigQuery bills at least 10 MB per query, so tiny scans cost the same.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
