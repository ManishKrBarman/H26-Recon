import argparse
from datetime import date, timedelta
from pathlib import Path
import random
import sqlite3
import numpy as np
import pandas as pd

from . import config

ROOT = config.ROOT
DATA = config.DATA_DIR
DATA.mkdir(parents=True, exist_ok=True)

GST_RATES = [5.0, 12.0, 18.0, 28.0]
VENDOR_PREFIXES = ["ABC", "Nova", "Prime", "Shakti", "Vertex", "Apex", "Orbit", "Zenith", "Blue", "Green"]
VENDOR_SUFFIXES = ["Traders", "Industries", "Solutions", "Supplies", "Enterprises", "Technologies"]


def money(x: float) -> float:
    return round(float(x), 2)


def make_vendors(n: int) -> pd.DataFrame:
    rows = []
    for i in range(1, n + 1):
        name = f"{VENDOR_PREFIXES[(i-1) % len(VENDOR_PREFIXES)]} {VENDOR_SUFFIXES[((i-1)//len(VENDOR_PREFIXES)) % len(VENDOR_SUFFIXES)]} {i}"
        rows.append({
            "vendor_code": f"V{i:04d}",
            "vendor_name": name,
            "gstin": f"07ABCDE{i:04d}F1Z5",
        })
    return pd.DataFrame(rows)


def generate(n: int, seed: int, data_dir: Path | None = None) -> None:
    rng = np.random.default_rng(seed)
    random.seed(seed)
    data_dir = Path(data_dir) if data_dir else DATA
    data_dir.mkdir(parents=True, exist_ok=True)
    vendors = make_vendors(max(25, min(100, n // 10)))
    start = date(2026, 1, 1)

    invoice_rows, ledger_rows, gst_rows, truth = [], [], [], []
    for i in range(1, n + 1):
        vendor = vendors.iloc[int(rng.integers(0, len(vendors)))]
        inv_id = f"INV-{i:06d}"
        d = start + timedelta(days=int(rng.integers(0, 273)))
        taxable = money(rng.uniform(1000, 250000))
        rate = float(rng.choice(GST_RATES))
        tax = money(taxable * rate / 100)
        total = money(taxable + tax)
        invoice_rows.append([inv_id, vendor.vendor_code, d, taxable, rate, tax, total])
        ledger_rows.append([f"LED-{i:06d}", inv_id, vendor.vendor_code, d, taxable, tax, total])
        gst_rows.append([f"GST-{i:06d}", inv_id, vendor.vendor_code, d + timedelta(days=int(rng.integers(0, 4))), taxable, rate, tax])

    invoices = pd.DataFrame(invoice_rows, columns=["invoice_id","vendor_code","invoice_date","taxable_amount","tax_rate","tax_amount","total_amount"])
    ledger = pd.DataFrame(ledger_rows, columns=["ledger_ref","invoice_id","vendor_code","entry_date","taxable_amount","tax_amount","total_amount"])
    gst = pd.DataFrame(gst_rows, columns=["gst_ref","invoice_id","vendor_code","filing_date","taxable_amount","tax_rate","tax_amount"])

    # Controlled discrepancy injection: proportions are deliberately modest so the dataset remains mostly clean.
    idx = np.arange(n)
    rng.shuffle(idx)
    counts = {
        "duplicate_invoice": max(1, int(n * 0.02)),
        "missing_ledger": max(1, int(n * 0.02)),
        "missing_gst": max(1, int(n * 0.02)),
        "amount_mismatch": max(1, int(n * 0.02)),
        "tax_mismatch": max(1, int(n * 0.02)),
        "date_mismatch": max(1, int(n * 0.02)),
    }
    cursor = 0
    used = set()
    for kind, count in counts.items():
        for pos in idx[cursor:cursor+count]:
            if pos in used:
                continue
            used.add(int(pos))
            inv = invoices.iloc[pos]
            invoice_id = inv.invoice_id
            if kind == "duplicate_invoice":
                dup = invoices.iloc[[pos]].copy()
                dup["invoice_id"] = dup["invoice_id"].astype(str) + "-DUP"
                invoices = pd.concat([invoices, dup], ignore_index=True)
                truth.append([invoice_id, kind, "invoices", "Near-identical invoice intentionally duplicated."])
            elif kind == "missing_ledger":
                ledger = ledger[ledger.invoice_id != invoice_id]
                truth.append([invoice_id, kind, "ledger", "Ledger entry intentionally removed."])
            elif kind == "missing_gst":
                gst = gst[gst.invoice_id != invoice_id]
                truth.append([invoice_id, kind, "gst", "GST record intentionally removed."])
            elif kind == "amount_mismatch":
                mask = ledger.invoice_id == invoice_id
                ledger.loc[mask, "taxable_amount"] = ledger.loc[mask, "taxable_amount"] * 1.08
                ledger.loc[mask, "taxable_amount"] = ledger.loc[mask, "taxable_amount"].round(2)
                ledger.loc[mask, "total_amount"] = (ledger.loc[mask, "taxable_amount"] + ledger.loc[mask, "tax_amount"]).round(2)
                truth.append([invoice_id, kind, "ledger", "Ledger taxable amount intentionally altered by 8%."])
            elif kind == "tax_mismatch":
                mask = gst.invoice_id == invoice_id
                gst.loc[mask, "tax_amount"] = (gst.loc[mask, "tax_amount"] * 1.10).round(2)
                truth.append([invoice_id, kind, "gst", "GST tax amount intentionally altered by 10%."])
            elif kind == "date_mismatch":
                mask = ledger.invoice_id == invoice_id
                ledger.loc[mask, "entry_date"] = pd.to_datetime(ledger.loc[mask, "entry_date"]) + pd.Timedelta(days=15)
                ledger.loc[mask, "entry_date"] = ledger.loc[mask, "entry_date"].apply(lambda x: x.date() if hasattr(x, "date") else x)
                truth.append([invoice_id, kind, "ledger", "Ledger date intentionally shifted by 15 days."])
        cursor += count

    invoices.to_csv(data_dir / "invoices.csv", index=False)
    ledger.to_csv(data_dir / "ledger.csv", index=False)
    gst.to_csv(data_dir / "gst_records.csv", index=False)
    vendors.to_csv(data_dir / "vendors.csv", index=False)
    pd.DataFrame(truth, columns=["invoice_id","discrepancy_type","affected_table","description"]).to_csv(data_dir / "ground_truth.csv", index=False)
    print(f"Generated {len(invoices)} invoices, {len(ledger)} ledger rows, {len(gst)} GST rows and {len(truth)} ground-truth cases in {data_dir}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.n, args.seed)
