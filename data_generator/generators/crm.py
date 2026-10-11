"""CRM system (lands in SQL Server): customers, products, subscriptions."""

from __future__ import annotations

import numpy as np
import pandas as pd
from faker import Faker

from data_generator.config import GenConfig
from data_generator.defects import DefectLog, pick

REGIONS = [
    "London",
    "South East",
    "South West",
    "East of England",
    "West Midlands",
    "East Midlands",
    "North West",
    "North East",
    "Yorkshire and the Humber",
    "Scotland",
    "Wales",
    "Northern Ireland",
]
REGION_WEIGHTS = [0.17, 0.14, 0.08, 0.09, 0.08, 0.07, 0.11, 0.04, 0.08, 0.07, 0.04, 0.03]
SEGMENTS = ["Consumer", "SME", "Enterprise"]

PRODUCT_COLUMNS = [
    "product_id",
    "product_name",
    "product_type",
    "segment",
    "monthly_fee",
    "data_allowance_gb",
    "minutes_allowance",
    "sla_tier",
]
# allowance None = unlimited
PRODUCTS = [
    ("MOB-SIM-5GB", "SIM Only 5GB", "MOBILE", "Consumer", 10.00, 5, 500, "Standard"),
    ("MOB-SIM-30GB", "SIM Only 30GB", "MOBILE", "Consumer", 16.00, 30, None, "Standard"),
    ("MOB-UNL", "Unlimited Mobile", "MOBILE", "Consumer", 25.00, None, None, "Standard"),
    (
        "MOB-BIZ-UNL",
        "Business Unlimited Mobile",
        "MOBILE",
        "Business",
        30.00,
        None,
        None,
        "Enhanced",
    ),
    ("BB-FIBRE-80", "Fibre 80", "BROADBAND", "Consumer", 30.00, None, None, "Standard"),
    ("BB-FIBRE-500", "Full Fibre 500", "BROADBAND", "Consumer", 45.00, None, None, "Standard"),
    ("BB-FIBRE-900", "Full Fibre 900", "BROADBAND", "Consumer", 55.00, None, None, "Enhanced"),
    (
        "BB-BIZ-FIBRE-900",
        "Business Full Fibre 900",
        "BROADBAND",
        "Business",
        60.00,
        None,
        None,
        "Enhanced",
    ),
    ("ETH-100M", "Ethernet 100Mbps", "ETHERNET", "Business", 250.00, None, None, "Premium"),
    ("ETH-1G", "Ethernet 1Gbps", "ETHERNET", "Business", 450.00, None, None, "Premium"),
    ("ETH-10G", "Ethernet 10Gbps", "ETHERNET", "Business", 1200.00, None, None, "Premium"),
]

CONSUMER_MOBILE = ["MOB-SIM-5GB", "MOB-SIM-30GB", "MOB-UNL"]
CONSUMER_BB = ["BB-FIBRE-80", "BB-FIBRE-500", "BB-FIBRE-900"]
ETHERNET = ["ETH-100M", "ETH-1G", "ETH-10G"]


class MsisdnPool:
    """Unique UK mobile numbers (447xxxxxxxxx)."""

    def __init__(self, rng: np.random.Generator, size: int) -> None:
        nums = 447_000_000_000 + rng.choice(999_999_999, size=size, replace=False)
        self._it = iter(nums.astype(str).tolist())

    def take(self) -> str:
        return next(self._it)


def make_products() -> pd.DataFrame:
    df = pd.DataFrame(PRODUCTS, columns=PRODUCT_COLUMNS)
    df["data_allowance_gb"] = df["data_allowance_gb"].astype("Int64")
    df["minutes_allowance"] = df["minutes_allowance"].astype("Int64")
    df["created_at"] = pd.Timestamp("2018-01-01 09:00:00")
    df["updated_at"] = pd.Timestamp("2026-01-01 09:00:00")
    return df


def make_customers(
    cfg: GenConfig, rng: np.random.Generator, fake: Faker, pool: MsisdnPool
) -> pd.DataFrame:
    n = cfg.n_customers
    segments = rng.choice(SEGMENTS, n, p=[0.75, 0.20, 0.05])
    regions = rng.choice(REGIONS, n, p=REGION_WEIGHTS)
    statuses = rng.choice(["ACTIVE", "SUSPENDED", "CEASED"], n, p=[0.93, 0.03, 0.04])

    first_day = pd.Timestamp("2018-01-01")
    last_day = pd.Timestamp(cfg.history_start) - pd.Timedelta(days=1)
    span_s = int((last_day - first_day).total_seconds())
    created = first_day + pd.to_timedelta(rng.integers(0, span_s, n), unit="s")
    as_of = pd.Timestamp(cfg.as_of)

    rows = []
    for i in range(n):
        first, last = fake.first_name(), fake.last_name()
        if segments[i] == "Consumer":
            company = None
            email = f"{first}.{last}{rng.integers(1, 1000)}@example.com"
            dob = as_of.normalize() - pd.Timedelta(days=int(rng.integers(18 * 365, 85 * 365)))
        else:
            company = fake.company()
            slug = "".join(ch for ch in company.lower() if ch.isalnum())[:20]
            email = f"{first}.{last}@{slug}.example.com"
            dob = pd.NaT
        c_created = created[i].floor("s")
        c_updated = c_created + (as_of - c_created) * float(rng.random())
        rows.append(
            {
                "customer_id": f"CUS{i + 1:07d}",
                "segment": segments[i],
                "first_name": first,
                "last_name": last,
                "company_name": company,
                "email": email.lower().replace("'", ""),
                "msisdn": pool.take(),
                "date_of_birth": dob,
                "address_line1": fake.street_address().replace("\n", ", "),
                "city": fake.city(),
                "postcode": fake.postcode(),
                "region": regions[i],
                "status": statuses[i],
                "created_at": c_created,
                "updated_at": c_updated.floor("s"),
            }
        )
    df = pd.DataFrame(rows)
    df["date_of_birth"] = pd.to_datetime(df["date_of_birth"])
    return df


def make_subscriptions(
    cfg: GenConfig,
    rng: np.random.Generator,
    customers: pd.DataFrame,
    products: pd.DataFrame,
    pool: MsisdnPool,
    log: DefectLog,
) -> pd.DataFrame:
    ptype = dict(zip(products.product_id, products.product_type, strict=True))
    latest_start = pd.Timestamp(cfg.history_end) - pd.Timedelta(days=10)
    as_of = pd.Timestamp(cfg.as_of)

    rows = []
    seq = 0
    for c in customers.itertuples(index=False):
        chosen: list[str] = []
        if c.segment == "Consumer":
            for _ in range(int(rng.choice([0, 1, 2], p=[0.15, 0.70, 0.15]))):
                chosen.append(str(rng.choice(CONSUMER_MOBILE)))
            if rng.random() < 0.6:
                chosen.append(str(rng.choice(CONSUMER_BB)))
        elif c.segment == "SME":
            chosen += ["MOB-BIZ-UNL"] * int(rng.integers(1, 4))
            if rng.random() < 0.7:
                chosen.append("BB-BIZ-FIBRE-900")
            if rng.random() < 0.1:
                chosen.append(str(rng.choice(ETHERNET)))
        else:  # Enterprise
            chosen += ["MOB-BIZ-UNL"] * int(rng.integers(2, 6))
            chosen += [str(rng.choice(ETHERNET)) for _ in range(int(rng.integers(1, 3)))]
        if not chosen:
            chosen = [str(rng.choice(CONSUMER_MOBILE))]

        earliest = max(c.created_at.normalize(), pd.Timestamp("2019-01-01"))
        span = max(1, (latest_start - earliest).days)
        for pid in chosen:
            seq += 1
            start = earliest + pd.Timedelta(days=int(rng.integers(0, span)))
            end = pd.NaT
            if c.status == "CEASED" or rng.random() < 0.04:
                remaining = (as_of - start).days
                if remaining > 1:
                    end = start + pd.Timedelta(days=int(rng.integers(1, remaining)))
            created_at = start + pd.Timedelta(hours=int(rng.integers(8, 18)))
            updated_at = created_at if pd.isna(end) else end + pd.Timedelta(hours=10)
            rows.append(
                {
                    "subscription_id": f"SUB{seq:07d}",
                    "customer_id": c.customer_id,
                    "product_id": pid,
                    "msisdn": pool.take() if ptype[pid] == "MOBILE" else None,
                    "start_date": start,
                    "end_date": end,
                    "status": "ACTIVE" if pd.isna(end) else "CEASED",
                    "created_at": created_at,
                    "updated_at": updated_at,
                }
            )
    subs = pd.DataFrame(rows)
    subs["end_date"] = pd.to_datetime(subs["end_date"])

    # Defect: orphan subscriptions (customer no longer exists in CRM). No FK in the
    # legacy CRM, so this happens in real life. Their usage is never billed.
    idx = pick(rng, len(subs), 0.002)
    subs.loc[idx, "customer_id"] = [f"CUS9{rng.integers(0, 10**6):06d}" for _ in idx]
    log.add(
        "crm_orphan_subscription",
        "CRM (SQL Server)",
        "subscriptions.customer_id points to a customer that does not exist",
        subs.loc[idx, "subscription_id"],
    )
    return subs


def apply_customer_defects(
    cfg: GenConfig, customers: pd.DataFrame, rng: np.random.Generator, log: DefectLog
) -> pd.DataFrame:
    df = customers.copy()
    n = len(df)

    # Null emails
    idx = pick(rng, n, 0.01)
    df.loc[idx, "email"] = None
    log.add(
        "crm_null_email", "CRM (SQL Server)", "customers.email is NULL", df.loc[idx, "customer_id"]
    )

    # Invalid postcodes
    idx = pick(rng, n, 0.005)
    df.loc[idx, "postcode"] = rng.choice(["N/A", "UNKNOWN", "12345"], len(idx))
    log.add(
        "crm_invalid_postcode",
        "CRM (SQL Server)",
        "customers.postcode is not a UK postcode",
        df.loc[idx, "customer_id"],
    )

    # Duplicate customers: same person re-keyed with a new ID, name in upper case
    idx = pick(rng, n, 0.005)
    dups = df.loc[idx].copy()
    dups["customer_id"] = [f"CUS{n + k + 1:07d}" for k in range(len(dups))]
    dups["first_name"] = dups["first_name"].str.upper()
    dups["status"] = "ACTIVE"
    dups["created_at"] = (
        dups["created_at"] + pd.to_timedelta(rng.integers(30, 400, len(dups)), unit="D")
    ).clip(upper=pd.Timestamp(cfg.history_end))
    dups["updated_at"] = dups["created_at"]
    log.add(
        "crm_duplicate_customer",
        "CRM (SQL Server)",
        "Same person stored twice under different customer_id (same email, DOB)",
        dups["customer_id"],
        original_ids=df.loc[idx, "customer_id"].tolist(),
    )
    return pd.concat([df, dups], ignore_index=True)
