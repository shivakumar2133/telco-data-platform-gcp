"""Phase 3 verification: Bronze is complete and reconciles with every source.

  - every database table: COUNT(DISTINCT primary key) in Bronze == COUNT(*) in source
    (updates arrive as extra versions, so we compare distinct keys, not rows)
  - CDR files: Bronze rows == rows in the generated files; all 30 files loaded
  - the alarm export with a bad control total was REJECTED (and is the one we injected)
  - tickets: distinct ticket_id in Bronze == tickets served by the API
  - no FAILED loads in the audit trail; a watermark exists for each incremental object

Runs as you (project owner). Queries scan a few MB of Bronze - well inside the free tier.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from google.cloud import bigquery
from sqlalchemy import text

from ingestion.common.config import get_settings
from ingestion.extractors.db_extractor import engine_for, load_catalog

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_generator" / "output"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def main() -> int:
    s = get_settings()
    bq = bigquery.Client(project=s.project_id, location=s.bq_location)

    def scalar(sql: str):
        return next(iter(bq.query(sql).result()))[0]

    def bronze(table: str) -> str:
        return f"`{s.project_id}.bronze.{table}`"

    # ---- databases
    cfg, specs = load_catalog()
    engines = {}
    for spec in specs:
        name = f"{spec.system}.{spec.name}"
        try:
            if spec.system not in engines:
                engines[spec.system] = engine_for(spec.system, cfg, sa_email="")
            with engines[spec.system].connect() as conn:
                src = conn.execute(text(f"SELECT COUNT(*) FROM {spec.qualified}")).scalar_one()
            pk = ", ".join(spec.primary_key)
            tgt = scalar(f"SELECT COUNT(DISTINCT {pk}) FROM {bronze(spec.bronze_table)}")
            rows = scalar(f"SELECT COUNT(*) FROM {bronze(spec.bronze_table)}")
            check(
                f"{name} keys reconcile",
                src == tgt,
                f"source={src:,} bronze distinct={tgt:,} (bronze rows incl. versions={rows:,})",
            )
        except Exception as exc:  # noqa: BLE001
            check(f"{name} keys reconcile", False, str(exc).splitlines()[0][:110])

    # ---- files
    summary = json.loads((OUT / "generation_summary.json").read_text())["row_counts"]
    manifest = json.loads((OUT / "defects_manifest.json").read_text())
    try:
        rows, files = next(
            iter(
                bq.query(
                    f"SELECT COUNT(*), COUNT(DISTINCT _source_file) FROM {bronze('files__cdr')}"
                ).result()
            )
        )
        check(
            "CDR files all loaded",
            files == summary["files.cdr_files"],
            f"{files} of {summary['files.cdr_files']} files",
        )
        check(
            "CDR rows reconcile with files",
            rows == summary["files.cdr_rows"],
            f"bronze={rows:,} files={summary['files.cdr_rows']:,}",
        )
    except Exception as exc:  # noqa: BLE001
        check("CDR files", False, str(exc).splitlines()[0][:110])

    rejected = {
        r.object_name
        for r in bq.query(
            f"SELECT DISTINCT object_name FROM `{s.project_id}.ops.load_audit` "
            "WHERE source_system = 'files' AND status = 'REJECTED'"
        ).result()
    }
    bad_export = manifest["alarm_record_count_mismatch"]["ids"][0]  # NMS-EXPORT-YYYYMMDD
    expected_file = f"alarms/alarms_{bad_export.rsplit('-', 1)[-1]}.json"
    check(
        "bad alarm export quarantined",
        expected_file in rejected,
        f"rejected={sorted(rejected) or 'none'}, injected={expected_file}",
    )

    try:
        n_alarm_files = scalar(
            f"SELECT COUNT(DISTINCT _source_file) FROM {bronze('files__alarms')}"
        )
        check(
            "alarm files loaded (all but the bad one)",
            n_alarm_files == summary["files.alarm_files"] - 1,
            f"{n_alarm_files} of {summary['files.alarm_files']}",
        )
        sla = scalar(f"SELECT COUNT(DISTINCT _source_file) FROM {bronze('files__sla_targets')}")
        check("SLA workbook loaded", sla >= 1, f"{sla} file(s)")
    except Exception as exc:  # noqa: BLE001
        check("alarm / SLA files", False, str(exc).splitlines()[0][:110])

    # ---- API
    try:
        expected = len(json.loads((OUT / "api" / "tickets.json").read_text()))
        got = scalar(f"SELECT COUNT(DISTINCT ticket_id) FROM {bronze('api__tickets')}")
        check("tickets reconcile with API", got == expected, f"bronze={got:,} api={expected:,}")
    except Exception as exc:  # noqa: BLE001
        check("tickets reconcile with API", False, str(exc).splitlines()[0][:110])

    # ---- audit + watermarks
    failed = scalar(
        f"SELECT COUNT(*) FROM `{s.project_id}.ops.load_audit` "
        "WHERE status = 'FAILED' AND started_at > TIMESTAMP_SUB(CURRENT_TIMESTAMP(), "
        "INTERVAL 1 DAY)"
    )
    check("no FAILED loads in last 24h", failed == 0, f"{failed} failed")
    wm = {
        (r.source_system, r.object_name)
        for r in bq.query(
            f"SELECT DISTINCT source_system, object_name FROM `{s.project_id}.ops.watermarks`"
        ).result()
    }
    needed = {(sp.system, sp.name) for sp in specs if sp.mode != "full"} | {("api", "tickets")}
    missing = sorted(f"{a}.{b}" for a, b in needed - wm)
    check(
        "watermark stored for every incremental object",
        not missing,
        f"missing: {missing}" if missing else f"{len(needed)} objects",
    )

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    n_failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - n_failed}/{len(results)} checks passed")
    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
