"""Phase 1 verification: every source is reachable, complete and read-only for the pipeline.

Checks
  1. Generated files exist (CDR CSVs, alarm JSONs, SLA XLSX, tickets JSON)
  2. Each database, queried as etl_reader, has the same row counts as the
     control totals recorded at load time (a first reconciliation)
  3. etl_reader cannot write (least privilege)
  4. The tickets API rejects missing keys, paginates, and returns every ticket
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv
from sqlalchemy import create_engine

from sources.load_sources import TABLES, mssql_url, oracle_url, pg_url

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_generator" / "output"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))


def check_files() -> None:
    cdr = sorted((OUT / "files" / "cdr").glob("cdr_*.csv"))
    alarms = sorted((OUT / "files" / "alarms").glob("alarms_*.json"))
    check("CDR files", len(cdr) > 0, f"{len(cdr)} files")
    check("Alarm export files", len(alarms) > 0, f"{len(alarms)} files")
    check("SLA workbook", (OUT / "files" / "sla" / "sla_targets.xlsx").exists())
    check("Defect manifest", (OUT / "defects_manifest.json").exists())


def check_db(system: str, engine, qualify, write_sql: str, totals: dict) -> None:
    try:
        with engine.connect() as conn:
            for table in TABLES[system]:
                n = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {qualify(table)}").scalar_one()
                expected = totals.get(system, {}).get(table, {}).get("rows")
                check(f"{system}.{table} row count", n == expected, f"db={n:,} expected={expected}")
        try:
            with engine.begin() as conn:
                conn.exec_driver_sql(write_sql)
            check(f"{system} etl_reader is read-only", False, "write succeeded!")
        except Exception:  # noqa: BLE001 - a permission error is the expected outcome
            check(f"{system} etl_reader is read-only", True, "write rejected")
    except Exception as exc:  # noqa: BLE001
        check(f"{system} reachable as etl_reader", False, str(exc).splitlines()[0][:120])


def check_api() -> None:
    base = os.getenv("TICKETS_API_URL", "http://localhost:8000")
    key = os.getenv("TICKETS_API_KEY", "")
    expected = len(json.loads((OUT / "api" / "tickets.json").read_text()))
    try:
        r = httpx.get(f"{base}/api/v1/tickets", timeout=10)
        check("API rejects missing key", r.status_code == 401, f"HTTP {r.status_code}")

        fetched, page, pages = 0, 1, 0
        while page:
            r = httpx.get(
                f"{base}/api/v1/tickets",
                headers={"X-API-Key": key},
                params={"page": page, "page_size": 200},
                timeout=10,
            )
            r.raise_for_status()
            body = r.json()
            fetched += len(body["data"])
            page, pages = body["next_page"], pages + 1
        check(
            "API returns all tickets",
            fetched == expected,
            f"{fetched:,} in {pages} pages, expected {expected:,}",
        )

        r = httpx.get(
            f"{base}/api/v1/tickets",
            headers={"X-API-Key": key},
            params={"updated_since": "2026-09-30T00:00:00Z"},
            timeout=10,
        )
        check(
            "API incremental filter",
            0 < r.json()["total"] < expected,
            f"{r.json()['total']} tickets updated since 2026-09-30",
        )
    except httpx.HTTPError as exc:
        check("API reachable", False, str(exc))


def main() -> int:
    load_dotenv(ROOT / ".env")
    reader_pw = os.getenv("ETL_READER_PASSWORD", "")
    totals_path = OUT / "source_control_totals.json"
    totals = json.loads(totals_path.read_text()) if totals_path.exists() else {}

    check_files()
    check_db(
        "postgres",
        create_engine(pg_url("etl_reader", reader_pw, "network")),
        lambda t: f"public.{t}",
        "UPDATE public.sites SET site_name = site_name WHERE 1 = 0",
        totals,
    )
    check_db(
        "mssql",
        create_engine(mssql_url("etl_reader", reader_pw, "crm")),
        lambda t: f"dbo.{t}",
        "UPDATE dbo.products SET product_name = product_name WHERE 1 = 0",
        totals,
    )
    check_db(
        "oracle",
        create_engine(oracle_url("etl_reader", reader_pw)),
        lambda t: f"billing.{t}",
        "UPDATE billing.invoices SET status = status WHERE 1 = 0",
        totals,
    )
    check_api()

    width = max(len(n) for n, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
