from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List

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
}

PRIORITY_WEIGHTS = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}


def _safe_float(value, default=0.0) -> float:
    try:
        x = float(value)
        return default if math.isnan(x) else x
    except (TypeError, ValueError):
        return default


def _issue_list(value) -> List[str]:
    if pd.isna(value) or not str(value).strip():
        return []
    # Support both ';' (from reconciliation) and '|' separators.
    import re
    return [x.strip() for x in re.split(r"[;|]", str(value)) if x.strip()]


def _priority_score(row: pd.Series, issue: str) -> float:
    severity = PRIORITY_WEIGHTS.get(str(row.get("severity", "LOW")).upper(), 1)
    confidence = _safe_float(row.get("match_confidence"), 0.0)
    exposure = _safe_float(row.get("financial_exposure"), 0.0)
    # Bounded financial component keeps huge transactions from overwhelming the score.
    financial_component = min(math.log10(max(exposure, 0.0) + 1) / 7.0, 1.0)
    confidence_component = max(0.0, min(confidence / 100.0, 1.0))
    issue_component = 1.0 if issue in {"duplicate_invoice", "tax_mismatch", "amount_mismatch"} else 0.75
    return round(100 * (0.45 * (severity / 3) + 0.30 * financial_component + 0.15 * confidence_component + 0.10 * issue_component), 2)


def _exposure(row: pd.Series, issue: str) -> float:
    existing = _safe_float(row.get("financial_exposure"), 0.0)
    if existing > 0:
        return round(existing, 2)
    if issue == "missing_ledger":
        return round(_safe_float(row.get("invoice_total_amount"), 0.0), 2)
    if issue == "missing_gst":
        return round(_safe_float(row.get("invoice_tax_amount"), 0.0), 2)
    return 0.0


def build_investigation_cases(reconciliation: pd.DataFrame, invoices: pd.DataFrame | None = None) -> pd.DataFrame:
    """Turn row-level reconciliation flags into structured investigation cases."""
    df = reconciliation.copy()
    if invoices is not None:
        inv_cols = [c for c in ["invoice_id", "total_amount", "tax_amount"] if c in invoices.columns]
        inv = invoices[inv_cols].drop_duplicates("invoice_id").rename(
            columns={"total_amount": "invoice_total_amount", "tax_amount": "invoice_tax_amount"}
        )
        df = df.merge(inv, on="invoice_id", how="left")
    else:
        df["invoice_total_amount"] = 0.0
        df["invoice_tax_amount"] = 0.0

    rows: List[Dict] = []
    for _, row in df.iterrows():
        issues = _issue_list(row.get("issues"))
        if not issues:
            continue
        # One investigation case per issue makes the workflow independently actionable.
        for issue in issues:
            meta = ISSUE_META.get(issue, {
                "label": issue.replace("_", " ").title(),
                "category": "OTHER",
                "action": "Review the supporting records and determine the cause.",
            })
            exposure = _exposure(row, issue)
            evidence = str(row.get("evidence", ""))
            confidence = _safe_float(row.get("match_confidence"), 0.0)
            case_id = f"CASE-{len(rows) + 1:05d}"
            rows.append({
                "case_id": case_id,
                "invoice_id": row.get("invoice_id"),
                "vendor_code": row.get("vendor_code", ""),
                "ledger_ref": row.get("ledger_ref"),
                "gst_ref": row.get("gst_ref"),
                "issue_type": issue,
                "issue_label": meta["label"],
                "category": meta["category"],
                "severity": str(row.get("severity", "LOW")).upper(),
                "match_confidence": round(confidence, 2),
                "financial_exposure": exposure,
                "priority_score": _priority_score(row, issue),
                "evidence": evidence,
                "recommended_action": meta["action"],
                "status": "OPEN",
                "human_decision": "PENDING",
                "review_notes": "",
            })

    columns = [
        "case_id", "invoice_id", "vendor_code", "ledger_ref", "gst_ref", "issue_type", "issue_label", "category",
        "severity", "match_confidence", "financial_exposure", "priority_score", "evidence",
        "recommended_action", "status", "human_decision", "review_notes",
    ]
    result = pd.DataFrame(rows, columns=columns)
    for c in ["match_confidence", "financial_exposure", "priority_score"]:
        result[c] = pd.to_numeric(result[c], errors="coerce").fillna(0.0)

    if not result.empty:
        result = result.sort_values(["priority_score", "financial_exposure"], ascending=False).reset_index(drop=True)
        result["case_id"] = [f"CASE-{i:05d}" for i in range(1, len(result) + 1)]
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
