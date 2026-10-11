"""Create the three source databases' schemas and load the generated seed data.

Run after `make generate` and `make sources-up`:
    python -m sources.load_sources                  # all three
    python -m sources.load_sources --only postgres  # just one

For each system it:
  1. waits until the database accepts connections
  2. creates the schema owner / database (idempotent)
  3. runs ddl.sql (drop + create tables)
  4. bulk-loads the CSVs
  5. creates a READ-ONLY `etl_reader` login - the pipeline extracts with this,
     never with the owner account (least privilege)
  6. records control totals (row counts, amount sums) for later reconciliation
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import String, create_engine
from sqlalchemy.engine import URL, Engine

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "sources"
OUTPUT = ROOT / "data_generator" / "output"
SEED = OUTPUT / "db"

DATE_COL = re.compile(r"(_date|_at|^date_of_birth|^period_start|^period_end)$")
TEXT_COL = re.compile(r"(msisdn|postcode|serial)")
AMOUNT_COLS = {"invoices": "total_amount", "invoice_lines": "amount", "payments": "amount"}

# Load order matters for foreign keys (parents first)
TABLES = {
    "postgres": ["sites", "cells", "devices"],
    "mssql": ["products", "customers", "subscriptions"],
    "oracle": ["billing_accounts", "invoices", "invoice_lines", "payments"],
}


# ---------------------------------------------------------------- helpers
def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"{name} is not set. Add it to .env (see .env.example).")
    return value


def oracle_url(user: str, password: str) -> URL:
    return URL.create(
        "oracle+oracledb",
        username=user,
        password=password,
        host=env("ORACLE_HOST", "localhost"),
        port=int(env("ORACLE_PORT", "1521")),
        query={"service_name": env("ORACLE_SERVICE", "FREEPDB1")},
    )


def mssql_url(user: str, password: str, database: str) -> URL:
    return URL.create(
        "mssql+pymssql",
        username=user,
        password=password,
        host=env("MSSQL_HOST", "localhost"),
        port=int(env("MSSQL_PORT", "1433")),
        database=database,
    )


def pg_url(user: str, password: str, database: str) -> URL:
    return URL.create(
        "postgresql+psycopg",
        username=user,
        password=password,
        host=env("POSTGRES_HOST", "localhost"),
        port=int(env("POSTGRES_PORT", "5432")),
        database=database,
    )


def wait_for(engine: Engine, name: str, probe: str, timeout_s: int = 600) -> None:
    """Retry until the DB answers. Oracle needs 1-3 minutes on first start."""
    start = time.time()
    while True:
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql(probe)
            print(f"[{name}] connected")
            return
        except Exception as exc:  # noqa: BLE001 - any connection error means "not ready yet"
            waited = int(time.time() - start)
            if waited > timeout_s:
                raise RuntimeError(f"[{name}] not reachable after {timeout_s}s: {exc}") from exc
            print(f"[{name}] not ready yet ({waited}s) - retrying in 10s ...")
            time.sleep(10)


def split_sql(sql: str) -> list[str]:
    """Strip -- comments and split on ';' (our DDL has no ';' inside strings)."""
    no_comments = "\n".join(re.sub(r"--.*$", "", line) for line in sql.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


def run_sql_file(engine: Engine, path: Path) -> None:
    with engine.begin() as conn:
        for stmt in split_sql(path.read_text()):
            conn.exec_driver_sql(stmt)


def read_seed(path: Path) -> pd.DataFrame:
    header = pd.read_csv(path, nrows=0).columns
    df = pd.read_csv(
        path,
        dtype={c: str for c in header if TEXT_COL.search(c)},
        keep_default_na=False,  # keep defects like 'N/A' as text...
        na_values=[""],  # ...only empty cells are NULL
    )
    for col in df.columns:
        if DATE_COL.search(col):
            df[col] = pd.to_datetime(df[col])
    return df


def load_table(
    engine: Engine, table: str, csv_path: Path, schema: str | None = None
) -> pd.DataFrame:
    df = read_seed(csv_path)
    # Bind text columns as VARCHAR (pandas would otherwise send CLOB to Oracle)
    text_types = {
        c: String(255) for c in df.columns if df[c].dtype == object or str(df[c].dtype) == "str"
    }
    df.to_sql(
        table,
        engine,
        schema=schema,
        if_exists="append",
        index=False,
        chunksize=5000,
        dtype=text_types,
    )
    return df


def control_totals(engine: Engine, system: str, qualify: Callable[[str], str]) -> dict:
    totals: dict[str, dict] = {}
    with engine.connect() as conn:
        for table in TABLES[system]:
            rows = conn.exec_driver_sql(f"SELECT COUNT(*) FROM {qualify(table)}").scalar_one()
            entry: dict = {"rows": int(rows)}
            if table in AMOUNT_COLS:
                total = conn.exec_driver_sql(
                    f"SELECT SUM({AMOUNT_COLS[table]}) FROM {qualify(table)}"
                ).scalar_one()
                entry["sum_amount"] = round(float(total or 0), 2)
            totals[table] = entry
    return totals


def load_and_check(engine: Engine, system: str, schema: str | None = None) -> dict[str, int]:
    loaded = {}
    for table in TABLES[system]:
        t0 = time.time()
        df = load_table(engine, table, SEED / system / f"{table}.csv", schema)
        loaded[table] = len(df)
        print(f"[{system}] loaded {table:<18} {len(df):>8,} rows in {time.time() - t0:5.1f}s")
    return loaded


# ---------------------------------------------------------------- systems
def setup_postgres() -> dict:
    pw = env("POSTGRES_PASSWORD")
    reader_pw = env("ETL_READER_PASSWORD")
    eng = create_engine(pg_url("network_admin", pw, "network"))
    wait_for(eng, "postgres", "SELECT 1")

    run_sql_file(eng, SOURCES / "postgres" / "ddl.sql")
    load_and_check(eng, "postgres")

    with eng.begin() as conn:
        conn.exec_driver_sql(
            "DO $$ BEGIN "
            "IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_reader') THEN "
            f"CREATE ROLE etl_reader LOGIN PASSWORD '{reader_pw}'; END IF; END $$"
        )
        conn.exec_driver_sql("GRANT CONNECT ON DATABASE network TO etl_reader")
        conn.exec_driver_sql("GRANT USAGE ON SCHEMA public TO etl_reader")
        conn.exec_driver_sql("GRANT SELECT ON ALL TABLES IN SCHEMA public TO etl_reader")
    print("[postgres] etl_reader granted SELECT")
    return control_totals(eng, "postgres", lambda t: f"public.{t}")


def setup_mssql() -> dict:
    sa_pw = env("MSSQL_SA_PASSWORD")
    reader_pw = env("ETL_READER_PASSWORD")
    master = create_engine(mssql_url("sa", sa_pw, "master"), isolation_level="AUTOCOMMIT")
    wait_for(master, "mssql", "SELECT 1")
    with master.connect() as conn:
        conn.exec_driver_sql("IF DB_ID('crm') IS NULL CREATE DATABASE crm")
        conn.exec_driver_sql(
            "IF SUSER_ID('etl_reader') IS NULL "
            f"CREATE LOGIN etl_reader WITH PASSWORD = '{reader_pw}', CHECK_POLICY = OFF"
        )

    eng = create_engine(mssql_url("sa", sa_pw, "crm"))
    run_sql_file(eng, SOURCES / "mssql" / "ddl.sql")
    load_and_check(eng, "mssql", schema="dbo")

    with eng.begin() as conn:
        conn.exec_driver_sql(
            "IF USER_ID('etl_reader') IS NULL CREATE USER etl_reader FOR LOGIN etl_reader"
        )
        conn.exec_driver_sql("ALTER ROLE db_datareader ADD MEMBER etl_reader")
    print("[mssql] etl_reader added to db_datareader")
    return control_totals(eng, "mssql", lambda t: f"dbo.{t}")


def setup_oracle() -> dict:
    system_pw = env("ORACLE_PASSWORD")
    billing_pw = env("BILLING_DB_PASSWORD")
    reader_pw = env("ETL_READER_PASSWORD")

    admin = create_engine(oracle_url("system", system_pw))
    wait_for(admin, "oracle", "SELECT 1 FROM dual")
    with admin.begin() as conn:
        conn.exec_driver_sql(
            f'CREATE USER IF NOT EXISTS billing IDENTIFIED BY "{billing_pw}" '
            "DEFAULT TABLESPACE users QUOTA UNLIMITED ON users"
        )
        conn.exec_driver_sql("GRANT CREATE SESSION, CREATE TABLE, CREATE VIEW TO billing")
        conn.exec_driver_sql(f'CREATE USER IF NOT EXISTS etl_reader IDENTIFIED BY "{reader_pw}"')
        conn.exec_driver_sql("GRANT CREATE SESSION TO etl_reader")

    eng = create_engine(oracle_url("billing", billing_pw))
    run_sql_file(eng, SOURCES / "oracle" / "ddl.sql")
    load_and_check(eng, "oracle")

    with eng.begin() as conn:
        for table in TABLES["oracle"]:
            conn.exec_driver_sql(f"GRANT SELECT ON billing.{table} TO etl_reader")
    print("[oracle] etl_reader granted SELECT on billing tables")
    return control_totals(eng, "oracle", lambda t: f"billing.{t}")


SETUP = {"postgres": setup_postgres, "mssql": setup_mssql, "oracle": setup_oracle}


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description="Load seed data into local source databases")
    parser.add_argument(
        "--only",
        default="postgres,mssql,oracle",
        help="Comma-separated subset: postgres,mssql,oracle",
    )
    args = parser.parse_args()

    if not SEED.exists():
        print("No seed data found. Run `make generate` first.")
        return 1

    totals_path = OUTPUT / "source_control_totals.json"
    totals = json.loads(totals_path.read_text()) if totals_path.exists() else {}

    for system in [s.strip() for s in args.only.split(",") if s.strip()]:
        print(f"\n=== {system} ===")
        totals[system] = SETUP[system]()
        expected = {t: len(read_seed(SEED / system / f"{t}.csv")) for t in TABLES[system]}
        for table, entry in totals[system].items():
            ok = "OK " if entry["rows"] == expected[table] else "MISMATCH"
            print(f"[{system}] {ok} {table:<18} csv={expected[table]:>8,} db={entry['rows']:>8,}")

    totals_path.write_text(json.dumps(totals, indent=2))
    print(f"\nControl totals written to {totals_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
