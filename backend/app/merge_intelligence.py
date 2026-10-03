from __future__ import annotations
from pathlib import Path
import pandas as pd
ROOT=Path(__file__).resolve().parents[2]; DATA=ROOT/"data"

def merge_anomaly_signals(cases: pd.DataFrame, anomalies: pd.DataFrame) -> pd.DataFrame:
    out=cases.copy(); sig=anomalies[["invoice_id","anomaly_score","ml_anomaly","anomaly_reason","model"]]
    out=out.merge(sig,on="invoice_id",how="left")
    out["anomaly_score"]=out["anomaly_score"].fillna(0.0); out["ml_anomaly"]=out["ml_anomaly"].fillna(False).astype(bool)
    out["model"]=out["model"].fillna("IsolationForest"); out["anomaly_reason"]=out["anomaly_reason"].fillna("")
    out["ml_priority_boost"]=(out["anomaly_score"]*0.12).round(2)
    out["combined_priority_score"]=(out["priority_score"]+out["ml_priority_boost"]).clip(upper=100).round(2)
    out["investigation_signal"]=out["ml_anomaly"].map({True:"DETERMINISTIC + ML",False:"DETERMINISTIC"})
    return out

def run_and_save(data_dir: Path=DATA):
    out=merge_anomaly_signals(pd.read_csv(data_dir/"investigation_cases.csv"),pd.read_csv(data_dir/"anomaly_results.csv"))
    out.to_csv(data_dir/"investigation_cases_enriched.csv",index=False); return out
