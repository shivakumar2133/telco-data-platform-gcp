"""Prove the DQ rules catch every injected defect.

Reads the latest DQ run from ops.dq_failures (as sa-reporting, read-only) and
compares it, record by record, with data_generator/output/defects_manifest.json.

    python -m quality.dq_report              # table in the terminal, exit 1 if anything was missed
    python -m quality.dq_report --markdown   # paste into README / docs

Cost: one query on today's partitions of ops.dq_failures (a few MB).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quality.dq_compare import compare, overall_recall, render

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data_generator" / "output" / "defects_manifest.json"
SIMULATED = ROOT / "data_generator" / "output" / "simulated_changes.json"


def load_detected(client, project: str) -> tuple[str, dict[str, set[str]]]:
    """record_keys per defect_type from the most recent DQ run."""
    sql = f"""
        with latest as (
          select dq_run_id from `{project}.ops.dq_scorecard`
          where dq_run_date >= date_sub(current_date(), interval 7 day)
          order by dq_run_at desc limit 1)
        select dq_run_id, defect_type, array_agg(distinct record_key) as keys
        from `{project}.ops.dq_failures`
        where detected_date >= date_sub(current_date(), interval 7 day)  -- partition pruning
          and dq_run_id = (select dq_run_id from latest)
          and defect_type is not null
        group by 1, 2"""
    run_id, detected = "", {}
    for row in client.query(sql).result():
        run_id = row.dq_run_id
        detected[row.defect_type] = set(row.keys)
    return run_id, detected


def fixed_at_source() -> dict[str, set[str]]:
    """simulate_changes.py fills in emails for 20 customers: if any had a NULL email,
    that defect no longer exists at the source - correctly not flagged any more."""
    if not SIMULATED.exists():
        return {}
    changed = json.loads(SIMULATED.read_text()).get("mssql", {}).get("customers_updated", [])
    return {"crm_null_email": set(changed)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--manifest", type=Path, default=MANIFEST)
    args = p.parse_args(argv)

    from google.cloud import bigquery

    from ingestion.common.config import get_settings
    from ingestion.common.gcp_auth import impersonate

    s = get_settings()
    creds = impersonate(s.sa_email("reporting"))
    client = bigquery.Client(project=s.project_id, location=s.bq_location, credentials=creds)

    manifest = json.loads(args.manifest.read_text())
    run_id, detected = load_detected(client, s.project_id)
    if not run_id:
        print("No DQ run in the last 7 days - run `make dq-build` first.")
        return 1

    results = compare(
        manifest,
        detected,
        rejected_exports=detected.get("alarm_record_count_mismatch", set()),
        fixed_at_source=fixed_at_source(),
    )
    print(f"DQ run {run_id} vs {args.manifest.name}\n")
    print(render(results, markdown=args.markdown))
    missed = [(r.defect_type, r.missed[:5]) for r in results if r.missed or not r.has_rule]
    for defect_type, ids in missed:
        print(f"\nMISSED {defect_type}: {ids}")
    print(f"\nRecall: {overall_recall(results):.2%}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
