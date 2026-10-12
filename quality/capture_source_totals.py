"""Capture control totals from the source databases into ops.source_control_totals.

The "expected" side of reconciliation must come from the SOURCE, not from our own
pipeline - otherwise we'd be checking our work against itself. Right after
extraction this reads COUNT(*) (and SUM of the money column) per table, as
sa-ingest with the read-only etl_reader account.

    python -m quality.capture_source_totals                  # -> BigQuery ops table
    python -m quality.capture_source_totals --local local_run # -> local_run/meta/*.jsonl
    python -m quality.capture_source_totals --system oracle

Oracle analogy: the control-total query you'd run at the source (or a flashback
AS OF SCN query for a perfectly consistent snapshot) before signing off a load.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine, text

from ingestion.common.context import RunContext, build_context, new_run_id
from ingestion.common.log import get_logger
from ingestion.extractors.db_extractor import ObjectSpec, engine_for, load_catalog

log = get_logger(__name__)

# Tables that carry money: these sums are reconciled to the penny in Silver
AMOUNT_COLUMNS = {
    ("oracle", "invoices"): "total_amount",
    ("oracle", "invoice_lines"): "amount",
    ("oracle", "payments"): "amount",
}


def totals_query(spec: ObjectSpec, amount_column: str | None) -> str:
    amount = f"SUM({amount_column})" if amount_column else "NULL"
    return f"SELECT COUNT(*) AS row_count, {amount} AS sum_amount FROM {spec.qualified}"


def capture_system(engine: Engine, specs: list[ObjectSpec], run_id: str) -> list[dict]:
    rows = []
    with engine.connect() as conn:
        for spec in specs:
            amount_column = AMOUNT_COLUMNS.get((spec.system, spec.name))
            count, total = conn.execute(text(totals_query(spec, amount_column))).one()
            rows.append(
                {
                    "run_id": run_id,
                    "source_system": spec.system,
                    "object_name": spec.name,
                    "row_count": int(count),
                    "amount_column": amount_column,
                    # str keeps the exact decimal (NUMERIC in BigQuery, no float rounding)
                    "sum_amount": None if total is None else str(total),
                    "captured_at": datetime.now(UTC).isoformat(),
                }
            )
            log.info(
                "control totals captured",
                extra={"fields": {"object": spec.qualified, "rows": count, "sum": total}},
            )
    return rows


def capture(ctx: RunContext, systems: list[str]) -> list[dict]:
    cfg, specs = load_catalog()
    run_id = new_run_id()
    rows: list[dict] = []
    for system in systems:
        engine = engine_for(system, cfg, ctx.ingest_sa)
        try:
            rows += capture_system(engine, [s for s in specs if s.system == system], run_id)
        finally:
            engine.dispose()
    ctx.meta.append_rows("source_control_totals", rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--local", type=Path, help="write to this folder instead of BigQuery")
    p.add_argument("--system", choices=["postgres", "mssql", "oracle"], action="append")
    args = p.parse_args(argv)

    ctx = build_context(args.local)
    rows = capture(ctx, args.system or ["postgres", "mssql", "oracle"])
    print(f"captured control totals for {len(rows)} source tables")
    return 0


if __name__ == "__main__":
    sys.exit(main())
