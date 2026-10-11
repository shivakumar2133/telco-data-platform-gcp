"""Network alarms (nested JSON exports) and trouble tickets (served by the REST API)."""

from __future__ import annotations

import copy
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from data_generator.config import GenConfig
from data_generator.defects import DefectLog, pick
from data_generator.generators.sla import SLA_MATRIX

SEVERITIES = ["CRITICAL", "MAJOR", "MINOR", "WARNING"]
SEVERITY_P = [0.10, 0.25, 0.35, 0.30]
MEAN_CLEAR_HOURS = {"CRITICAL": 2, "MAJOR": 4, "MINOR": 8, "WARNING": 12}
ALARM_TYPES = {
    "BASEBAND": ["CELL_OUTAGE", "HIGH_TEMPERATURE", "SYNC_LOSS"],
    "ROUTER": ["LINK_DOWN", "HIGH_CPU", "BGP_SESSION_DOWN"],
    "RADIO_UNIT": ["VSWR_HIGH", "POWER_FAILURE"],
    "OLT": ["PON_LOS", "POWER_FAILURE"],
    "SWITCH": ["PORT_DOWN", "FAN_FAILURE"],
}
PROBABLE_CAUSE = {
    "LINK_DOWN": "Fibre cut",
    "HIGH_CPU": "Traffic spike",
    "POWER_FAILURE": "Mains failure",
    "PON_LOS": "Loss of signal",
    "PORT_DOWN": "Port disabled",
    "FAN_FAILURE": "Hardware fault",
    "CELL_OUTAGE": "Baseband fault",
    "HIGH_TEMPERATURE": "Cooling failure",
    "SYNC_LOSS": "GPS sync lost",
    "BGP_SESSION_DOWN": "Peer unreachable",
    "VSWR_HIGH": "Antenna feeder fault",
}
TIER_RANK = {"Standard": 1, "Enhanced": 2, "Premium": 3}
ASSIGNMENT_GROUP = {
    "NETWORK_FAULT": "NOC Tier 2",
    "FAULT": "Service Desk",
    "BILLING": "Billing Ops",
    "ORDER": "Provisioning",
    "COMPLAINT": "Customer Relations",
}


def iso(ts) -> str | None:
    if ts is None or pd.isna(ts):
        return None
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_alarms(
    cfg: GenConfig, rng: np.random.Generator, devices: pd.DataFrame, log: DefectLog
) -> tuple[dict[pd.Timestamp, dict], list[dict]]:
    """Return (export file per day, clean list of alarms)."""
    sys = "Alarm exports (JSON)"
    in_service = devices[devices["status"] == "IN_SERVICE"].reset_index(drop=True)
    days = pd.date_range(pd.Timestamp(cfg.cdr_start), periods=cfg.cdr_days, freq="D")

    per_day: dict[pd.Timestamp, list[dict]] = {}
    for day in days:
        alarms = []
        counts = rng.poisson(0.08, len(in_service))
        for dev, k in zip(in_service.itertuples(index=False), counts, strict=True):
            for _ in range(int(k)):
                sev = str(rng.choice(SEVERITIES, p=SEVERITY_P))
                atype = str(rng.choice(ALARM_TYPES[dev.device_type]))
                raised = day + timedelta(seconds=int(rng.integers(0, 86_400)))
                cleared = None
                if rng.random() >= 0.03:  # 3% still active at export time
                    cleared = raised + timedelta(
                        minutes=1 + float(rng.exponential(MEAN_CLEAR_HOURS[sev] * 60))
                    )
                alarms.append(
                    {
                        "alarm_id": "",
                        "device": {
                            "device_id": dev.device_id,
                            "site_id": dev.site_id,
                            "device_type": dev.device_type,
                            "vendor": dev.vendor,
                        },
                        "severity": sev,
                        "alarm_type": atype,
                        "raised_at": iso(raised),
                        "cleared_at": iso(cleared),
                        "attributes": {
                            "probable_cause": PROBABLE_CAUSE[atype],
                            "interface": f"ge-0/0/{int(rng.integers(0, 48))}",
                            "vendor_code": f"{dev.vendor[:3].upper()}-{rng.integers(1000, 9999)}",
                        },
                    }
                )
        alarms.sort(key=lambda a: a["raised_at"])
        for i, a in enumerate(alarms, start=1):
            a["alarm_id"] = f"ALM{day:%Y%m%d}{i:05d}"
        per_day[day] = alarms

    clean = [a for d in days for a in per_day[d]]
    exports = {d: copy.deepcopy(per_day[d]) for d in days}

    reexports: dict[pd.Timestamp, list[dict]] = {}
    for i, d in enumerate(days):
        alarms = exports[d]
        with_clear = [j for j, a in enumerate(alarms) if a["cleared_at"]]
        sel = [with_clear[j] for j in pick(rng, len(with_clear), 0.005)]
        for j in sel:
            raised = datetime.strptime(alarms[j]["raised_at"], "%Y-%m-%dT%H:%M:%SZ")
            alarms[j]["cleared_at"] = iso(raised - timedelta(minutes=30))
        log.add(
            "alarm_cleared_before_raised",
            sys,
            "cleared_at < raised_at",
            [alarms[j]["alarm_id"] for j in sel],
        )

        sel = pick(rng, len(alarms), 0.003)
        for j in sel:
            alarms[j]["device"]["device_id"] = "DEV999999"
        log.add(
            "alarm_unknown_device",
            sys,
            "device_id not in network inventory",
            [alarms[j]["alarm_id"] for j in sel],
        )

        if i < len(days) - 1:
            sel = pick(rng, len(per_day[d]), 0.01)
            again = [copy.deepcopy(per_day[d][j]) for j in sel]
            reexports[days[i + 1]] = again
            log.add(
                "alarm_reexported",
                sys,
                "Alarm re-sent in the next day's export",
                [a["alarm_id"] for a in again],
            )

    for d, again in reexports.items():
        exports[d] = exports[d] + again

    files = {}
    bad_day = days[int(rng.integers(0, len(days)))]
    for d in days:
        record_count = len(exports[d])
        if d == bad_day:
            record_count += 1
        files[d] = {
            "export_id": f"NMS-EXPORT-{d:%Y%m%d}",
            "exported_at": iso(d + timedelta(days=1, hours=1)),
            "source_system": "NMS-SIM",
            "record_count": record_count,
            "alarms": exports[d],
        }
    log.add(
        "alarm_record_count_mismatch",
        sys,
        "Header record_count != number of alarms in the file",
        [f"NMS-EXPORT-{bad_day:%Y%m%d}"],
    )
    return files, clean


def make_tickets(
    cfg: GenConfig,
    rng: np.random.Generator,
    customers: pd.DataFrame,
    subs: pd.DataFrame,
    products: pd.DataFrame,
    sites: pd.DataFrame,
    alarms: list[dict],
    log: DefectLog,
) -> list[dict]:
    sys = "Ticketing API"
    as_of = pd.Timestamp(cfg.as_of)

    tiers = subs.merge(products[["product_id", "sla_tier"]], on="product_id")
    tiers["rank"] = tiers["sla_tier"].map(TIER_RANK)
    best = tiers.sort_values("rank").groupby("customer_id")["sla_tier"].last()
    tier_of = best.to_dict()

    site_region = dict(zip(sites.site_id, sites.region, strict=True))
    business = customers[customers["segment"] != "Consumer"]
    if business.empty:
        business = customers
    biz_by_region = business.groupby("region")["customer_id"].apply(list).to_dict()
    all_business = business["customer_id"].tolist()

    drafts: list[dict] = []
    for a in alarms:
        if a["severity"] in ("CRITICAL", "MAJOR") and rng.random() < 0.7:
            pool = biz_by_region.get(site_region.get(a["device"]["site_id"]), all_business)
            raised = pd.Timestamp(a["raised_at"].rstrip("Z"))
            drafts.append(
                {
                    "customer_id": str(rng.choice(pool)),
                    "alarm_id": a["alarm_id"],
                    "category": "NETWORK_FAULT",
                    "priority": "P1" if a["severity"] == "CRITICAL" else "P2",
                    "opened_at": raised + pd.Timedelta(minutes=int(rng.integers(5, 60))),
                }
            )

    n_cust = int(len(customers) * 0.15)
    window_s = int((as_of - pd.Timedelta(days=1) - pd.Timestamp(cfg.history_start)).total_seconds())
    cust_ids = rng.choice(customers["customer_id"].to_numpy(), n_cust)
    cats = rng.choice(["BILLING", "FAULT", "ORDER", "COMPLAINT"], n_cust, p=[0.35, 0.4, 0.15, 0.1])
    prios = rng.choice(["P2", "P3", "P4"], n_cust, p=[0.15, 0.5, 0.35])
    offsets = rng.integers(0, window_s, n_cust)
    for cid, cat, pr, off in zip(cust_ids, cats, prios, offsets, strict=True):
        drafts.append(
            {
                "customer_id": str(cid),
                "alarm_id": None,
                "category": str(cat),
                "priority": str(pr),
                "opened_at": pd.Timestamp(cfg.history_start) + pd.Timedelta(seconds=int(off)),
            }
        )

    drafts.sort(key=lambda t: t["opened_at"])
    tickets = []
    for i, t in enumerate(drafts, start=1):
        tier = tier_of.get(t["customer_id"], "Standard")
        target = SLA_MATRIX[tier][t["priority"]][1]
        hours = target * float(rng.lognormal(np.log(0.6), 0.55))  # ~15% breach SLA
        resolved = t["opened_at"] + pd.Timedelta(hours=hours)
        if resolved <= as_of:
            status = str(rng.choice(["RESOLVED", "CLOSED"], p=[0.4, 0.6]))
            updated = resolved
        else:
            status = str(rng.choice(["IN_PROGRESS", "NEW"], p=[0.7, 0.3]))
            resolved = None
            updated = min(as_of, t["opened_at"] + pd.Timedelta(hours=float(rng.uniform(0, 4))))
        tickets.append(
            {
                "ticket_id": f"INC{i:07d}",
                "customer_id": t["customer_id"],
                "alarm_id": t["alarm_id"],
                "category": t["category"],
                "priority": t["priority"],
                "service_level": tier,
                "status": status,
                "assignment_group": ASSIGNMENT_GROUP[t["category"]],
                "opened_at": iso(t["opened_at"]),
                "resolved_at": iso(resolved),
                "updated_at": iso(updated),
            }
        )

    resolved_idx = [j for j, t in enumerate(tickets) if t["resolved_at"]]
    sel = [resolved_idx[j] for j in pick(rng, len(resolved_idx), 0.005)]
    for j in sel:
        tickets[j]["status"] = "RESOLVED"
        tickets[j]["resolved_at"] = None
    log.add(
        "ticket_resolved_without_date",
        sys,
        "status RESOLVED but resolved_at is null",
        [tickets[j]["ticket_id"] for j in sel],
    )

    sel = pick(rng, len(tickets), 0.003)
    for j in sel:
        tickets[j]["customer_id"] = "CUS9999999"
    log.add(
        "ticket_unknown_customer",
        sys,
        "customer_id not in CRM",
        [tickets[j]["ticket_id"] for j in sel],
    )
    return tickets
