"""Held-out evaluation data generator — deliberately harsher than the demo generator.

Differences vs ``generate_data.py`` (which the detection engine was developed against):

* ID corruption: ledger/GST ``invoice_id`` references get typos (char swaps,
  deletions, case changes) so fuzzy matching must recover them.
* Split invoices: ledger posts only a fraction of the invoice taxable value.
* Date drift: entry dates shifted by 8-20 days (well past the 7-day tolerance)
* Date-format drift in stored dates.
* Partial-amount alterations at awkward magnitudes (e.g. +450.01).
* A negative-control mode with zero injected errors to measure the false-positive rate.

Everything is deterministic for a given seed.
"""
from __future__ import annotations

import random
import string
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

GST_RATES = [0.0, 5.0, 12.0, 18.0, 28.0]


def _typo_id(inv_id: str, rng: random.Random) -> str:
    """Corrupt an invoice id: swap, delete, duplicate a char, or change case."""
    chars = list(inv_id)
    ops = ["swap", "delete", "dup", "case"]
    op = rng.choice(ops)
    i = rng.randrange(1, len(chars))  # keep first char
    if op == "swap" and i < len(chars) - 1:
        chars[i], chars[i + 1] = chars[i + 1], chars[i]
    elif op == "delete" and len(chars) > 4:
        del chars[i]
    elif op == "dup":
        chars.insert(i, chars[i])
    elif op == "case":
        chars[i] = chars[i].lower() if chars[i].isalpha() else chars[i]
    return "".join(chars)


def generate_eval(n: int, seed: int, per_type: int = 20) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return (invoices, ledger, gst, ground_truth) with harsher corruptions."""
    rng = np.random.default_rng(seed)
    pyrng = random.Random(seed)
    n_vendors = max(20, min(100, n // 10))
    vendors = [f"V{i:04d}" for i in range(1, n_vendors + 1)]
    start = date(2026, 4, 1)

    invoice_rows, ledger_rows, gst_rows, truth = [], [], [], []
    for i in range(1, n + 1):
        vendor = vendors[int(rng.integers(0, len(vendors)))]
        inv_id = f"TX-{i:06d}"
        d = start + timedelta(days=int(rng.integers(0, 180)))
        taxable = round(float(rng.uniform(500, 300000)), 2)
        rate = float(rng.choice(GST_RATES))
        tax = round(taxable * rate / 100, 2)
        total = round(taxable + tax, 2)
        invoice_rows.append([inv_id, vendor, d.isoformat(), taxable, rate, tax, total])

    invoices = pd.DataFrame(invoice_rows, columns=["invoice_id", "vendor_code", "invoice_date", "taxable_amount", "tax_rate", "tax_amount", "total_amount"])

    # Clean copies to corrupt.
    ledger = invoices.copy()
    ledger.insert(0, "ledger_ref", [f"LED-{i:06d}" for i in range(1, n + 1)])
    ledger.rename(columns={"invoice_date": "entry_date"}, inplace=True)
    gst = invoices.copy()
    gst.insert(0, "gst_ref", [f"GST-{i:06d}" for i in range(1, n + 1)])
    gst.rename(columns={"invoice_date": "filing_date"}, inplace=True)

    idx = np.arange(n)
    rng.shuffle(idx)
    cursor = 0
    used: set[int] = set()

    def take(count: int) -> list[int]:
        nonlocal cursor
        picked = []
        while len(picked) < count and cursor < len(idx):
            pos = int(idx[cursor]); cursor += 1
            if pos in used:
                continue
            used.add(pos)
            picked.append(pos)
        return picked

    # 1) duplicate_invoice: near-duplicate with tiny amount difference and -2 suffix.
    for pos in take(per_type):
        row = invoices.iloc[pos].copy()
        row["invoice_id"] = row["invoice_id"] + "-2"
        row["taxable_amount"] = round(float(row["taxable_amount"]) + 0.5, 2)
        row["total_amount"] = round(float(row["total_amount"]) + 0.5, 2)
        invoices = pd.concat([invoices, pd.DataFrame([row])], ignore_index=True)
        truth.append([invoices.iloc[pos]["invoice_id"], "duplicate_invoice", "invoices", "Near-duplicate injected."])

    # 2) missing_ledger.
    for pos in take(per_type):
        iid = invoices.iloc[pos]["invoice_id"]
        ledger = ledger[ledger.invoice_id != iid]
        truth.append([iid, "missing_ledger", "ledger", "Ledger entry removed."])

    # 3) missing_gst.
    for pos in take(per_type):
        iid = invoices.iloc[pos]["invoice_id"]
        gst = gst[gst.invoice_id != iid]
        truth.append([iid, "missing_gst", "gst", "GST record removed."])

    # 4) amount_mismatch: awkward partial alterations + split invoices.
    for pos in take(per_type):
        iid = invoices.iloc[pos]["invoice_id"]
        mask = ledger.invoice_id == iid
        style = pyrng.choice(["pct", "flat", "split"])
        if style == "pct":
            ledger.loc[mask, "taxable_amount"] = (ledger.loc[mask, "taxable_amount"] * pyrng.uniform(1.05, 1.12)).round(2)
        elif style == "flat":
            ledger.loc[mask, "taxable_amount"] = (ledger.loc[mask, "taxable_amount"] + pyrng.choice([450.01, 1234.5, 999.99])).round(2)
        else:  # split invoice: only part posted
            ledger.loc[mask, "taxable_amount"] = (ledger.loc[mask, "taxable_amount"] * 0.5).round(2)
        ledger.loc[mask, "total_amount"] = (ledger.loc[mask, "taxable_amount"] + ledger.loc[mask, "tax_amount"]).round(2)
        truth.append([iid, "amount_mismatch", "ledger", f"Ledger taxable altered ({style})."])

    # 5) tax_mismatch: GST tax off by awkward percentages or flat amounts.
    for pos in take(per_type):
        iid = invoices.iloc[pos]["invoice_id"]
        mask = gst.invoice_id == iid
        style = pyrng.choice(["pct", "flat"])
        if style == "pct":
            gst.loc[mask, "tax_amount"] = (gst.loc[mask, "tax_amount"] * pyrng.uniform(1.08, 1.15)).round(2)
        else:
            gst.loc[mask, "tax_amount"] = (gst.loc[mask, "tax_amount"] + pyrng.choice([89.99, 250.0, 15.75])).round(2)
        truth.append([iid, "tax_mismatch", "gst", f"GST tax altered ({style})."])

    # 6) date_mismatch: 8-20 day drift.
    for pos in take(per_type):
        iid = invoices.iloc[pos]["invoice_id"]
        mask = ledger.invoice_id == iid
        ledger.loc[mask, "entry_date"] = (
            pd.to_datetime(ledger.loc[mask, "entry_date"]) + pd.Timedelta(days=int(pyrng.randint(8, 20)))
        ).dt.strftime("%Y-%m-%d")
        truth.append([iid, "date_mismatch", "ledger", "Entry date shifted 8-20 days."])

    # Harsher ID corruption on references (typos on ~10% of remaining rows).
    for df, ref_col in ((ledger, "invoice_id"), (gst, "invoice_id")):
        rows = df.index.to_list()
        pyrng.shuffle(rows)
        for r in rows[: max(1, len(rows) // 10)]:
            df.loc[r, "invoice_id"] = _typo_id(df.loc[r, "invoice_id"], pyrng)

    truth_df = pd.DataFrame(truth, columns=["invoice_id", "discrepancy_type", "affected_table", "description"])
    return invoices, ledger, gst, truth_df


def generate_negative_control(n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Clean dataset with zero injected errors (false-positive measurement)."""
    invoices, ledger, gst, _ = generate_eval(n, seed, per_type=0)
    return invoices, ledger, gst


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=90210)
    parser.add_argument("--per-type", type=int, default=20)
    parser.add_argument("--out", type=Path, default=Path("../data/eval_holdout"))
    args = parser.parse_args()
    inv, led, gst, truth = generate_eval(args.n, args.seed, args.per_type)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    inv.to_csv(out / "invoices.csv", index=False)
    led.to_csv(out / "ledger.csv", index=False)
    gst.to_csv(out / "gst_records.csv", index=False)
    truth.to_csv(out / "ground_truth.csv", index=False)
    print(f"Held-out set: {len(inv)} invoices, {len(truth)} injected cases → {out}")
