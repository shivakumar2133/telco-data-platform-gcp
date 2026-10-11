"""Network inventory (lands in PostgreSQL): sites, cells, devices."""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

from data_generator.config import GenConfig
from data_generator.generators.crm import REGION_WEIGHTS, REGIONS

SITE_TYPES = ["MACRO", "SMALL_CELL", "EXCHANGE"]
DEVICE_PLAN = {
    "MACRO": [("BASEBAND", "Ericsson", "Baseband 6630"), ("ROUTER", "Cisco", "ASR 920")],
    "SMALL_CELL": [("RADIO_UNIT", "Nokia", "AirScale Micro RRH")],
    "EXCHANGE": [
        ("OLT", "Nokia", "Lightspan MF-14"),
        ("SWITCH", "Juniper", "EX4650"),
        ("ROUTER", "Cisco", "NCS 5500"),
    ],
}


def _random_dates(rng, n: int, start: str, end: str) -> pd.DatetimeIndex:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return s + pd.to_timedelta(rng.integers(0, (e - s).days, n), unit="D")


def make_network(
    cfg: GenConfig, rng: np.random.Generator, fake: Faker
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    n = cfg.n_sites
    types = rng.choice(SITE_TYPES, n, p=[0.60, 0.25, 0.15])
    regions = rng.choice(REGIONS, n, p=REGION_WEIGHTS)
    built = _random_dates(rng, n, "2012-01-01", "2026-06-30")

    sites, cells, devices = [], [], []
    cell_seq = dev_seq = 0
    for i in range(n):
        site_id = f"SITE{i + 1:05d}"
        stype = str(types[i])
        sites.append(
            {
                "site_id": site_id,
                "site_name": f"{fake.city()} {stype.replace('_', ' ').title()} {i + 1}",
                "site_type": stype,
                "region": regions[i],
                "postcode": fake.postcode(),
                "latitude": round(float(rng.uniform(50.1, 58.5)), 5),
                "longitude": round(float(rng.uniform(-5.5, 1.7)), 5),
                "created_at": built[i] + pd.Timedelta(hours=9),
                "updated_at": built[i] + pd.Timedelta(days=int(rng.integers(0, 300)), hours=9),
            }
        )

        if stype == "MACRO":
            techs = ["4G"] + (["5G"] if rng.random() < 0.5 else [])
            plan = [(t, s) for t in techs for s in (1, 2, 3)]
        elif stype == "SMALL_CELL":
            plan = [(str(rng.choice(["4G", "5G"])), 1)]
        else:
            plan = []
        for tech, sector in plan:
            cell_seq += 1
            commissioned = built[i] + pd.Timedelta(days=int(rng.integers(0, 365)))
            cells.append(
                {
                    "cell_id": f"CELL{cell_seq:06d}",
                    "site_id": site_id,
                    "technology": tech,
                    "band": "n78" if tech == "5G" else str(rng.choice(["B3", "B7", "B20"])),
                    "sector": sector,
                    "commissioned_date": commissioned,
                    "status": "ACTIVE" if rng.random() < 0.97 else "LOCKED",
                    "updated_at": commissioned + pd.Timedelta(hours=10),
                }
            )

        for dtype, vendor, model in DEVICE_PLAN[stype]:
            dev_seq += 1
            installed = built[i] + pd.Timedelta(days=int(rng.integers(0, 200)))
            devices.append(
                {
                    "device_id": f"DEV{dev_seq:06d}",
                    "site_id": site_id,
                    "device_type": dtype,
                    "vendor": vendor,
                    "model": model,
                    "serial_number": f"{vendor[:2].upper()}{dev_seq:06d}{rng.integers(100, 999)}",
                    "install_date": installed,
                    "status": "IN_SERVICE" if rng.random() < 0.96 else "DECOMMISSIONED",
                    "updated_at": installed
                    + pd.Timedelta(days=int(rng.integers(0, 400)), hours=11),
                }
            )

    sites_df = pd.DataFrame(sites)
    sites_df["updated_at"] = sites_df["updated_at"].clip(upper=pd.Timestamp(cfg.as_of))
    devices_df = pd.DataFrame(devices)
    devices_df["updated_at"] = devices_df["updated_at"].clip(upper=pd.Timestamp(cfg.as_of))
    return sites_df, pd.DataFrame(cells), devices_df
