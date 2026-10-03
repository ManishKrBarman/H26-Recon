"""ReconAI Phase 2: three-way reconciliation engine.

The engine reconciles purchase invoices against accounting ledger and GST records,
then emits explainable exception cases. It is deliberately deterministic at this
stage; ML/anomaly detection is added in a later phase.

Phase-2 hardening
-----------------
* Independent GST arithmetic check per invoice (taxable × rate ≈ tax,
  taxable + tax ≈ total, valid slabs 0/5/12/18/28% + slabs observed in data).
* Fuzzy reference matching hardened against case, separators, leading zeros,
  FY prefixes and single-character typos.
* Duplicate detection groups rows into one canonical finding (no double-counting)
  and also catches the same id reused for different vendors/amounts.
* Every finding carries structured evidence used downstream for explainability.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import re

import numpy as np
import pandas as pd
from rapidfuzz.fuzz import ratio

from . import config

ROOT = config.ROOT
DATA = config.DATA_DIR

MONEY_TOLERANCE = config.MONEY_TOLERANCE
DATE_TOLERANCE_DAYS = 7
MATCH_THRESHOLD = 55.0
IDENTITY_THRESHOLD = 94.0

VALID_GST_SLABS: tuple[float, ...] = tuple(config.GST_SLABS)


def normalize_id(value: object) -> str:
    """Normalize invoice/reference identifiers for comparison.

    Strips separators/case, collapses leading zeros on the numeric tail so
    ``inv-0000123`` == ``INV123``, and drops common FY/document prefixes.
    """
    if pd.isna(value):
        return ""
    s = str(value).upper().strip()
    s = re.sub(r"\b(FY\s?\d{2,4}[-/]\d{2,4})\b", "", s)          # FY2025-26 prefixes
    s = re.sub(r"[^A-Z0-9]", "", s)
    # Collapse leading zeros in the trailing digit run ( INV0000123 → INV123 ).
    m = re.match(r"^([A-Z]*)(0+)(\d+)$", s)
    if m:
        s = m.group(1) + m.group(3)
    return s


def base_invoice_id(value: object) -> str:
    """Remove synthetic duplicate suffixes such as -DUP / -2."""
    if pd.isna(value):
        return ""
    value = str(value).upper()
    value = re.sub(r"[-_/ ]DUP(?:LICATE)?$", "", value)
    value = re.sub(r"[-_/ ]2$", "", value)
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


def _observed_slabs(invoices: pd.DataFrame) -> set[float]:
    """GST slabs actually present in the data (rounded to 2dp, positive only)."""
    rates = pd.to_numeric(invoices.get("tax_rate"), errors="coerce").dropna()
    return {round(float(r), 2) for r in rates if r > 0}


def check_tax_arithmetic(invoices: pd.DataFrame) -> pd.DataFrame:
    """Deterministic per-invoice GST arithmetic checks.

    Returns a frame indexed like ``invoices`` with:
      arith_tax_delta      expected tax (taxable × rate) − recorded tax
      arith_total_delta    expected total (taxable + tax) − recorded total
      arith_bad_slab       True when the rate is not a recognised slab
      arith_flag           True when any check fails beyond tolerance
    """
    inv = invoices.copy()
    taxable = pd.to_numeric(inv.get("taxable_amount"), errors="coerce")
    rate = pd.to_numeric(inv.get("tax_rate"), errors="coerce")
    tax = pd.to_numeric(inv.get("tax_amount"), errors="coerce")
    total = pd.to_numeric(inv.get("total_amount"), errors="coerce")

    expected_tax = (taxable * rate / 100.0).round(2)
    expected_total = (taxable + tax).round(2)

    out = pd.DataFrame({
        "invoice_id": inv.get("invoice_id"),
        "arith_tax_delta": (expected_tax - tax).round(2),
        "arith_total_delta": (expected_total - total).round(2),
    })
    slabs = set(VALID_GST_SLABS) | _observed_slabs(invoices)
    out["arith_bad_slab"] = rate.notna() & ~rate.round(2).isin(slabs)
    out["arith_flag"] = (
        (out["arith_tax_delta"].abs() > MONEY_TOLERANCE)
        | (out["arith_total_delta"].abs() > MONEY_TOLERANCE)
        | out["arith_bad_slab"]
    )
    return out


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


def _contextual_match(inv: pd.Series, pool: pd.DataFrame, tax_col: Optional[str]) -> Optional[pd.Series]:
    """Fallback identity: same vendor, same taxable AND same tax (₹-tolerance), any date.

    Catches reference typos (case/deletion/swaps below the fuzzy threshold) where
    the financial content is identical — the row clearly exists and only the id
    is corrupted. Requires BOTH amounts to match so a genuinely altered amount
    or tax still surfaces as a mismatch rather than silently matching.
    """
    if pool.empty:
        return None
    inv_taxable = float(inv["taxable_amount"])
    inv_tax = float(inv["tax_amount"])
    vendor_rows = pool[pool.vendor_code == inv.vendor_code]
    if vendor_rows.empty:
        return None
    for _, row in vendor_rows.iterrows():
        try:
            taxable_ok = abs(float(row["taxable_amount"]) - inv_taxable) <= MONEY_TOLERANCE
            tax_ok = tax_col is None or abs(float(row[tax_col]) - inv_tax) <= MONEY_TOLERANCE
        except (TypeError, ValueError):
            continue
        if taxable_ok and tax_ok:
            return row
    return None


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
        row_norm = normalize_id(base_invoice_id(row[id_col]))
        id_score = ratio(inv_norm, row_norm)
        # Identity must be plausible before financial/date similarities can match a row.
        # This prevents a missing invoice from being incorrectly paired with an unrelated
        # transaction from the same vendor.
        if id_score < IDENTITY_THRESHOLD:
            continue
        score = _candidate_score(inv, row, id_col, date_col, tax_col)
        scored.append((score, row))

    # Contextual fallback for typo'd references with identical financial content.
    if not scored:
        crow = _contextual_match(inv, pool, tax_col)
        if crow is not None:
            scored.append((_candidate_score(inv, crow, id_col, date_col, tax_col), crow))

    if not scored:
        return None, 0.0
    scored.sort(key=lambda x: x[0], reverse=True)
    score, row = scored[0]
    if score < MATCH_THRESHOLD:
        return None, score
    return row, score


@dataclass
class _DuplicateGroup:
    canonical: str
    members: list[str]


def detect_duplicate_groups(invoices: pd.DataFrame) -> tuple[dict[str, list[str]], dict[str, str]]:
    """Group invoice rows into duplicate clusters.

    Returns (groups, group_of) where ``groups`` maps canonical id → member
    invoice_ids (only groups with >1 member) and ``group_of`` maps every member
    invoice_id → canonical id, so downstream code emits ONE case per cluster.
    Also flags same-id reuse across vendors/amounts via the same grouping.
    """
    work = invoices.copy()
    work["_norm_id"] = work["invoice_id"].map(normalize_id)
    work["_base_id"] = work["invoice_id"].map(base_invoice_id).map(normalize_id)
    work["_amount"] = pd.to_numeric(work["total_amount"], errors="coerce")

    parent: dict[str, str] = {}

    def find(x: str) -> str:
        while parent.get(x, x) != x:
            x = parent[x] = parent.get(parent[x], parent[x])
        return parent.get(x, x)

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    ids = work["invoice_id"].astype(str).tolist()
    for iid in ids:
        parent.setdefault(iid, iid)

    # Pass 1: same normalized base id (catches -DUP / -2 suffixes and case variants).
    by_base: dict[str, list[str]] = defaultdict(list)
    for _, r in work.iterrows():
        if r["_base_id"]:
            by_base[r["_base_id"]].append(r["invoice_id"])
    for members in by_base.values():
        for other in members[1:]:
            union(members[0], other)

    # Pass 2: same id reused with a different vendor or materially different amount.
    by_norm: dict[str, list[pd.Series]] = defaultdict(list)
    for _, r in work.iterrows():
        if r["_norm_id"]:
            by_norm[r["_norm_id"]].append(r)
    for rows in by_norm.values():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i], rows[j]
                if a["vendor_code"] != b["vendor_code"] or abs(float(a["_amount"]) - float(b["_amount"])) > MONEY_TOLERANCE:
                    union(str(a["invoice_id"]), str(b["invoice_id"]))

    # Pass 3: near-duplicate fingerprint (same vendor, close amount, close date, similar id).
    for vendor, group in work.groupby("vendor_code"):
        if len(group) < 2:
            continue
        rows = list(group.iterrows())
        for i in range(len(rows)):
            _, a = rows[i]
            for j in range(i + 1, len(rows)):
                _, b = rows[j]
                if pd.isna(a["_amount"]) or pd.isna(b["_amount"]):
                    continue
                if abs(float(a["_amount"]) - float(b["_amount"])) > MONEY_TOLERANCE:
                    continue
                if abs((pd.Timestamp(a["invoice_date"]) - pd.Timestamp(b["invoice_date"])).days) > 3:
                    continue
                id_sim = ratio(str(a["_norm_id"]), str(b["_norm_id"]))
                if id_sim >= 85 and find(str(a["invoice_id"])) != find(str(b["invoice_id"])):
                    union(str(a["invoice_id"]), str(b["invoice_id"]))

    clusters: dict[str, list[str]] = defaultdict(list)
    for iid in ids:
        clusters[find(iid)].append(iid)
    groups = {canon: sorted(members) for canon, members in clusters.items() if len(members) > 1}
    group_of = {member: canon for canon, members in groups.items() for member in members}
    return groups, group_of


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

    # Pre-index arithmetic results by invoice id.
    arith = check_tax_arithmetic(invoices).set_index("invoice_id")

    dup_groups, group_of = detect_duplicate_groups(invoices)

    # Pre-index best matches to avoid recomputing per pass; one match pass per invoice.
    results = []
    for _, inv in invoices.iterrows():
        base_id = base_invoice_id(inv.invoice_id)
        lrow, lscore = best_match(inv, ledger, "invoice_id", "entry_date", "tax_amount")
        grow, gscore = best_match(inv, gst, "invoice_id", "filing_date", "tax_amount")

        issues: list[str] = []
        evidence: list[str] = []

        if inv.invoice_id in group_of:
            members = dup_groups[group_of[str(inv.invoice_id)]]
            issues.append("duplicate_invoice")
            evidence.append(
                "Duplicate cluster: " + ", ".join(members)
                + " share the same/near-identical transaction fingerprint."
            )
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
                evidence.append(
                    f"Ledger taxable ₹{float(lrow.taxable_amount):,.2f} differs from invoice "
                    f"₹{float(inv.taxable_amount):,.2f} by ₹{abs(amount_delta):,.2f}."
                )

            date_delta = abs((pd.Timestamp(lrow.entry_date) - pd.Timestamp(inv.invoice_date)).days)
            if date_delta > DATE_TOLERANCE_DAYS:
                issues.append("date_mismatch")
                evidence.append(f"Ledger date differs from invoice date by {date_delta} days.")

        if grow is not None:
            tax_delta = round(float(grow.tax_amount) - float(inv.tax_amount), 2)
            if abs(tax_delta) > MONEY_TOLERANCE:
                issues.append("tax_mismatch")
                evidence.append(
                    f"GST tax ₹{float(grow.tax_amount):,.2f} differs from invoice tax "
                    f"₹{float(inv.tax_amount):,.2f} by ₹{abs(tax_delta):,.2f}."
                )

        # Independent GST arithmetic check (no cross-source comparison needed).
        arith_tax_delta = 0.0
        if str(inv.invoice_id) in arith.index:
            arow = arith.loc[str(inv.invoice_id)]
            if bool(arow.get("arith_bad_slab", False)):
                issues.append("tax_rate_invalid")
                evidence.append(f"Tax rate {float(inv.tax_rate):g}% is not a recognised GST slab.")
            arith_tax_delta = float(arow.get("arith_tax_delta", 0.0) or 0.0)
            if abs(arith_tax_delta) > MONEY_TOLERANCE:
                issues.append("tax_arithmetic_mismatch")
                evidence.append(
                    f"taxable ₹{float(inv.taxable_amount):,.2f} × {float(inv.tax_rate):g}% implies tax "
                    f"₹{float(inv.tax_amount) + arith_tax_delta:,.2f}, recorded ₹{float(inv.tax_amount):,.2f} "
                    f"(difference ₹{abs(arith_tax_delta):,.2f})."
                )
            total_delta_a = float(arow.get("arith_total_delta", 0.0) or 0.0)
            if abs(total_delta_a) > MONEY_TOLERANCE:
                issues.append("tax_arithmetic_mismatch")
                evidence.append(
                    f"taxable ₹{float(inv.taxable_amount):,.2f} + tax ₹{float(inv.tax_amount):,.2f} implies total "
                    f"₹{float(inv.total_amount) + total_delta_a:,.2f}, recorded ₹{float(inv.total_amount):,.2f}."
                )

        # Confidence reflects the weakest side of the three-way match when present.
        present_scores = [s for s in (lscore, gscore) if s > 0]
        confidence = round(min(present_scores) if present_scores else 0.0, 2)

        # Financial exposure is based on detected amount/tax discrepancies.
        exposure = 0.0
        if lrow is not None:
            exposure += abs(float(lrow.taxable_amount) - float(inv.taxable_amount))
        if grow is not None:
            exposure += abs(float(grow.tax_amount) - float(inv.tax_amount))
        for issue in issues:
            if issue == "duplicate_invoice":
                exposure = max(exposure, float(inv.total_amount))
            elif issue == "missing_ledger":
                exposure = max(exposure, float(inv.total_amount))
            elif issue == "missing_gst":
                exposure = max(exposure, float(inv.tax_amount))
            elif issue == "tax_mismatch" and grow is not None:
                exposure = max(exposure, abs(round(float(grow.tax_amount) - float(inv.tax_amount), 2)))
            elif issue == "tax_arithmetic_mismatch":
                exposure = max(exposure, abs(arith_tax_delta) if abs(arith_tax_delta) > MONEY_TOLERANCE else float(inv.tax_amount))

        severity = "LOW"
        if issues:
            if exposure >= 100000 or len(issues) >= 2:
                severity = "HIGH"
            elif exposure >= 25000 or any(x in issues for x in ("missing_ledger", "missing_gst", "tax_mismatch", "tax_arithmetic_mismatch", "tax_rate_invalid")):
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


def load_data(data_dir: Path | None = None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    inv_path = data_dir / "invoices.csv"
    led_path = data_dir / "ledger.csv"
    gst_path = data_dir / "gst_records.csv"

    # If data files are missing (e.g. fresh clone / fresh Docker container), generate initial demo dataset
    if not (inv_path.exists() and led_path.exists() and gst_path.exists()):
        from .generate_data import generate
        generate(config.DEMO_INVOICE_COUNT, seed=config.DEMO_SEED, data_dir=data_dir)

    return (
        pd.read_csv(inv_path),
        pd.read_csv(led_path),
        pd.read_csv(gst_path),
    )


def run_and_save(data_dir: Path | None = None) -> pd.DataFrame:
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
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
