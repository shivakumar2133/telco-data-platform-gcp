"""Call detail records (daily CSV files from the mediation platform)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_generator.config import GenConfig
from data_generator.defects import DefectLog, pick

CALL_TYPES = np.array(["VOICE", "SMS", "DATA"])
CDR_COLUMNS = [
    "cdr_id",
    "msisdn_a",
    "msisdn_b",
    "call_type",
    "start_time",
    "duration_sec",
    "data_volume_mb",
    "cell_id",
    "call_result",
    "charge_amount",
]
EVENTS_PER_SUB_PER_DAY = 6.0


def make_cdrs(
    cfg: GenConfig,
    rng: np.random.Generator,
    subs: pd.DataFrame,
    products: pd.DataFrame,
    cells: pd.DataFrame,
) -> tuple[dict[pd.Timestamp, pd.DataFrame], pd.Series]:
    """Return (clean CDRs per day incl. subscription_id, rated usage per subscription).

    The rated usage is the 'truth' that billing should invoice (used in Phase 7
    for revenue-assurance reconciliation).
    """
    mob = subs.merge(products[["product_id", "product_type"]], on="product_id")
    mob = mob[mob["product_type"] == "MOBILE"]

    active_cells = cells.loc[cells["status"] == "ACTIVE", "cell_id"].to_numpy()
    n_bad = max(1, int(len(active_cells) * 0.05))
    bad_cells = rng.choice(active_cells, n_bad, replace=False)
    is_bad_cell = np.isin(active_cells, bad_cells)  # these cells drop ~12% of calls

    days = pd.date_range(pd.Timestamp(cfg.cdr_start), periods=cfg.cdr_days, freq="D")
    clean: dict[pd.Timestamp, pd.DataFrame] = {}
    for day in days:
        act = mob[(mob["start_date"] <= day) & (mob["end_date"].isna() | (mob["end_date"] > day))]
        counts = rng.poisson(EVENTS_PER_SUB_PER_DAY, len(act))
        n = int(counts.sum())

        call_type = rng.choice(CALL_TYPES, n, p=[0.45, 0.30, 0.25])
        is_voice, is_sms, is_data = call_type == "VOICE", call_type == "SMS", call_type == "DATA"

        duration = np.zeros(n, dtype=np.int64)
        duration[is_voice] = np.maximum(1, np.round(rng.lognormal(4.3, 1.0, is_voice.sum())))
        duration[is_data] = rng.integers(30, 3600, is_data.sum())
        data_mb = np.zeros(n)
        data_mb[is_data] = np.round(rng.lognormal(3.0, 1.2, is_data.sum()), 2)

        msisdn_b = (447_000_000_000 + rng.integers(0, 10**9, n)).astype(str).astype(object)
        msisdn_b[is_data] = None

        cell_idx = rng.integers(0, len(active_cells), n)
        p_drop = np.where(is_bad_cell[cell_idx], 0.12, 0.015)
        u = rng.random(n)
        result = np.where(u < p_drop, "DROPPED", np.where(u < p_drop + 0.01, "FAILED", "COMPLETED"))

        # Out-of-bundle charges: some voice minutes and texts are billable
        charge = np.zeros(n)
        bill_voice = is_voice & (rng.random(n) < 0.25)
        bill_sms = is_sms & (rng.random(n) < 0.15)
        charge[bill_voice] = np.ceil(duration[bill_voice] / 60) * 0.05
        charge[bill_sms] = 0.04
        charge[result == "FAILED"] = 0.0

        df = pd.DataFrame(
            {
                "msisdn_a": np.repeat(act["msisdn"].to_numpy(), counts),
                "msisdn_b": msisdn_b,
                "call_type": call_type,
                "start_time": day + pd.to_timedelta(rng.integers(0, 86_400, n), unit="s"),
                "duration_sec": duration,
                "data_volume_mb": data_mb,
                "cell_id": active_cells[cell_idx],
                "call_result": result,
                "charge_amount": np.round(charge, 2),
                "subscription_id": np.repeat(act["subscription_id"].to_numpy(), counts),
            }
        )
        df = df.sort_values("start_time", kind="stable").reset_index(drop=True)
        df.insert(0, "cdr_id", [f"CDR{day:%Y%m%d}{i:07d}" for i in range(1, n + 1)])
        clean[day] = df

    all_cdrs = pd.concat(clean.values(), ignore_index=True)
    rated = all_cdrs.groupby("subscription_id")["charge_amount"].sum().round(2)
    return clean, rated


def apply_cdr_defects(
    clean: dict[pd.Timestamp, pd.DataFrame], rng: np.random.Generator, log: DefectLog
) -> dict[pd.Timestamp, pd.DataFrame]:
    sys = "CDR files"
    days = sorted(clean)
    files = {d: clean[d][CDR_COLUMNS].copy() for d in days}

    # Late arrivals: records from day D delivered in day D+1's file
    late_rows: dict[pd.Timestamp, pd.DataFrame] = {}
    for i, d in enumerate(days[:-1]):
        f = files[d]
        idx = pick(rng, len(f), 0.005)
        late_rows[days[i + 1]] = f.loc[idx]
        files[d] = f.drop(index=idx).reset_index(drop=True)
        log.add(
            "cdr_late_arrival", sys, "CDR delivered in the next day's file", f.loc[idx, "cdr_id"]
        )

    for d in days:
        f = files[d]
        idx = pick(rng, len(f), 0.001)
        f.loc[idx, "cell_id"] = "CELL999999"
        log.add("cdr_unknown_cell", sys, "cell_id not in network inventory", f.loc[idx, "cdr_id"])

        voice = np.flatnonzero(f["call_type"].to_numpy() == "VOICE")
        sel = voice[pick(rng, len(voice), 0.0005)]
        f.loc[sel, "duration_sec"] = -f.loc[sel, "duration_sec"]
        log.add("cdr_negative_duration", sys, "VOICE duration_sec < 0", f.loc[sel, "cdr_id"])

        idx = pick(rng, len(f), 0.002)
        dups = f.loc[idx]
        log.add("cdr_duplicate", sys, "Same cdr_id appears twice in a file", dups["cdr_id"])

        parts = [f, dups] + ([late_rows[d]] if d in late_rows else [])
        files[d] = pd.concat(parts, ignore_index=True)
    return files
