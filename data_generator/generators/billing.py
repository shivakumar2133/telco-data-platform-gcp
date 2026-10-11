"""Billing system (lands in Oracle): accounts, invoices, invoice lines, payments."""

from __future__ import annotations

import numpy as np
import pandas as pd

from data_generator.config import GenConfig
from data_generator.defects import DefectLog, pick

PAYMENT_METHODS = ["DIRECT_DEBIT", "CARD", "BANK_TRANSFER"]


def make_billing(
    cfg: GenConfig,
    rng: np.random.Generator,
    customers: pd.DataFrame,
    subs: pd.DataFrame,
    products: pd.DataFrame,
    rated_usage: pd.Series,
    log: DefectLog,
) -> dict[str, pd.DataFrame]:
    sys = "Billing (Oracle)"
    as_of = pd.Timestamp(cfg.as_of)

    # One billing account per customer
    n = len(customers)
    accounts = pd.DataFrame(
        {
            "account_id": [f"ACC{i + 1:07d}" for i in range(n)],
            "customer_id": customers["customer_id"].to_numpy(),
            "billing_cycle_day": 1,
            "payment_method": rng.choice(PAYMENT_METHODS, n, p=[0.75, 0.15, 0.10]),
            "credit_class": rng.choice(["A", "B", "C"], n, p=[0.7, 0.22, 0.08]),
            "created_at": customers["created_at"].to_numpy(),
            "updated_at": customers["created_at"].to_numpy(),
        }
    )
    pay_method = dict(zip(accounts.account_id, accounts.payment_method, strict=True))

    subs_p = subs.merge(
        products[["product_id", "product_name", "product_type", "monthly_fee"]], on="product_id"
    )
    acct_map = accounts[["customer_id", "account_id"]]
    cdr_month = pd.Timestamp(cfg.cdr_start).to_period("M").to_timestamp()

    line_frames = []
    months = pd.date_range(
        pd.Timestamp(cfg.history_start), pd.Timestamp(cfg.history_end), freq="MS"
    )
    for m_start in months:
        m_end = m_start + pd.offsets.MonthEnd(0)
        # Inner join to accounts: orphan subscriptions get no invoice (unbilled usage)
        act = subs_p[
            (subs_p["start_date"] <= m_end)
            & (subs_p["end_date"].isna() | (subs_p["end_date"] >= m_start))
        ].merge(acct_map, on="customer_id")

        recurring = pd.DataFrame(
            {
                "account_id": act["account_id"],
                "subscription_id": act["subscription_id"],
                "charge_type": "RECURRING",
                "description": act["product_name"] + " monthly charge",
                "quantity": 1,
                "amount": act["monthly_fee"],
            }
        )

        mob = act[act["product_type"] == "MOBILE"]
        if m_start == cdr_month:
            usage_amt = mob["subscription_id"].map(rated_usage).fillna(0.0).to_numpy()
        else:
            usage_amt = np.where(
                rng.random(len(mob)) < 0.4, 0.0, np.round(rng.gamma(1.2, 2.0, len(mob)), 2)
            )
        usage = pd.DataFrame(
            {
                "account_id": mob["account_id"].to_numpy(),
                "subscription_id": mob["subscription_id"].to_numpy(),
                "charge_type": "USAGE",
                "description": "Out-of-bundle usage",
                "quantity": 1,
                "amount": usage_amt,
            }
        )
        usage = usage[usage["amount"] > 0].reset_index(drop=True)

        if m_start == cdr_month:
            # Defect (revenue leakage): rated usage never reached the invoice
            idx = pick(rng, len(usage), 0.02)
            leaked = usage.loc[idx]
            log.add(
                "billing_revenue_leakage",
                sys,
                "Rated CDR usage for the CDR month has no USAGE invoice line",
                leaked["subscription_id"],
                missing_amount=round(float(leaked["amount"].sum()), 2),
            )
            usage = usage.drop(index=idx)

        oneoff_idx = pick(rng, len(act), 0.03)
        oneoff_kind = rng.choice([0, 1], len(oneoff_idx))
        oneoff = pd.DataFrame(
            {
                "account_id": act["account_id"].to_numpy()[oneoff_idx],
                "subscription_id": act["subscription_id"].to_numpy()[oneoff_idx],
                "charge_type": "ONEOFF",
                "description": np.where(oneoff_kind == 0, "Late payment fee", "Equipment charge"),
                "quantity": 1,
                "amount": np.where(oneoff_kind == 0, 7.50, 49.99),
            }
        )

        lines_m = pd.concat([recurring, usage, oneoff], ignore_index=True)
        lines_m["period_start"] = m_start
        lines_m["period_end"] = m_end.normalize()
        line_frames.append(lines_m)

    lines = pd.concat(line_frames, ignore_index=True)
    lines["amount"] = lines["amount"].astype(float).round(2)

    inv = (
        lines.groupby(["period_start", "period_end", "account_id"], as_index=False)["amount"]
        .sum()
        .rename(columns={"amount": "total_amount"})
        .sort_values(["period_start", "account_id"])
        .reset_index(drop=True)
    )
    inv["total_amount"] = inv["total_amount"].round(2)
    inv.insert(0, "invoice_id", [f"INV{i:08d}" for i in range(1, len(inv) + 1)])
    inv["invoice_date"] = inv["period_end"] + pd.Timedelta(days=1)
    inv["due_date"] = inv["invoice_date"] + pd.Timedelta(days=14)

    lines = lines.merge(
        inv[["period_start", "account_id", "invoice_id"]], on=["period_start", "account_id"]
    )
    lines = lines.sort_values(["invoice_id", "charge_type", "subscription_id"]).reset_index(
        drop=True
    )
    lines.insert(0, "line_id", [f"LIN{i:010d}" for i in range(1, len(lines) + 1)])

    # Defect: invoice header total does not equal the sum of its lines
    idx = pick(rng, len(inv), 0.003)
    inv.loc[idx, "total_amount"] = (
        inv.loc[idx, "total_amount"] + np.round(rng.uniform(0.01, 5.0, len(idx)), 2)
    ).round(2)
    log.add(
        "billing_header_line_mismatch",
        sys,
        "invoices.total_amount != SUM(invoice_lines.amount)",
        inv.loc[idx, "invoice_id"],
    )

    # Payments and invoice status as of the as_of date
    payments, status, updated = [], [], []
    for r in inv.itertuples(index=False):
        roll = rng.random()
        overdue_possible = r.due_date <= as_of
        if overdue_possible:
            outcome = "FULL" if roll < 0.90 else ("PARTIAL" if roll < 0.95 else "NONE")
        else:
            outcome = "FULL" if roll < 0.35 else "NONE"
        created = r.invoice_date + pd.Timedelta(hours=2)
        if outcome == "NONE":
            status.append("OVERDUE" if r.due_date < as_of else "ISSUED")
            updated.append(created)
            continue
        amount = (
            r.total_amount
            if outcome == "FULL"
            else round(r.total_amount * rng.uniform(0.3, 0.8), 2)
        )
        latest = min(r.due_date + pd.Timedelta(days=10), as_of)
        span = max(1, (latest - r.invoice_date).days + 1)
        pdate = r.invoice_date + pd.Timedelta(days=int(rng.integers(0, span)))
        payments.append(
            {
                "payment_id": f"PAY{len(payments) + 1:08d}",
                "invoice_id": r.invoice_id,
                "payment_date": pdate,
                "amount": amount,
                "payment_method": pay_method[r.account_id],
                "created_at": pdate + pd.Timedelta(hours=10),
            }
        )
        status.append("PAID" if outcome == "FULL" else "PARTIALLY_PAID")
        updated.append(max(created, pdate + pd.Timedelta(hours=10)))

    inv["status"] = status
    inv["created_at"] = inv["invoice_date"] + pd.Timedelta(hours=2)
    inv["updated_at"] = updated

    invoices = inv[
        [
            "invoice_id",
            "account_id",
            "invoice_date",
            "period_start",
            "period_end",
            "due_date",
            "total_amount",
            "status",
            "created_at",
            "updated_at",
        ]
    ]
    invoice_lines = lines[
        [
            "line_id",
            "invoice_id",
            "subscription_id",
            "charge_type",
            "description",
            "quantity",
            "amount",
        ]
    ]
    return {
        "billing_accounts": accounts,
        "invoices": invoices,
        "invoice_lines": invoice_lines,
        "payments": pd.DataFrame(payments),
    }
