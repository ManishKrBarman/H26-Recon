"""ReconAI Phase 2: three-way reconciliation engine.

The engine reconciles purchase invoices against accounting ledger and GST records,
then emits explainable exception cases. It is deliberately deterministic at this
stage; ML/anomaly detection is added in a later phase.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional
import re

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

MONEY_TOLERANCE = 1.00
DATE_TOLERANCE_DAYS = 7
MATCH_THRESHOLD = 55.0


def normalize_id(value: object) -> str:
    """Normalize invoice/reference identifiers for comparison."""
    if pd.isna(value):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(value).upper())


def base_invoice_id(value: object) -> str:
    """Remove synthetic duplicate suffixes such as -DUP."""
    if pd.isna(value):
        return ""
    value = str(value).upper()
    value = re.sub(r"[-_/ ]DUP(?:LICATE)?$", "", value)
    return value


def money_similarity(a: float, b: float) -> float:
    if pd.isna(a) or pd.isna(b):
        return 0.0
    scale = max(abs(float(a)), abs(float(b)), 1.0)
    return max(0.0, 100.0 - abs(float(a) - float(b)) / scale * 100.0)


def date_similarity(a: object, b: object) -> float:
    if pd.isna(a) or pd.isna(b):
        return 0.0
    days = abs((pd.Timestamp(a) - pd.Timestamp(b)).days)
    return max(0.0, 100.0 - min(days, 30) / 30.0 * 100.0)


def _candidate_score(inv: pd.Series, row: pd.Series, id_col: str, date_col: str,
                    tax_col: Optional[str] = None) -> float:
    id_score = ratio(normalize_id(base_invoice_id(inv["invoice_id"])), normalize_id(base_invoice_id(row[id_col])))
    vendor_score = ratio(str(inv["vendor_code"]), str(row["vendor_code"]))
    row_total = row["total_amount"] if "total_amount" in row.index else float(row["taxable_amount"]) + float(row["tax_amount"])
    amount_score = money_similarity(inv["total_amount"], row_total)
    date_score = date_similarity(inv["invoice_date"], row[date_col])
    tax_score = 100.0
    if tax_col:
        tax_score = money_similarity(inv["tax_amount"], row[tax_col])

    # ID/vendor are identity signals; amount/date/tax help resolve imperfect IDs.
    return round(
        id_score * 0.45
        + vendor_score * 0.15
        + amount_score * 0.20
        + date_score * 0.10
        + tax_score * 0.10,
        2,
    )


def best_match(inv: pd.Series, candidates: pd.DataFrame, id_col: str,
                date_col: str, tax_col: Optional[str] = None) -> tuple[Optional[pd.Series], float]:
    if candidates.empty:
        return None, 0.0

    # First narrow by vendor when possible. If no vendor candidate exists, fall back.
    vendor_candidates = candidates[candidates.vendor_code == inv.vendor_code]
    pool = vendor_candidates if not vendor_candidates.empty else candidates

    scored = []
    inv_norm = normalize_id(base_invoice_id(inv["invoice_id"]))
    for _, row in pool.iterrows():
        id_score = ratio(inv_norm, normalize_id(base_invoice_id(row[id_col])))
        # Identity must be plausible before financial/date similarities can match a row.
        # This prevents a missing invoice from being incorrectly paired with an unrelated
        # transaction from the same vendor.
        if id_score < 94.0:
            continue
        score = _candidate_score(inv, row, id_col, date_col, tax_col)
        scored.append((score, row))
    if not scored:
        return None, 0.0
    scored.sort(key=lambda x: x[0], reverse=True)
    score, row = scored[0]
    if score < MATCH_THRESHOLD:
        return None, score
    return row, score


def detect_duplicate_invoices(invoices: pd.DataFrame) -> set[str]:
    """Return canonical invoice IDs with duplicate/near-duplicate invoice rows."""
    dup_ids: set[str] = set()

    # Exact normalized/base identifier duplicates.
    base = invoices["invoice_id"].map(base_invoice_id)
    for key, group in invoices.groupby(base):
        if key and len(group) > 1:
            dup_ids.add(key)

    # Near-duplicate fingerprint for rows with different identifiers.
    work = invoices.copy()
    work["_norm_vendor"] = work["vendor_code"].astype(str)
    for _, group in work.groupby("_norm_vendor"):
        if len(group) < 2:
            continue
        rows = list(group.iterrows())
        for i in range(len(rows)):
            _, a = rows[i]
            for j in range(i + 1, len(rows)):
                _, b = rows[j]
                if abs(float(a.total_amount) - float(b.total_amount)) > MONEY_TOLERANCE:
                    continue
                if abs((pd.Timestamp(a.invoice_date) - pd.Timestamp(b.invoice_date)).days) > 3:
                    continue
                id_sim = ratio(normalize_id(a.invoice_id), normalize_id(b.invoice_id))
                if id_sim >= 85:
                    dup_ids.add(base_invoice_id(a.invoice_id))
                    dup_ids.add(base_invoice_id(b.invoice_id))
    return dup_ids


def reconcile(invoices: pd.DataFrame, ledger: pd.DataFrame, gst: pd.DataFrame) -> pd.DataFrame:
    """Run deterministic three-way reconciliation and return one row per invoice."""
    invoices = invoices.copy()
    ledger = ledger.copy()
    gst = gst.copy()
    for df, cols in [
        (invoices, ["invoice_date"]),
        (ledger, ["entry_date"]),
        (gst, ["filing_date"]),
    ]:
        for col in cols:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    dup_ids = detect_duplicate_invoices(invoices)
    results = []

    for _, inv in invoices.iterrows():
        base_id = base_invoice_id(inv.invoice_id)
        lrow, lscore = best_match(inv, ledger, "invoice_id", "entry_date", "tax_amount")
        grow, gscore = best_match(inv, gst, "invoice_id", "filing_date", "tax_amount")

        issues: list[str] = []
        evidence: list[str] = []

        if base_id in dup_ids:
            issues.append("duplicate_invoice")
            evidence.append("Multiple invoice rows share the same/near-identical transaction fingerprint.")
        if lrow is None:
            issues.append("missing_ledger")
            evidence.append("No sufficiently confident accounting-ledger match was found.")
        if grow is None:
            issues.append("missing_gst")
            evidence.append("No sufficiently confident GST-record match was found.")

        if lrow is not None:
            amount_delta = round(float(lrow.taxable_amount) - float(inv.taxable_amount), 2)
            if abs(amount_delta) > MONEY_TOLERANCE:
                issues.append("amount_mismatch")
                evidence.append(f"Ledger taxable amount differs by ₹{abs(amount_delta):,.2f}.")

            date_delta = abs((pd.Timestamp(lrow.entry_date) - pd.Timestamp(inv.invoice_date)).days)
            if date_delta > DATE_TOLERANCE_DAYS:
                issues.append("date_mismatch")
                evidence.append(f"Ledger date differs from invoice date by {date_delta} days.")

        if grow is not None:
            tax_delta = round(float(grow.tax_amount) - float(inv.tax_amount), 2)
            if abs(tax_delta) > MONEY_TOLERANCE:
                issues.append("tax_mismatch")
                evidence.append(f"GST tax amount differs by ₹{abs(tax_delta):,.2f}.")

        # Confidence reflects the weakest side of the three-way match when present.
        present_scores = [s for s in (lscore, gscore) if s > 0]
        confidence = round(min(present_scores) if present_scores else 0.0, 2)

        # Financial exposure is based on detected amount/tax discrepancies.
        exposure = 0.0
        if lrow is not None:
            exposure += abs(float(lrow.taxable_amount) - float(inv.taxable_amount))
        if grow is not None:
            exposure += abs(float(grow.tax_amount) - float(inv.tax_amount))
        if "duplicate_invoice" in issues:
            exposure = max(exposure, float(inv.total_amount))

        severity = "LOW"
        if issues:
            if exposure >= 100000 or len(issues) >= 2:
                severity = "HIGH"
            elif exposure >= 25000 or any(x in issues for x in ("missing_ledger", "missing_gst", "tax_mismatch")):
                severity = "MEDIUM"

        results.append({
            "invoice_id": inv.invoice_id,
            "canonical_invoice_id": base_id,
            "vendor_code": inv.vendor_code,
            "invoice_date": inv.invoice_date.date().isoformat() if not pd.isna(inv.invoice_date) else None,
            "ledger_ref": None if lrow is None else lrow.ledger_ref,
            "gst_ref": None if grow is None else grow.gst_ref,
            "ledger_match_confidence": round(lscore, 2),
            "gst_match_confidence": round(gscore, 2),
            "match_confidence": confidence,
            "issues": ";".join(issues),
            "issue_count": len(issues),
            "severity": severity,
            "financial_exposure": round(exposure, 2),
            "evidence": " ".join(evidence),
        })

    return pd.DataFrame(results)


def load_data(data_dir: Path = DATA) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir.mkdir(parents=True, exist_ok=True)
    inv_path = data_dir / "invoices.csv"
    led_path = data_dir / "ledger.csv"
    gst_path = data_dir / "gst_records.csv"

    # If data files are missing (e.g. fresh clone / fresh Docker container), generate initial demo dataset
    if not (inv_path.exists() and led_path.exists() and gst_path.exists()):
        from .generate_data import generate
        generate(100, seed=42)

    return (
        pd.read_csv(inv_path),
        pd.read_csv(led_path),
        pd.read_csv(gst_path),
    )


def run_and_save(data_dir: Path = DATA) -> pd.DataFrame:
    invoices, ledger, gst = load_data(data_dir)
    result = reconcile(invoices, ledger, gst)
    out = data_dir / "reconciliation_results.csv"
    result.to_csv(out, index=False)
    return result


if __name__ == "__main__":
    result = run_and_save()
    flagged = result[result.issue_count > 0]
    print(f"Reconciled {len(result)} invoice rows")
    print(f"Flagged {len(flagged)} invoice rows")
    print(flagged[["invoice_id", "issues", "severity", "financial_exposure", "match_confidence"]].head(20).to_string(index=False))
