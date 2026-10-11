"""Simulate a day of business activity in the source databases, so incremental
extraction has something to pick up.

    python -m sources.simulate_changes                 # all three systems
    python -m sources.simulate_changes --only oracle

Changes (all stamped with the current UTC time):
  CRM (SQL Server)      update 20 customers' email/city; add 5 subscriptions
  Billing (Oracle)      30 unpaid invoices get paid: insert payment + update invoice
  Inventory (Postgres)  10 devices change status

Writes data_generator/output/simulated_changes.json with what was changed,
so you can check the next incremental run picked up exactly these rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

from sources.load_sources import env, mssql_url, oracle_url, pg_url

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data_generator" / "output" / "simulated_changes.json"


def mssql_changes() -> dict:
    eng = create_engine(mssql_url("sa", env("MSSQL_SA_PASSWORD"), "crm"))
    with eng.begin() as c:
        ids = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT TOP (20) customer_id FROM dbo.customers WHERE status = 'ACTIVE' "
                    "ORDER BY NEWID()"
                )
            )
        ]
        for cid in ids:
            c.execute(
                text(
                    "UPDATE dbo.customers"
                    " SET email = LOWER(CONCAT(customer_id, '@updated.example.com')),"
                    " city = 'Milton Keynes', updated_at = SYSUTCDATETIME() WHERE customer_id = :id"
                ),
                {"id": cid},
            )
        next_no = (
            c.execute(
                text(
                    "SELECT MAX(CAST(SUBSTRING(subscription_id, 4, 20) AS INT))"
                    " FROM dbo.subscriptions "
                    "WHERE subscription_id LIKE 'SUB%'"
                )
            ).scalar_one()
            + 1
        )
        new_subs = []
        for i, cid in enumerate(ids[:5]):
            sid = f"SUB{next_no + i:07d}"
            c.execute(
                text(
                    "INSERT INTO dbo.subscriptions"
                    " (subscription_id, customer_id, product_id, msisdn,"
                    " start_date, end_date, status, created_at, updated_at) VALUES (:sid, :cid,"
                    " 'MOB-SIM-30GB', :msisdn, CAST(SYSUTCDATETIME() AS DATE), NULL, 'ACTIVE',"
                    " SYSUTCDATETIME(), SYSUTCDATETIME())"
                ),
                {"sid": sid, "cid": cid, "msisdn": f"4479{next_no + i:08d}"},
            )
            new_subs.append(sid)
    return {"customers_updated": ids, "subscriptions_inserted": new_subs}


def oracle_changes() -> dict:
    eng = create_engine(oracle_url("billing", env("BILLING_DB_PASSWORD")))
    with eng.begin() as c:
        rows = c.execute(
            text(
                "SELECT i.invoice_id, i.total_amount, a.payment_method FROM invoices i "
                "JOIN billing_accounts a ON a.account_id = i.account_id "
                "WHERE i.status IN ('ISSUED', 'OVERDUE') ORDER BY i.invoice_id "
                "FETCH FIRST 30 ROWS ONLY"
            )
        ).all()
        next_no = (
            c.execute(
                text("SELECT MAX(TO_NUMBER(SUBSTR(payment_id, 4))) FROM payments")
            ).scalar_one()
            + 1
        )
        payments = []
        for i, (inv_id, amount, method) in enumerate(rows):
            pid = f"PAY{int(next_no) + i:08d}"
            c.execute(
                text(
                    "INSERT INTO payments (payment_id, invoice_id, payment_date, amount,"
                    " payment_method, created_at) VALUES (:pid, :inv, TRUNC(SYSDATE), :amt, :m,"
                    " CAST(SYS_EXTRACT_UTC(SYSTIMESTAMP) AS TIMESTAMP(0)))"
                ),
                {"pid": pid, "inv": inv_id, "amt": amount, "m": method},
            )
            c.execute(
                text(
                    "UPDATE invoices SET status = 'PAID',"
                    " updated_at = CAST(SYS_EXTRACT_UTC(SYSTIMESTAMP) AS TIMESTAMP(0))"
                    " WHERE invoice_id = :inv"
                ),
                {"inv": inv_id},
            )
            payments.append(pid)
        lines = (
            c.execute(
                text(
                    "SELECT COUNT(*) FROM invoice_lines WHERE invoice_id IN ("
                    + ",".join(f"'{r[0]}'" for r in rows)
                    + ")"
                )
            ).scalar_one()
            if rows
            else 0
        )
    return {
        "invoices_paid": [r[0] for r in rows],
        "payments_inserted": payments,
        "invoice_lines_of_changed_invoices": int(lines),
    }


def postgres_changes() -> dict:
    eng = create_engine(pg_url("network_admin", env("POSTGRES_PASSWORD"), "network"))
    with eng.begin() as c:
        ids = [
            r[0]
            for r in c.execute(
                text(
                    "SELECT device_id FROM devices WHERE status = 'IN_SERVICE'"
                    " ORDER BY random() LIMIT 10"
                )
            )
        ]
        c.execute(
            text(
                "UPDATE devices SET status = 'MAINTENANCE', updated_at = now() AT TIME ZONE 'utc' "
                "WHERE device_id = ANY(:ids)"
            ),
            {"ids": ids},
        )
    return {"devices_updated": ids}


CHANGES = {"mssql": mssql_changes, "oracle": oracle_changes, "postgres": postgres_changes}


def main() -> int:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser()
    p.add_argument("--only", default="postgres,mssql,oracle")
    args = p.parse_args()

    report = {"changed_at": datetime.now(UTC).isoformat(timespec="seconds")}
    for system in [s.strip() for s in args.only.split(",") if s.strip()]:
        report[system] = CHANGES[system]()
        summary = {k: (len(v) if isinstance(v, list) else v) for k, v in report[system].items()}
        print(f"[{system}] {summary}")
    OUT.write_text(json.dumps(report, indent=2))
    print("\nExpected on the next incremental run (make ingest-db):")
    if "mssql" in report:
        print(f"  mssql.customers      {len(report['mssql']['customers_updated'])}")
        print(f"  mssql.subscriptions  {len(report['mssql']['subscriptions_inserted'])}")
    if "oracle" in report:
        o = report["oracle"]
        print(f"  oracle.invoices      {len(o['invoices_paid'])}")
        print(f"  oracle.invoice_lines {o['invoice_lines_of_changed_invoices']}")
        print(f"  oracle.payments      {len(o['payments_inserted'])}")
    if "postgres" in report:
        print(f"  postgres.devices     {len(report['postgres']['devices_updated'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
