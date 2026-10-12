"""Phase 13 verification: Spark and dbt produce the same numbers - and what each cost.

Compares scratch.spark_cell_daily (PySpark on Dataproc Serverless) with dbt's
gold.rpt_network_daily per day and region: counts must match exactly, minutes and GB
within rounding. Then prints the BigQuery cost of the dbt path (from job labels) and the
latest Dataproc batch's resource usage, for the Spark-vs-SQL discussion.

    python -m scripts.compare_spark_dbt
"""

from __future__ import annotations

import json
import subprocess
import sys

from google.cloud import bigquery

from ingestion.common.config import get_settings

COUNTS = ["call_attempts", "voice_calls", "dropped_calls", "failed_calls"]


def main() -> int:
    s = get_settings()
    p = s.project_id
    bq = bigquery.Client(project=p, location=s.bq_location)

    agg = ", ".join(f"sum({c}) as {c}" for c in [*COUNTS, "voice_minutes", "data_gb"])
    sql = f"""
        with spark as (
            select call_date, region, {agg} from `{p}.scratch.spark_cell_daily` group by 1, 2),
        dbt as (
            select call_date, region, {agg} from `{p}.gold.rpt_network_daily` group by 1, 2)
        select coalesce(s.call_date, d.call_date) as call_date,
               coalesce(s.region, d.region) as region,
               {", ".join(f"s.{c} as s_{c}, d.{c} as d_{c}" for c in [*COUNTS, "voice_minutes", "data_gb"])}
        from spark as s full outer join dbt as d
          on s.call_date is not distinct from d.call_date and s.region = d.region"""  # noqa: E501
    rows = list(bq.query(sql).result())

    mismatches = []
    for r in rows:
        for c in COUNTS:
            if r[f"s_{c}"] != r[f"d_{c}"]:
                mismatches.append(
                    f"{r.call_date} {r.region} {c}: spark={r[f's_{c}']} dbt={r[f'd_{c}']}"
                )
        for c, tol in (("voice_minutes", 0.5), ("data_gb", 0.01)):
            a, b = r[f"s_{c}"], r[f"d_{c}"]
            if abs(float(a or 0) - float(b or 0)) > tol or (a is None) != (b is None):
                mismatches.append(f"{r.call_date} {r.region} {c}: spark={a} dbt={b}")

    total = sum(r.s_call_attempts or 0 for r in rows)
    print(f"Compared {len(rows)} day x region groups, {total:,} call attempts.")
    if mismatches:
        print(f"FAIL  {len(mismatches)} differences, first ones:")
        for m in mismatches[:10]:
            print(f"   {m}")
    else:
        print("PASS  Spark and dbt agree on every day and region")
        print("      (counts exact, voice minutes and GB within rounding)")

    print("\nCost of the dbt path (last 7 days, latest run of each model):")
    jobs = f"`region-{s.bq_location.lower()}`.INFORMATION_SCHEMA.JOBS_BY_PROJECT"
    cost_sql = f"""
        select (select value from unnest(labels) where key = 'node_id') as node,
               total_bytes_billed, total_slot_ms, timestamp_diff(end_time, start_time, second) secs
        from {jobs}
        where creation_time >= timestamp_sub(current_timestamp(), interval 7 day)
          and exists (select 1 from unnest(labels) where key = 'node_id'
                      and value in ('model_telco_usage_cdrs', 'model_telco_fct_calls',
                                    'model_telco_mart_cell_daily'))
        qualify row_number() over (partition by node order by creation_time desc) = 1"""
    for r in bq.query(cost_sql).result():
        print(
            f"   {r.node:30} {(r.total_bytes_billed or 0) / 1024**2:8.1f} MiB billed "
            f"{(r.total_slot_ms or 0) / 1000:8.1f} slot-s {r.secs:5}s wall"
        )

    print("\nLatest Dataproc Serverless batch:")
    try:
        out = subprocess.run(
            [
                "gcloud",
                "dataproc",
                "batches",
                "list",
                f"--project={p}",
                f"--region={s.region}",
                "--limit=1",
                "--sort-by=~createTime",
                "--format=json",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        batch = (json.loads(out) or [{}])[0]
        usage = batch.get("runtimeInfo", {}).get("approximateUsage", {})
        dcu_hours = int(usage.get("milliDcuSeconds", 0)) / 1000 / 3600
        name = batch.get("name", "?").split("/")[-1]
        print(f"   {name}  state={batch.get('state')}  {dcu_hours:.3f} DCU-hours")
        print("   Cost ~ DCU-hours x the Dataproc Serverless price per DCU-hour (see ADR 0012).")
    except (subprocess.CalledProcessError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"   (could not read batches: {exc})")

    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
