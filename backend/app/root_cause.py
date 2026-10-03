from __future__ import annotations

import math
import sqlite3
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd

DATA = Path(__file__).resolve().parents[2] / "data"
DB = DATA / "reconai.db"

ISSUE_ROOT_CAUSE = {
    "duplicate_invoice": ("Possible duplicate booking", "Compare the linked records and confirm whether the same economic transaction was recorded more than once."),
    "missing_ledger": ("Missing or delayed accounting posting", "Check the ledger and posting period for an omitted, delayed, or differently referenced entry."),
    "missing_gst": ("Missing or differently referenced GST record", "Check GST reference/filing records and confirm whether the invoice was omitted, filed in another period, or referenced differently."),
    "amount_mismatch": ("Accounting amount differs from invoice", "Compare taxable values and source documents; determine whether the difference is an entry error, adjustment, or timing issue."),
    "tax_mismatch": ("Recorded tax differs from expected/source tax", "Recalculate tax from taxable value and applicable rate, then compare the invoice, ledger and GST record."),
    "date_mismatch": ("Posting or filing timing difference", "Compare invoice, accounting and filing dates and determine whether the difference is a valid period/timing adjustment."),
}


def _f(x, default=0.0):
    try:
        v = float(x)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default


def _fmt_money(x):
    return f"₹{_f(x):,.2f}"


def _load(base: Path = DATA):
    cases = pd.read_csv(base / "investigation_cases_patterned.csv")
    inv = pd.read_csv(base / "invoices.csv")
    led = pd.read_csv(base / "ledger.csv")
    gst = pd.read_csv(base / "gst_records.csv")
    vendors = pd.read_csv(base / "vendors.csv")
    for d, cols in [(inv,["invoice_date"]),(led,["entry_date"]),(gst,["filing_date"])]:
        for c in cols: d[c] = pd.to_datetime(d[c], errors="coerce")
    return cases, inv, led, gst, vendors


def _evidence(issue, irow, lrow, grow):
    parts=[]
    if irow is not None:
        parts.append(f"Invoice {irow['invoice_id']} taxable {_fmt_money(irow['taxable_amount'])}, tax {_fmt_money(irow['tax_amount'])} at {irow['tax_rate']:.2f}%.")
    if lrow is not None:
        parts.append(f"Ledger taxable {_fmt_money(lrow['taxable_amount'])}, tax {_fmt_money(lrow['tax_amount'])}, entry date {lrow['entry_date'].date()}.")
    if grow is not None:
        parts.append(f"GST taxable {_fmt_money(grow['taxable_amount'])}, tax {_fmt_money(grow['tax_amount'])}, filing date {grow['filing_date'].date()}.")
    if issue == "tax_mismatch" and irow is not None:
        expected = _f(irow["taxable_amount"]) * _f(irow["tax_rate"]) / 100
        parts.append(f"Expected invoice tax from taxable value × rate is {_fmt_money(expected)}.")
    return " ".join(parts)


def enrich_root_cause(cases: pd.DataFrame, base: Path = DATA) -> pd.DataFrame:
    cases = cases.copy()
    _, inv, led, gst, vendors = _load(base)
    inv_by = {str(r.invoice_id): r for r in inv.itertuples(index=False)}
    led_by = {str(r.invoice_id): r for r in led.itertuples(index=False)}
    gst_by = {str(r.invoice_id): r for r in gst.itertuples(index=False)}

    out=[]
    for _, row in cases.iterrows():
        issue=str(row.get("issue_type",""))
        iid=str(row.get("invoice_id",""))
        i=inv_by.get(iid); l=led_by.get(iid); g=gst_by.get(iid)
        label, action=ISSUE_ROOT_CAUSE.get(issue, ("Review required", "Review the supporting records."))
        # Convert namedtuple to dict-like access for robust formatting.
        im = i._asdict() if i else None
        lm = l._asdict() if l else None
        gm = g._asdict() if g else None
        evidence=_evidence(issue, im, lm, gm)

        if issue == "tax_mismatch" and im:
            expected=_f(im["taxable_amount"])*_f(im["tax_rate"])/100
            recorded = _f(gm["tax_amount"]) if gm else (_f(lm["tax_amount"]) if lm else _f(im["tax_amount"]))
            exposure=abs(recorded-expected)
            detail=f"Expected tax {_fmt_money(expected)} vs recorded {_fmt_money(recorded)}; difference {_fmt_money(exposure)}."
        elif issue == "amount_mismatch" and im and lm:
            exposure=abs(_f(im["taxable_amount"])-_f(lm["taxable_amount"]))
            detail=f"Invoice taxable {_fmt_money(im['taxable_amount'])} vs ledger taxable {_fmt_money(lm['taxable_amount'])}; difference {_fmt_money(exposure)}."
        elif issue == "date_mismatch" and im and lm:
            days=abs((pd.Timestamp(lm["entry_date"])-pd.Timestamp(im["invoice_date"])).days)
            exposure=0.0
            detail=f"Invoice date {pd.Timestamp(im['invoice_date']).date()} vs ledger date {pd.Timestamp(lm['entry_date']).date()}; {days} day difference."
        elif issue == "missing_gst" and im:
            exposure=_f(im["tax_amount"])
            detail=f"No GST record was linked to invoice {iid}; invoice tax at stake is {_fmt_money(exposure)}."
        elif issue == "missing_ledger" and im:
            exposure=_f(im["total_amount"])
            detail=f"No ledger record was linked to invoice {iid}; invoice total requiring accounting review is {_fmt_money(exposure)}."
        elif issue == "duplicate_invoice" and im:
            exposure=_f(im["total_amount"])
            detail=f"Invoice {iid} is part of a duplicate/near-duplicate fingerprint; review the linked booking before counting exposure as a loss."
        else:
            exposure=_f(row.get("financial_exposure"))
            detail="Supporting source records are incomplete for a deeper deterministic explanation."

        pattern=str(row.get("pattern_explanation", "No recurring pattern detected."))
        if not pattern or pattern.lower()=="nan": pattern="No recurring pattern detected."
        ml_reason=str(row.get("anomaly_reason", ""))
        if ml_reason.lower()=="nan": ml_reason=""
        anomaly=_f(row.get("anomaly_score"), 0)
        if anomaly >= 70:
            anomaly_note=f"ML anomaly signal is high ({anomaly:.1f}/100)."
        elif anomaly >= 40:
            anomaly_note=f"ML anomaly signal is moderate ({anomaly:.1f}/100)."
        else:
            anomaly_note=f"ML anomaly signal is low ({anomaly:.1f}/100)."

        confidence=_f(row.get("pattern_confidence"), 0)
        explanation=(f"{label}. {detail} {pattern} {anomaly_note}"
                     + (f" ML signal: {ml_reason}." if ml_reason else ""))
        priority=_f(row.get("final_priority_score", row.get("combined_priority_score", row.get("priority_score"))))
        if priority >= 80: priority_band="CRITICAL"
        elif priority >= 60: priority_band="HIGH"
        elif priority >= 35: priority_band="MEDIUM"
        else: priority_band="LOW"

        rec = row.to_dict()
        rec.update({
            "root_cause": label,
            "root_cause_detail": detail,
            "investigation_explanation": explanation,
            "evidence_detail": evidence,
            "financial_exposure_refined": round(exposure,2),
            "pattern_context": pattern,
            "ml_context": ml_reason,
            "priority_band": priority_band,
            "recommended_action_refined": action,
            "review_question": "Confirm whether the evidence supports the proposed root cause and record the final decision.",
        })
        out.append(rec)
    return pd.DataFrame(out)


def save_root_cause_outputs(df: pd.DataFrame, base: Path = DATA):
    base.mkdir(parents=True, exist_ok=True)
    df.to_csv(base / "investigation_cases_explained.csv", index=False, encoding="utf-8-sig")
    with sqlite3.connect(DB) as conn:
        df.to_sql("investigation_cases_explained", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_explained_priority ON investigation_cases_explained(priority_band)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_explained_root_cause ON investigation_cases_explained(root_cause)")
        conn.commit()


def create_explanation_summary(df: pd.DataFrame) -> Dict:
    if df.empty:
        return {"cases":0,"total_refined_exposure":0.0,"by_root_cause":{},"priority_bands":{}}
    return {
        "cases": int(len(df)),
        "total_refined_exposure": round(float(df["financial_exposure_refined"].sum()),2),
        "by_root_cause": {str(k): int(v) for k,v in df["root_cause"].value_counts().to_dict().items()},
        "priority_bands": {str(k): int(v) for k,v in df["priority_band"].value_counts().to_dict().items()},
    }


def main():
    cases, *_ = _load()
    explained=enrich_root_cause(cases)
    save_root_cause_outputs(explained)
    print(create_explanation_summary(explained))

if __name__ == "__main__":
    main()
