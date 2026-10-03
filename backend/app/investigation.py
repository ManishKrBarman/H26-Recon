from __future__ import annotations

import hashlib
import math
import re
import sqlite3
from pathlib import Path
from typing import Dict, List

import pandas as pd

ISSUE_META = {
    "duplicate_invoice": {
        "label": "Possible duplicate invoice",
        "category": "DUPLICATE",
        "action": "Review the linked invoice records and confirm whether the transaction was booked more than once.",
    },
    "missing_ledger": {
        "label": "Missing accounting ledger record",
        "category": "MISSING_RECORD",
        "action": "Check the accounting ledger and posting period for an omitted or delayed entry.",
    },
    "missing_gst": {
        "label": "Missing GST record",
        "category": "MISSING_RECORD",
        "action": "Check GST filing/reference records and confirm whether the invoice was omitted or filed in another period.",
    },
    "amount_mismatch": {
        "label": "Amount mismatch",
        "category": "AMOUNT",
        "action": "Compare the taxable values in the invoice and ledger and verify the source document.",
    },
    "tax_mismatch": {
        "label": "Tax amount mismatch",
        "category": "TAX",
        "action": "Recalculate tax from the taxable value and rate, then compare with the recorded GST amount.",
    },
    "date_mismatch": {
        "label": "Date mismatch",
        "category": "TIMING",
        "action": "Review the invoice and posting dates to determine whether this is a valid timing/period difference.",
    },
    "tax_arithmetic_mismatch": {
        "label": "GST arithmetic inconsistency",
        "category": "TAX",
        "action": "Recompute tax from taxable value × rate and verify the invoice total; correct the source document.",
    },
    "tax_rate_invalid": {
        "label": "Invalid GST rate",
        "category": "TAX",
        "action": "Verify the applicable GST slab (0/5/12/18/28%) for this supply and correct the rate.",
    },
}

PRIORITY_WEIGHTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}

# Per-issue confidence weights over (match certainty, evidence strength, issue base rate).
ISSUE_EVIDENCE_WEIGHTS = {
    "duplicate_invoice": 0.95,
    "missing_ledger": 0.9,
    "missing_gst": 0.9,
    "amount_mismatch": 0.92,
    "tax_mismatch": 0.9,
    "date_mismatch": 0.75,
    "tax_arithmetic_mismatch": 0.97,
    "tax_rate_invalid": 0.99,
}


def _safe_float(value, default=0.0) -> float:
    try:
        x = float(value)
        return default if math.isnan(x) else x
    except (TypeError, ValueError):
        return default


def _issue_list(value) -> List[str]:
    if pd.isna(value) or not str(value).strip():
        return []
    return [x.strip() for x in re.split(r"[;|]", str(value)) if x.strip()]


def stable_case_id(row: pd.Series, issue: str) -> str:
    """Deterministic case id: survives pipeline reruns and data reordering.

    Keyed on the issue type plus the source references that identify the
    finding (invoice, vendor, ledger and GST refs). Two runs over the same
    data always produce the same id; changed data produces a new id, and the
    review-persistence layer reports the old decision as orphaned.
    """
    parts = [
        issue,
        str(row.get("invoice_id", "") or ""),
        str(row.get("canonical_invoice_id", row.get("invoice_id", "")) or ""),
        str(row.get("vendor_code", "") or ""),
        str(row.get("ledger_ref", "") or ""),
        str(row.get("gst_ref", "") or ""),
    ]
    digest = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12].upper()
    return f"CASE-{digest}"


def _priority_score(row: pd.Series, issue: str) -> float:
    severity = PRIORITY_WEIGHTS.get(str(row.get("severity", "LOW")).upper(), 1)
    confidence = _safe_float(row.get("match_confidence"), 0.0)
    exposure = _safe_float(row.get("financial_exposure"), 0.0)
    # Bounded financial component keeps huge transactions from overwhelming the score.
    financial_component = min(math.log10(max(exposure, 0.0) + 1) / 7.0, 1.0)
    confidence_component = max(0.0, min(confidence / 100.0, 1.0))
    issue_component = 1.0 if issue in {"duplicate_invoice", "tax_mismatch", "amount_mismatch",
                                       "tax_arithmetic_mismatch", "tax_rate_invalid"} else 0.75
    return round(100 * (0.45 * (severity / 3) + 0.30 * financial_component + 0.15 * confidence_component + 0.10 * issue_component), 2)


def _fmt_money(x: float) -> str:
    return f"₹{_safe_float(x):,.2f}"


def _split_evidence(raw: str) -> Dict[str, List[str]]:
    """Split reconciliation evidence strings into per-issue evidence lists."""
    out: Dict[str, List[str]] = {}
    text = str(raw or "").strip()
    if not text:
        return out
    chunks = [c.strip() for c in re.split(r"(?=\.\s+[A-Z₤₹])|(?<=\.)\s+(?=[A-Z₹])", text) if c.strip()]
    mapping = {
        "duplicate": "duplicate_invoice",
        "ledger": "missing_ledger",
        "GST-record": "missing_gst",
        "GST": "missing_gst",
        "taxable ₹": "amount_mismatch",
        "GST tax": "tax_mismatch",
        "date": "date_mismatch",
        "× implies": "tax_arithmetic_mismatch",
        "+ tax": "tax_arithmetic_mismatch",
        "slab": "tax_rate_invalid",
    }
    for chunk in chunks:
        assigned = "general"
        for key, issue in mapping.items():
            if key.lower() in chunk.lower():
                assigned = issue
                break
        out.setdefault(assigned, []).append(chunk)
    return out


def _issue_evidence(row: pd.Series, issue: str) -> List[str]:
    buckets = _split_evidence(str(row.get("evidence", "")))
    items: List[str] = []
    items.extend(buckets.get(issue, []))
    items.extend(buckets.get("general", []))
    if not items:
        meta = ISSUE_META.get(issue, {})
        items = [f"Flag raised by deterministic {issue} check."]
    return items


def _exposure(row: pd.Series, issue: str) -> float:
    existing = _safe_float(row.get("financial_exposure"), 0.0)
    if existing > 0:
        return round(existing, 2)
    if issue == "missing_ledger":
        return round(_safe_float(row.get("invoice_total_amount"), 0.0), 2)
    if issue == "missing_gst":
        return round(_safe_float(row.get("invoice_tax_amount"), 0.0), 2)
    return 0.0


def _compute_financial_impact(row: pd.Series, issue: str) -> Dict:
    """Per-issue impact: over-stated credit vs understated booking, in ₹."""
    invoice_tax = _safe_float(row.get("invoice_tax_amount"), 0.0)
    ledger_taxable = _safe_float(row.get("ledger_taxable_amount"), 0.0)
    invoice_taxable = _safe_float(row.get("invoice_taxable_amount"), 0.0)
    gst_tax = _safe_float(row.get("gst_tax_amount"), 0.0)
    invoice_total = _safe_float(row.get("invoice_total_amount"), 0.0)

    if issue == "amount_mismatch":
        delta = abs(ledger_taxable - invoice_taxable) if ledger_taxable else 0.0
        return {
            "type": "AMOUNT",
            "amount": round(delta, 2),
            "explanation": f"Taxable value differs between invoice and ledger by {_fmt_money(delta)}; affects booked expense and ITC proportionality.",
        }
    if issue in ("tax_mismatch", "tax_arithmetic_mismatch"):
        delta = abs(gst_tax - invoice_tax) if gst_tax else 0.0
        if issue == "tax_arithmetic_mismatch" and not delta:
            delta = invoice_tax  # recorded tax itself is inconsistent with rate
        return {
            "type": "TAX",
            "amount": round(delta, 2),
            "explanation": f"Tax discrepancy of {_fmt_money(delta)}; potential excess ITC claim or under-reported output tax.",
        }
    if issue == "missing_gst":
        return {
            "type": "TAX",
            "amount": round(invoice_tax, 2),
            "explanation": f"No GST record found; {_fmt_money(invoice_tax)} of input tax credit at risk of reversal if not supplier-reported.",
        }
    if issue == "missing_ledger":
        return {
            "type": "BOOKING",
            "amount": round(invoice_total, 2),
            "explanation": f"No ledger entry linked; {_fmt_money(invoice_total)} booking requires verification (expense/asset and payable).",
        }
    if issue == "duplicate_invoice":
        return {
            "type": "BOOKING",
            "amount": round(invoice_total, 2),
            "explanation": f"Duplicate booking risk: up to {_fmt_money(invoice_total)} may be paid/claimed twice.",
        }
    if issue == "date_mismatch":
        return {
            "type": "TIMING",
            "amount": 0.0,
            "explanation": "Timing difference only; direct monetary impact limited to period allocation and interest exposure.",
        }
    if issue == "tax_rate_invalid":
        return {
            "type": "TAX",
            "amount": round(invoice_tax, 2),
            "explanation": f"Non-standard rate applied; {_fmt_money(invoice_tax)} of tax requires recomputation at the correct slab.",
        }
    return {"type": "OTHER", "amount": 0.0, "explanation": "Impact assessment not available for this issue type."}


def build_investigation_cases(reconciliation: pd.DataFrame, invoices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Turn row-level reconciliation flags into structured investigation cases."""
    df = reconciliation.copy()
    if invoices is not None:
        inv_cols = ["invoice_id", "vendor_code", "invoice_date", "taxable_amount", "tax_rate", "tax_amount", "total_amount"]
        inv_cols = [c for c in inv_cols if c in invoices.columns]
        inv = invoices[inv_cols].drop_duplicates("invoice_id").rename(columns={
            "taxable_amount": "invoice_taxable_amount",
            "tax_rate": "invoice_tax_rate",
            "tax_amount": "invoice_tax_amount",
            "total_amount": "invoice_total_amount",
        })
        df = df.merge(inv, on="invoice_id", how="left")
    else:
        for col in ("invoice_taxable_amount", "invoice_tax_rate", "invoice_tax_amount", "invoice_total_amount"):
            df[col] = 0.0

    rows: List[Dict] = []
    seen_case_ids: Dict[str, int] = {}
    for _, row in df.iterrows():
        issues = _issue_list(row.get("issues"))
        if not issues:
            continue

        # Duplicate clusters: emit ONE case per cluster (the canonical id), not one per row.
        dup_members: List[str] = []
        if "duplicate_invoice" in issues:
            m = re.search(r"Duplicate cluster: ([^.]*)\.", str(row.get("evidence", "")))
            if m:
                dup_members = [x.strip() for x in m.group(1).split(",") if x.strip()]
        if "duplicate_invoice" in issues and dup_members and str(row["invoice_id"]) != dup_members[0]:
            continue  # secondary cluster member: covered by the canonical case

        for issue in issues:
            if issue == "duplicate_invoice" and not dup_members:
                continue
            meta = ISSUE_META.get(issue, {
                "label": issue.replace("_", " ").title(),
                "category": "OTHER",
                "action": "Review the supporting records and determine the cause.",
            })
            exposure = _exposure(row, issue)
            evidence = _issue_evidence(row, issue)
            match_conf = _safe_float(row.get("match_confidence"), 0.0)

            # Confidence breakdown: documented formula, components kept per-case.
            evidence_strength = ISSUE_EVIDENCE_WEIGHTS.get(issue, 0.85) * (1.0 if len(evidence) > 1 else 0.92)
            match_component = (match_conf / 100.0) if issue not in ("missing_ledger", "missing_gst", "duplicate_invoice",
                                                                    "tax_arithmetic_mismatch", "tax_rate_invalid") else 1.0
            confidence_score = round(min(99.0, 100 * (0.45 * match_component + 0.40 * evidence_strength + 0.15 * ISSUE_EVIDENCE_WEIGHTS.get(issue, 0.85))), 2)
            breakdown = {
                "match_certainty": round(100 * match_component, 1),
                "evidence_strength": round(100 * evidence_strength, 1),
                "issue_base_rate": round(100 * ISSUE_EVIDENCE_WEIGHTS.get(issue, 0.85), 1),
                "formula": "confidence = 100*(0.45*match_certainty + 0.40*evidence_strength + 0.15*issue_base_rate)",
            }

            impact = _compute_financial_impact(
                row, issue,
            )

            case_id = stable_case_id(row, issue)
            seen_case_ids[case_id] = seen_case_ids.get(case_id, 0) + 1
            if seen_case_ids[case_id] > 1:
                # Extremely rare (identical refs for two different findings); suffix deterministically.
                case_id = f"{case_id}-{seen_case_ids[case_id]}"
            rows.append({
                "case_id": case_id,
                "invoice_id": row.get("invoice_id"),
                "canonical_invoice_id": row.get("canonical_invoice_id"),
                "vendor_code": row.get("vendor_code", ""),
                "invoice_date": row.get("invoice_date"),
                "ledger_ref": row.get("ledger_ref"),
                "gst_ref": row.get("gst_ref"),
                "issue_type": issue,
                "issue_label": meta["label"],
                "category": meta["category"],
                "severity": str(row.get("severity", "LOW")).upper(),
                "match_confidence": round(match_conf, 2),
                "confidence_score": confidence_score,
                "confidence_breakdown": str(breakdown),
                "evidence": " | ".join(evidence),
                "likely_reason": meta["action"],
                "financial_exposure": exposure,
                "financial_impact_type": impact["type"],
                "financial_impact_amount": impact["amount"],
                "financial_impact_explanation": impact["explanation"],
                "priority_score": _priority_score(row, issue),
                "recommended_action": meta["action"],
                "status": "OPEN",
                "human_decision": "PENDING",
                "review_notes": "",
            })

    columns = [
        "case_id", "invoice_id", "canonical_invoice_id", "vendor_code", "invoice_date",
        "ledger_ref", "gst_ref", "issue_type", "issue_label", "category",
        "severity", "match_confidence", "confidence_score", "confidence_breakdown",
        "evidence", "likely_reason", "financial_exposure", "financial_impact_type",
        "financial_impact_amount", "financial_impact_explanation", "priority_score",
        "recommended_action", "status", "human_decision", "review_notes",
    ]
    result = pd.DataFrame(rows, columns=columns)
    if not result.empty:
        # Display order only — case ids themselves are content-derived and stable.
        result = result.sort_values(["priority_score", "financial_exposure"], ascending=False).reset_index(drop=True)
    return result


def create_investigation_summary(cases: pd.DataFrame) -> Dict:
    if cases.empty:
        return {"total_cases": 0, "open_cases": 0, "high_priority_cases": 0, "total_exposure": 0.0, "by_issue": {}}
    by_issue = cases.groupby("issue_type").size().sort_values(ascending=False).to_dict()
    return {
        "total_cases": int(len(cases)),
        "open_cases": int((cases["status"] == "OPEN").sum()),
        "high_priority_cases": int((cases["priority_score"] >= 70).sum()),
        "total_exposure": round(float(cases["financial_exposure"].sum()), 2),
        "by_issue": {str(k): int(v) for k, v in by_issue.items()},
    }


def save_cases_to_sqlite(cases: pd.DataFrame, db_path: str | Path) -> None:
    """Persist cases to a dedicated investigation_cases table."""
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        cases.to_sql("investigation_cases", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigation_status ON investigation_cases(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigation_issue ON investigation_cases(issue_type)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_investigation_priority ON investigation_cases(priority_score)")
        conn.commit()
