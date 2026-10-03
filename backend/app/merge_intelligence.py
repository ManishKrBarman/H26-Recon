from __future__ import annotations
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"

COLUMNS = [
    "case_id", "invoice_id", "vendor_code", "ledger_ref", "gst_ref", "issue_type", "issue_label",
    "category", "severity", "match_confidence", "financial_exposure", "priority_score", "evidence",
    "recommended_action", "status", "human_decision", "review_notes", "anomaly_score", "ml_anomaly",
    "anomaly_reason", "model", "ml_priority_boost", "combined_priority_score", "investigation_signal"
]


def merge_anomaly_signals(cases: pd.DataFrame, anomalies: pd.DataFrame, invoices: pd.DataFrame | None = None) -> pd.DataFrame:
    out = cases.copy()
    if invoices is None:
        inv_file = DATA / "invoices.csv"
        if inv_file.exists():
            try:
                invoices = pd.read_csv(inv_file)
            except Exception:
                invoices = None
    
    # 1. Merge anomaly signals into existing cases
    if not out.empty and not anomalies.empty:
        sig = anomalies[["invoice_id", "anomaly_score", "ml_anomaly", "anomaly_reason", "model"]].drop_duplicates("invoice_id")
        out = out.merge(sig, on="invoice_id", how="left")
    else:
        for col, default_val in [
            ("anomaly_score", 0.0),
            ("ml_anomaly", False),
            ("anomaly_reason", ""),
            ("model", "IsolationForest"),
        ]:
            if col not in out.columns:
                out[col] = default_val

    # Ensure all numeric columns have float/int dtypes to prevent pandas clip/round errors
    out["anomaly_score"] = pd.to_numeric(out["anomaly_score"], errors="coerce").fillna(0.0)
    out["ml_anomaly"] = out["ml_anomaly"].fillna(False).astype(bool)
    out["model"] = out["model"].fillna("IsolationForest")
    out["anomaly_reason"] = out["anomaly_reason"].fillna("")
    out["ml_priority_boost"] = (out["anomaly_score"] * 0.12).round(2)

    if "priority_score" not in out.columns:
        out["priority_score"] = 0.0
    else:
        out["priority_score"] = pd.to_numeric(out["priority_score"], errors="coerce").fillna(0.0)

    out["combined_priority_score"] = (out["priority_score"] + out["ml_priority_boost"]).clip(upper=100).round(2)
    out["investigation_signal"] = out["ml_anomaly"].map({True: "DETERMINISTIC + ML", False: "DETERMINISTIC"})

    # 2. Also surface pure ML anomalies (transactions flagged as outliers by ML that had clean deterministic reconciliation)
    if not anomalies.empty and "ml_anomaly" in anomalies.columns:
        existing_invoices = set(out["invoice_id"].dropna()) if not out.empty else set()
        ml_only = anomalies[anomalies["ml_anomaly"] & ~anomalies["invoice_id"].isin(existing_invoices)].copy()
        
        if not ml_only.empty:
            inv_map = {}
            if invoices is not None and "invoice_id" in invoices.columns and "total_amount" in invoices.columns:
                inv_map = invoices.drop_duplicates("invoice_id").set_index("invoice_id")["total_amount"].to_dict()

            ml_rows = []
            start_num = len(out) + 1
            for idx, r in ml_only.reset_index(drop=True).iterrows():
                score = float(r.get("anomaly_score", 60.0))
                exposure = float(inv_map.get(r["invoice_id"], r.get("total_amount", 0.0)))
                p_score = round(min(100.0, 35.0 + score * 0.5), 2)

                reason = str(r.get("anomaly_reason", "Statistical transaction outlier flagged by Isolation Forest."))
                ml_rows.append({
                    "case_id": f"CASE-{start_num + idx:05d}",
                    "invoice_id": r["invoice_id"],
                    "vendor_code": r.get("vendor_code", "UNKNOWN"),
                    "ledger_ref": r.get("invoice_id"),
                    "gst_ref": r.get("invoice_id"),
                    "issue_type": "ml_anomaly",
                    "issue_label": "Statistical Outlier / Anomaly",
                    "category": "ANOMALY",
                    "severity": "HIGH" if score >= 75 else "MEDIUM",
                    "match_confidence": 95.0,
                    "financial_exposure": exposure,
                    "priority_score": p_score,
                    "evidence": reason,
                    "recommended_action": "Review transaction characteristics against historical vendor baseline.",
                    "status": "OPEN",
                    "human_decision": "PENDING",
                    "review_notes": "",
                    "anomaly_score": score,
                    "ml_anomaly": True,
                    "anomaly_reason": reason,
                    "model": r.get("model", "IsolationForest"),
                    "ml_priority_boost": round(score * 0.12, 2),
                    "combined_priority_score": p_score,
                    "investigation_signal": "ML",
                })
            out = pd.concat([out, pd.DataFrame(ml_rows)], ignore_index=True)

    # Ensure schema integrity
    for c in COLUMNS:
        if c not in out.columns:
            out[c] = pd.Series(dtype="float64" if "score" in c or "boost" in c or "exposure" in c or "confidence" in c else "object")

    return out


def run_and_save(data_dir: Path = DATA):
    cases_path = data_dir / "investigation_cases.csv"
    anom_path = data_dir / "anomaly_results.csv"
    cases = pd.read_csv(cases_path) if cases_path.exists() else pd.DataFrame()
    anom = pd.read_csv(anom_path) if anom_path.exists() else pd.DataFrame()
    out = merge_anomaly_signals(cases, anom)
    out.to_csv(data_dir / "investigation_cases_enriched.csv", index=False)
    return out
