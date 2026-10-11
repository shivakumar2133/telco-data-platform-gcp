"""Generate all synthetic telecom source data.

Usage:
    python -m data_generator.generate                 # full size (~1-2 min)
    python -m data_generator.generate --scale 0.1     # quick run

Output (gitignored) in data_generator/output/:
    db/mssql/*.csv      -> loaded into SQL Server (CRM)
    db/oracle/*.csv     -> loaded into Oracle (billing)
    db/postgres/*.csv   -> loaded into PostgreSQL (network inventory)
    files/cdr/cdr_YYYYMMDD.csv          (mediation CDR files)
    files/alarms/alarms_YYYYMMDD.json   (NMS alarm exports, nested)
    files/sla/sla_targets.xlsx          (business-owned SLA workbook)
    api/tickets.json                    (served by the mock REST API)
    defects_manifest.json               (every defect injected, for Phase 7)
    generation_summary.json             (row counts, seed, scale)
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from faker import Faker

from data_generator.config import GenConfig
from data_generator.defects import DefectLog
from data_generator.generators.alarms_tickets import make_alarms, make_tickets
from data_generator.generators.billing import make_billing
from data_generator.generators.cdrs import apply_cdr_defects, make_cdrs
from data_generator.generators.crm import (
    MsisdnPool,
    apply_customer_defects,
    make_customers,
    make_products,
    make_subscriptions,
)
from data_generator.generators.network import make_network
from data_generator.generators.sla import write_sla_workbook

DEFAULT_OUT = Path(__file__).resolve().parent / "output"


def _csv(df: pd.DataFrame, path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return len(df)


def generate(cfg: GenConfig, out_dir: Path = DEFAULT_OUT) -> dict:
    out_dir = Path(out_dir)
    for sub in ("db", "files", "api"):
        shutil.rmtree(out_dir / sub, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    rng = np.random.default_rng(cfg.seed)
    fake = Faker("en_GB")
    fake.seed_instance(cfg.seed)
    log = DefectLog()
    pool = MsisdnPool(rng, cfg.n_customers * 8)

    # CRM
    products = make_products()
    customers = make_customers(cfg, rng, fake, pool)
    subs = make_subscriptions(cfg, rng, customers, products, pool, log)

    # Network inventory
    sites, cells, devices = make_network(cfg, rng, fake)

    # CDRs -> rated usage -> billing
    clean_cdrs, rated = make_cdrs(cfg, rng, subs, products, cells)
    billing = make_billing(cfg, rng, customers, subs, products, rated, log)
    cdr_files = apply_cdr_defects(clean_cdrs, rng, log)

    # Alarms -> tickets
    alarm_files, clean_alarms = make_alarms(cfg, rng, devices, log)
    tickets = make_tickets(cfg, rng, customers, subs, products, sites, clean_alarms, log)

    customers_out = apply_customer_defects(cfg, customers, rng, log)

    counts: dict[str, int] = {}
    db = out_dir / "db"
    counts["mssql.customers"] = _csv(customers_out, db / "mssql" / "customers.csv")
    counts["mssql.products"] = _csv(products, db / "mssql" / "products.csv")
    counts["mssql.subscriptions"] = _csv(subs, db / "mssql" / "subscriptions.csv")
    for name, df in billing.items():
        counts[f"oracle.{name}"] = _csv(df, db / "oracle" / f"{name}.csv")
    counts["postgres.sites"] = _csv(sites, db / "postgres" / "sites.csv")
    counts["postgres.cells"] = _csv(cells, db / "postgres" / "cells.csv")
    counts["postgres.devices"] = _csv(devices, db / "postgres" / "devices.csv")

    n_cdr = 0
    for day, df in cdr_files.items():
        n_cdr += _csv(df, out_dir / "files" / "cdr" / f"cdr_{day:%Y%m%d}.csv")
    counts["files.cdr_rows"] = n_cdr
    counts["files.cdr_files"] = len(cdr_files)

    alarm_dir = out_dir / "files" / "alarms"
    alarm_dir.mkdir(parents=True, exist_ok=True)
    n_alarm = 0
    for day, export in alarm_files.items():
        (alarm_dir / f"alarms_{day:%Y%m%d}.json").write_text(json.dumps(export, indent=2))
        n_alarm += len(export["alarms"])
    counts["files.alarm_records"] = n_alarm
    counts["files.alarm_files"] = len(alarm_files)

    counts["files.sla_rows"] = write_sla_workbook(
        out_dir / "files" / "sla" / "sla_targets.xlsx", log
    )

    api_dir = out_dir / "api"
    api_dir.mkdir(parents=True, exist_ok=True)
    (api_dir / "tickets.json").write_text(json.dumps(tickets, indent=1))
    counts["api.tickets"] = len(tickets)

    log.write(out_dir / "defects_manifest.json")
    summary = {
        "config": {k: str(v) for k, v in asdict(cfg).items()},
        "row_counts": counts,
        "defect_counts": {k: v["count"] for k, v in log.to_dict().items()},
    }
    (out_dir / "generation_summary.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic telecom source data")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--days", type=int, default=30, help="Number of CDR/alarm days")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    t0 = time.time()
    summary = generate(GenConfig(seed=args.seed, scale=args.scale, cdr_days=args.days), args.out)
    print(f"Generated in {time.time() - t0:,.1f}s -> {args.out}\n")
    print(f"{'dataset':32} {'rows':>12}")
    for k, v in summary["row_counts"].items():
        print(f"{k:32} {v:>12,}")
    print(f"\n{'injected defect':32} {'count':>12}")
    for k, v in summary["defect_counts"].items():
        print(f"{k:32} {v:>12,}")


if __name__ == "__main__":
    main()
