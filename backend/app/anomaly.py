"""ML anomaly detection using Isolation Forest.

The model is trained on per-vendor behavioural features extracted from
invoice data.  After training the fitted model, scaler, and reference
statistics are persisted to ``models/`` so that new data can be scored
without retraining.

Model artifacts
---------------
    models/anomaly_model.joblib     – fitted IsolationForest
    models/anomaly_scaler.joblib    – fitted StandardScaler
    models/anomaly_stats.joblib     – median / MAD reference for explanations
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

try:
    import joblib
except ImportError:  # fallback bundled with sklearn
    from sklearn.externals import joblib  # type: ignore[attr-defined]

from . import config

ROOT = config.ROOT
DATA = config.DATA_DIR
MODELS = config.MODELS_DIR

FEATURE_COLUMNS = [
    "taxable_amount", "tax_amount", "total_amount",
    "vendor_txn_count", "vendor_amount_mean_ratio",
    "vendor_amount_std_ratio", "vendor_tax_mean_ratio",
    "day_of_month", "day_of_week",
]

FEATURE_LABELS = {
    "taxable_amount": "unusual taxable amount",
    "tax_amount": "unusual tax amount",
    "total_amount": "unusual invoice total",
    "vendor_txn_count": "unusual vendor transaction frequency",
    "vendor_amount_mean_ratio": "amount differs from vendor baseline",
    "vendor_amount_std_ratio": "amount is far from vendor history",
    "vendor_tax_mean_ratio": "tax differs from vendor baseline",
    "day_of_month": "unusual invoice timing",
    "day_of_week": "unusual weekday pattern",
}


# ── Feature engineering ────────────────────────────────────────────────

def build_features(invoices: pd.DataFrame) -> pd.DataFrame:
    """Compute per-vendor behavioural features from raw invoice data."""
    df = invoices.copy()
    for col in ["taxable_amount", "tax_amount", "total_amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["invoice_date"] = pd.to_datetime(df["invoice_date"], errors="coerce")

    stats = df.groupby("vendor_code").agg(
        vendor_txn_count=("invoice_id", "count"),
        vendor_amount_mean=("total_amount", "mean"),
        vendor_amount_std=("total_amount", "std"),
        vendor_tax_mean=("tax_amount", "mean"),
    ).reset_index()
    df = df.merge(stats, on="vendor_code", how="left")

    df["vendor_amount_mean_ratio"] = df["total_amount"] / df["vendor_amount_mean"].replace(0, np.nan)
    df["vendor_amount_std_ratio"] = (df["total_amount"] - df["vendor_amount_mean"]).abs() / df["vendor_amount_std"].replace(0, np.nan)
    df["vendor_tax_mean_ratio"] = df["tax_amount"] / df["vendor_tax_mean"].replace(0, np.nan)
    df["day_of_month"] = df["invoice_date"].dt.day.fillna(0)
    df["day_of_week"] = df["invoice_date"].dt.dayofweek.fillna(0)

    for col in FEATURE_COLUMNS:
        df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return df


# ── Reason generation ──────────────────────────────────────────────────

def _reason(row, medians, scales):
    """Identify which features deviate most from the baseline."""
    vals = []
    for col in FEATURE_COLUMNS:
        scale = float(scales[col]) or 1.0
        z = abs(float(row[col]) - float(medians[col])) / scale
        if z >= 2.0:
            vals.append((z, FEATURE_LABELS[col]))
    vals.sort(reverse=True)
    return "; ".join(x[1] for x in vals[:3]) or "Transaction pattern is unusual relative to the learned baseline."


# ── Model persistence ─────────────────────────────────────────────────

def _model_path(name: str) -> Path:
    return MODELS / name


def save_model(model: IsolationForest, scaler: StandardScaler, medians: pd.Series, scales: pd.Series):
    """Persist the trained model and reference statistics."""
    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, _model_path("anomaly_model.joblib"))
    joblib.dump(scaler, _model_path("anomaly_scaler.joblib"))
    joblib.dump({"medians": medians, "scales": scales}, _model_path("anomaly_stats.joblib"))


def load_model():
    """Load a previously trained model. Returns (model, scaler, stats) or None."""
    model_file = _model_path("anomaly_model.joblib")
    scaler_file = _model_path("anomaly_scaler.joblib")
    stats_file = _model_path("anomaly_stats.joblib")
    if model_file.exists() and scaler_file.exists() and stats_file.exists():
        return (
            joblib.load(model_file),
            joblib.load(scaler_file),
            joblib.load(stats_file),
        )
    return None


# ── Train & score ──────────────────────────────────────────────────────

def train(invoices: pd.DataFrame, contamination: float = 0.05, random_state: int = 42):
    """Train the Isolation Forest and persist it. Returns (model, scaler, stats)."""
    features = build_features(invoices)
    X = features[FEATURE_COLUMNS].to_numpy(dtype=float)

    scaler = StandardScaler()
    Xs = scaler.fit_transform(X)

    model = IsolationForest(
        n_estimators=250,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(Xs)

    medians = features[FEATURE_COLUMNS].median()
    scales = (features[FEATURE_COLUMNS] - medians).abs().median().replace(0, 1.0)

    save_model(model, scaler, medians, scales)
    return model, scaler, {"medians": medians, "scales": scales}


def score(invoices: pd.DataFrame, model=None, scaler=None, stats=None) -> pd.DataFrame:
    """Score invoices with a trained model. If no model provided, loads from disk."""
    if model is None:
        loaded = load_model()
        if loaded is None:
            raise RuntimeError("No trained model found. Run train() or the pipeline first.")
        model, scaler, stats = loaded

    features = build_features(invoices)
    X = features[FEATURE_COLUMNS].to_numpy(dtype=float)
    Xs = scaler.transform(X)

    raw = -model.score_samples(Xs)
    lo, hi = float(raw.min()), float(raw.max())
    scores = np.full(len(raw), 50.0) if hi - lo < 1e-12 else 100 * (raw - lo) / (hi - lo)

    medians = stats["medians"]
    scales = stats["scales"]

    out = pd.DataFrame({
        "invoice_id": features["invoice_id"].astype(str),
        "vendor_code": features["vendor_code"].astype(str),
        "anomaly_score": np.round(scores, 2),
        "ml_anomaly": (model.predict(Xs) == -1),
    })
    out["anomaly_reason"] = [_reason(row, medians, scales) for _, row in features.iterrows()]
    out["model"] = "IsolationForest"
    return out


# ── Convenience: train + score in one call (used by pipeline) ──────────

def detect_anomalies(invoices: pd.DataFrame, contamination: float = 0.05, random_state: int = 42) -> pd.DataFrame:
    """Train a fresh model and score all invoices. Saves the model to disk."""
    model, scaler, stats = train(invoices, contamination, random_state)
    return score(invoices, model, scaler, stats)


def run_and_save(data_dir: Path = DATA):
    result = detect_anomalies(pd.read_csv(data_dir / "invoices.csv"))
    result.to_csv(data_dir / "anomaly_results.csv", index=False)
    return result


if __name__ == "__main__":
    r = run_and_save()
    print(f"Scored {len(r)} transactions; ML anomalies: {int(r.ml_anomaly.sum())}")
    print(f"Model saved to {MODELS}")
