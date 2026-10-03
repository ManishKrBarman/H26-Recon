"""Evaluation for ReconAI detection quality.

Modes
-----
* default      — evaluate the current data-dir dataset against its ground_truth.csv
                 (the committed Drive label set when demo data is loaded from the
                 external labels; falls back to repo-local ground_truth.csv).
* ``--labels drive`` — explicitly use data/external/ground_truth_drive.csv.
* ``--holdout`` — generate a fresh held-out synthetic set (different seed, harsher
                 corruptions, ≥20 injected per type) and evaluate against it.
* ``--negative`` — generate a clean set with zero injected errors and measure the
                 false-positive rate.

Results are written to ``data/evaluation_results.json`` and printed. Nothing here
tunes thresholds; it only measures.
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

import pandas as pd

from . import config
from .reconciliation import reconcile
from .investigation import build_investigation_cases

ROOT = config.ROOT
DATA = config.DATA_DIR


def has_ground_truth(data_dir: Path = DATA) -> bool:
    local = Path(data_dir) / "ground_truth.csv"
    return local.exists() or config.DRIVE_GROUND_TRUTH_PATH.exists()


def _resolve_labels(data_dir: Path, labels: str | None) -> Path | None:
    local = Path(data_dir) / "ground_truth.csv"
    if labels == "drive" or (labels is None and not local.exists() and config.DRIVE_GROUND_TRUTH_PATH.exists()):
        return config.DRIVE_GROUND_TRUTH_PATH
    if local.exists():
        return local
    return None


def _metrics_frame(truth: pd.DataFrame, result: pd.DataFrame) -> pd.DataFrame:
    truth_set = {(str(r.invoice_id), str(r.discrepancy_type)) for r in truth.itertuples()}
    pred_set: set[tuple[str, str]] = set()
    for r in result.itertuples():
        if not isinstance(r.issues, str) or not r.issues:
            continue
        for issue in r.issues.split(";"):
            if issue:
                pred_set.add((str(r.canonical_invoice_id), issue))

    rows = []
    kinds = sorted(set(truth_set) | set(pred_set), key=lambda x: x[1])
    for kind in sorted({k for _, k in kinds}):
        actual = {x for x in truth_set if x[1] == kind}
        predicted = {x for x in pred_set if x[1] == kind}
        tp = len(actual & predicted)
        fp = len(predicted - actual)
        fn = len(actual - predicted)
        precision = tp / (tp + fp) if tp + fp else (1.0 if not actual else 0.0)
        recall = tp / (tp + fn) if tp + fn else (1.0 if not predicted else 0.0)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({"discrepancy_type": kind, "true_positive": tp, "false_positive": fp,
                     "false_negative": fn, "precision": round(precision, 4),
                     "recall": round(recall, 4), "f1": round(f1, 4)})
    return pd.DataFrame(rows)


def evaluate(data_dir: Path = DATA, labels: str | None = None, refresh: bool = False,
             save: bool = True) -> pd.DataFrame:
    """Evaluate the current dataset against its ground truth."""
    data_dir = Path(data_dir)
    label_path = _resolve_labels(data_dir, labels)
    if label_path is None:
        raise FileNotFoundError("No ground truth labels available (data/ground_truth.csv or data/external/ground_truth_drive.csv)")
    truth = pd.read_csv(label_path)

    result_path = data_dir / "reconciliation_results.csv"
    if result_path.exists() and not refresh:
        result = pd.read_csv(result_path)
    else:
        invoices = pd.read_csv(data_dir / "invoices.csv")
        ledger = pd.read_csv(data_dir / "ledger.csv")
        gst = pd.read_csv(data_dir / "gst_records.csv")
        result = reconcile(invoices, ledger, gst)

    metrics = _metrics_frame(truth, result)
    if save:
        metrics.to_csv(data_dir / "reconciliation_metrics.csv", index=False)
    return metrics


def evaluate_holdout(n: int = 1000, seed: int = 90210, per_type: int = 20) -> dict:
    """Generate a held-out set (fresh seed, harsher corruptions) and evaluate."""
    from .eval_data import generate_eval

    truth_frames, metrics_frames, summary = [], [], {}
    with tempfile.TemporaryDirectory(prefix="reconai_eval_") as tmp:
        tmp_dir = Path(tmp)
        invoices, ledger, gst, truth = generate_eval(n, seed, per_type)
        invoices.to_csv(tmp_dir / "invoices.csv", index=False)
        ledger.to_csv(tmp_dir / "ledger.csv", index=False)
        gst.to_csv(tmp_dir / "gst_records.csv", index=False)
        truth.to_csv(tmp_dir / "ground_truth.csv", index=False)

        result = reconcile(invoices, ledger, gst)
        metrics = _metrics_frame(truth, result)
        macro_f1 = float(metrics["f1"].mean())

        # ML anomaly precision against injected outliers (injected rows vs flagged rows).
        from .anomaly import detect_anomalies
        anomalies = detect_anomalies(invoices)
        flagged = set(anomalies.loc[anomalies["ml_anomaly"], "invoice_id"])
        injected_ids = set(truth["invoice_id"]) | {str(v) + "-2" for v in truth.loc[truth.discrepancy_type == "duplicate_invoice", "invoice_id"]}
        injected_flagged = len(flagged & injected_ids)
        anomaly_precision = injected_flagged / len(flagged) if flagged else 0.0

        # Pattern recall: were vendor-level recurrences found? Build patterns from cases.
        from .pattern_intelligence import detect_patterns
        cases = build_investigation_cases(result, invoices)
        patterns, memberships = detect_patterns(cases, invoices)
        # Ground-truth recurrence: vendor+issue groups with >=3 injected cases.
        cases_with_vendor = cases.merge(invoices[["invoice_id", "vendor_code"]].drop_duplicates("invoice_id"), on="invoice_id", how="left", suffixes=("", "_inv"))
        injected_by_vendor_issue = truth.merge(cases_with_vendor[["invoice_id", "vendor_code"]].drop_duplicates("invoice_id"), on="invoice_id", how="left")
        gt_groups = injected_by_vendor_issue.groupby(["vendor_code", "discrepancy_type"]).size()
        gt_recurrences = gt_groups[gt_groups >= 3]
        found = 0
        for (vendor, issue) in gt_recurrences.index:
            hit = patterns[(patterns.vendor_code == vendor) & (patterns.issue_type == issue)]
            if not hit.empty:
                found += 1
        pattern_recall = found / len(gt_recurrences) if len(gt_recurrences) else None

        summary = {
            "mode": "holdout",
            "n_invoices": int(len(invoices)),
            "n_injected": int(len(truth)),
            "per_issue": metrics.to_dict(orient="records"),
            "macro_f1": round(macro_f1, 4),
            "ml_anomaly": {
                "flagged_rows": len(flagged),
                "flagged_injected": injected_flagged,
                "precision_vs_injected": round(anomaly_precision, 4),
            },
            "pattern_recall": None if pattern_recall is None else round(pattern_recall, 4),
            "n_pattern_recurrences_gt": int(len(gt_recurrences)),
            "n_patterns_detected": int(len(patterns)),
        }
    return summary


def evaluate_negative_control(n: int = 1000, seed: int = 777) -> dict:
    """Zero-injected-error dataset: measure false-positive rate."""
    from .eval_data import generate_negative_control

    with tempfile.TemporaryDirectory(prefix="reconai_eval_neg_") as tmp:
        tmp_dir = Path(tmp)
        invoices, ledger, gst = generate_negative_control(n, seed)
        result = reconcile(invoices, ledger, gst)
        flagged_rows = result[result["issue_count"] > 0]
        flagged_invoices = flagged_rows["canonical_invoice_id"].nunique()
        fp_rate_rows = len(flagged_rows) / n
        fp_rate_invoices = flagged_invoices / n
        by_issue = flagged_rows["issues"].str.split(";").explode().value_counts().to_dict() if len(flagged_rows) else {}
        return {
            "mode": "negative_control",
            "n_invoices": n,
            "flagged_rows": int(len(flagged_rows)),
            "flagged_invoices": int(flagged_invoices),
            "false_positive_rate_rows": round(fp_rate_rows, 4),
            "false_positive_rate_invoices": round(fp_rate_rate := fp_rate_invoices, 4),
            "by_issue": {str(k): int(v) for k, v in by_issue.items()},
        }


def run_full_evaluation(save_path: Path | None = None) -> dict:
    """Default dataset + holdout + negative control; writes evaluation_results.json."""
    report: dict = {"dataset": {}}
    if has_ground_truth(DATA):
        try:
            metrics = evaluate(DATA)
            report["dataset"] = {
                "mode": "current_dataset",
                "per_issue": metrics.to_dict(orient="records"),
                "macro_f1": round(float(metrics["f1"].mean()), 4),
            }
        except FileNotFoundError:
            report["dataset"] = {"mode": "current_dataset", "note": "no labels"}
    report["holdout"] = evaluate_holdout()
    report["negative_control"] = evaluate_negative_control()
    save_path = Path(save_path) if save_path else DATA / "evaluation_results.json"
    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", choices=["drive", "local"], default=None)
    parser.add_argument("--holdout", action="store_true", help="Evaluate on a harsher held-out synthetic set")
    parser.add_argument("--negative", action="store_true", help="Negative-control false-positive measurement")
    parser.add_argument("--n", type=int, default=1000)
    parser.add_argument("--per-type", type=int, default=20)
    parser.add_argument("--seed", type=int, default=90210)
    parser.add_argument("--full", action="store_true", help="Run all three and save evaluation_results.json")
    args = parser.parse_args()

    if args.full:
        report = run_full_evaluation()
        print(json.dumps(report, indent=2))
    elif args.holdout:
        print(json.dumps(evaluate_holdout(args.n, args.seed, args.per_type), indent=2))
    elif args.negative:
        print(json.dumps(evaluate_negative_control(args.n, args.seed), indent=2))
    else:
        df = evaluate(DATA, labels=args.labels)
        print(df.to_string(index=False))
        print(f"\nMacro F1: {df['f1'].mean():.4f}")
