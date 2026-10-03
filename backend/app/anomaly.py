from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
FEATURE_COLUMNS = ["taxable_amount","tax_amount","total_amount","vendor_txn_count","vendor_amount_mean_ratio","vendor_amount_std_ratio","vendor_tax_mean_ratio","day_of_month","day_of_week"]


def build_features(invoices: pd.DataFrame) -> pd.DataFrame:
    df = invoices.copy()
    for col in ["taxable_amount","tax_amount","total_amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")
    stats = df.groupby("vendor_code").agg(vendor_txn_count=("invoice_id","count"), vendor_amount_mean=("total_amount","mean"), vendor_amount_std=("total_amount","std"), vendor_tax_mean=("tax_amount","mean")).reset_index()
    df = df.merge(stats, on="vendor_code", how="left")
    df["vendor_amount_mean_ratio"] = df["total_amount"] / df["vendor_amount_mean"].replace(0, np.nan)
    df["vendor_amount_std_ratio"] = (df["total_amount"] - df["vendor_amount_mean"]).abs() / df["vendor_amount_std"].replace(0, np.nan)
    df["vendor_tax_mean_ratio"] = df["tax_amount"] / df["vendor_tax_mean"].replace(0, np.nan)
    df["day_of_month"] = df["invoice_date"].dt.day.fillna(0)
    df["day_of_week"] = df["invoice_date"].dt.dayofweek.fillna(0)
    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf,-np.inf], np.nan).fillna(0.0)
    return df


def _reason(row, medians, scales):
    labels = {"taxable_amount":"unusual taxable amount","tax_amount":"unusual tax amount","total_amount":"unusual invoice total","vendor_txn_count":"unusual vendor transaction frequency","vendor_amount_mean_ratio":"amount differs from vendor baseline","vendor_amount_std_ratio":"amount is far from vendor history","vendor_tax_mean_ratio":"tax differs from vendor baseline","day_of_month":"unusual invoice timing","day_of_week":"unusual weekday pattern"}
    vals=[]
    for col in FEATURE_COLUMNS:
        scale=float(scales[col]) or 1.0
        z=abs(float(row[col])-float(medians[col]))/scale
        if z>=2.0: vals.append((z,labels[col]))
    vals.sort(reverse=True)
    return "; ".join(x[1] for x in vals[:3]) or "Transaction pattern is unusual relative to the learned baseline."


def detect_anomalies(invoices: pd.DataFrame, contamination: float=0.05, random_state: int=42) -> pd.DataFrame:
    features=build_features(invoices)
    X=features[FEATURE_COLUMNS].to_numpy(dtype=float)
    Xs=StandardScaler().fit_transform(X)
    model=IsolationForest(n_estimators=250, contamination=contamination, random_state=random_state, n_jobs=-1)
    model.fit(Xs)
    raw=-model.score_samples(Xs)
    lo,hi=float(raw.min()),float(raw.max())
    scores=np.full(len(raw),50.0) if hi-lo<1e-12 else 100*(raw-lo)/(hi-lo)
    med=features[FEATURE_COLUMNS].median(); scale=(features[FEATURE_COLUMNS]-med).abs().median().replace(0,1.0)
    out=pd.DataFrame({"invoice_id":features["invoice_id"].astype(str),"vendor_code":features["vendor_code"].astype(str),"anomaly_score":np.round(scores,2),"ml_anomaly":(model.predict(Xs)==-1)})
    out["anomaly_reason"]=[_reason(row,med,scale) for _,row in features.iterrows()]
    out["model"]="IsolationForest"
    return out


def run_and_save(data_dir: Path=DATA):
    result=detect_anomalies(pd.read_csv(data_dir/"invoices.csv"))
    result.to_csv(data_dir/"anomaly_results.csv",index=False)
    return result

if __name__=="__main__":
    r=run_and_save(); print(f"Scored {len(r)} transactions; ML anomalies: {int(r.ml_anomaly.sum())}")
