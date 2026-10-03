"""Evaluate Phase 2 reconciliation results against synthetic ground truth."""
from pathlib import Path
import pandas as pd

from .reconciliation import reconcile, load_data

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def evaluate(data_dir: Path = DATA) -> pd.DataFrame:
    invoices, ledger, gst = load_data(data_dir)
    result = reconcile(invoices, ledger, gst)
    truth = pd.read_csv(data_dir / "ground_truth.csv")

    truth_set = {(str(r.invoice_id), str(r.discrepancy_type)) for r in truth.itertuples()}
    pred_set = set()
    for r in result.itertuples():
        if not isinstance(r.issues, str) or not r.issues:
            continue
        for issue in r.issues.split(";"):
            if issue:
                pred_set.add((str(r.canonical_invoice_id), issue))

    rows = []
    for kind in sorted(truth.discrepancy_type.unique()):
        actual = {x for x in truth_set if x[1] == kind}
        predicted = {x for x in pred_set if x[1] == kind}
        tp = len(actual & predicted)
        fp = len(predicted - actual)
        fn = len(actual - predicted)
        precision = tp / (tp + fp) if tp + fp else 1.0
        recall = tp / (tp + fn) if tp + fn else 1.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        rows.append({"discrepancy_type": kind, "true_positive": tp, "false_positive": fp,
                     "false_negative": fn, "precision": round(precision, 4),
                     "recall": round(recall, 4), "f1": round(f1, 4)})

    metrics = pd.DataFrame(rows)
    metrics.to_csv(data_dir / "reconciliation_metrics.csv", index=False)
    print(metrics.to_string(index=False))
    print(f"\nGround-truth cases: {len(truth_set)}")
    print(f"Detected ground-truth cases: {len(truth_set & pred_set)}")
    return metrics


if __name__ == "__main__":
    evaluate()
