"""Ingestion command line. Airflow (Phase 4) calls these same commands.

    python -m ingestion.run db  --system all            # incremental from all 3 databases
    python -m ingestion.run db  --system oracle --full  # force a full reload
    python -m ingestion.run api                         # tickets API
    python -m ingestion.run drop-files                  # simulate files arriving
    python -m ingestion.run files                       # process landing/ -> Bronze
    python -m ingestion.run all                         # db + api + files

Add --local DIR to run with no cloud at all (lake + metadata on disk).
Exit code 1 if any object FAILED (REJECTED files are expected, not failures).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from ingestion.common.context import build_context
from ingestion.common.metadata import AuditRecord

ROOT = Path(__file__).resolve().parents[1]
FILES_DIR = ROOT / "data_generator" / "output" / "files"
SYSTEMS = ["postgres", "mssql", "oracle"]


def print_summary(results: list[AuditRecord]) -> None:
    if not results:
        print("Nothing to do.")
        return
    print(f"\n{'status':9} {'source':9} {'object':34} {'type':12} {'source':>9} {'loaded':>9}")
    for r in results:
        print(
            f"{r.status:9} {r.source_system:9} {r.object_name[:34]:34} {r.load_type:12} "
            f"{'' if r.source_row_count is None else r.source_row_count:>9} "
            f"{'' if r.loaded_row_count is None else r.loaded_row_count:>9}"
            + (f"  <- {r.error_message[:90]}" if r.error_message else "")
        )
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    print("\n" + ", ".join(f"{k}: {v}" for k, v in sorted(counts.items())))


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser(description="Ingest sources into Bronze")
    p.add_argument(
        "--local",
        type=Path,
        default=None,
        help="Run offline: write lake + metadata under this folder",
    )
    sub = p.add_subparsers(dest="command", required=True)

    db = sub.add_parser("db", help="Extract database tables")
    db.add_argument("--system", default="all", choices=["all", *SYSTEMS])
    db.add_argument("--object", default=None, help="One table only, e.g. invoices")
    db.add_argument("--full", action="store_true", help="Ignore watermarks, reload everything")

    api = sub.add_parser("api", help="Extract tickets from the REST API")
    api.add_argument("--full", action="store_true")

    sub.add_parser("files", help="Process files waiting in landing/")

    drop = sub.add_parser("drop-files", help="Copy generated files into landing/")
    drop.add_argument("--from", dest="date_from", default=None, help="YYYY-MM-DD")
    drop.add_argument("--to", dest="date_to", default=None, help="YYYY-MM-DD")

    sub.add_parser("all", help="db + api + files")
    args = p.parse_args(argv)

    ctx = build_context(args.local)
    print(f"run_id={ctx.run_id}  lake={ctx.lake.uri('')}  acting as={ctx.ingest_sa or 'you'}")

    from ingestion.extractors.api_extractor import run_api
    from ingestion.extractors.db_extractor import run_db
    from ingestion.extractors.file_processor import drop_files, process_landing

    results: list[AuditRecord] = []
    if args.command == "db":
        systems = SYSTEMS if args.system == "all" else [args.system]
        results = run_db(ctx, systems, args.object, args.full)
    elif args.command == "api":
        results = run_api(ctx, args.full)
    elif args.command == "files":
        results = process_landing(ctx)
    elif args.command == "drop-files":
        n = drop_files(ctx.lake, FILES_DIR, args.date_from, args.date_to)
        print(f"Dropped {n} files into {ctx.lake.uri('landing/')}")
        return 0
    elif args.command == "all":
        results = run_db(ctx, SYSTEMS) + run_api(ctx) + process_landing(ctx)

    print_summary(results)
    return 1 if any(r.status == "FAILED" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
