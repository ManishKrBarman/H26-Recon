from pathlib import Path
import pandas as pd
from .investigation import build_investigation_cases, create_investigation_summary, save_cases_to_sqlite

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def main():
    reconciliation = pd.read_csv(DATA / "reconciliation_results.csv")
    invoices = pd.read_csv(DATA / "invoices.csv")
    cases = build_investigation_cases(reconciliation, invoices)
    out = DATA / "investigation_cases.csv"
    cases.to_csv(out, index=False)
    save_cases_to_sqlite(cases, DATA / "reconai.db")
    summary = create_investigation_summary(cases)
    print("ReconAI Investigation Engine")
    print(f"Cases created: {summary['total_cases']}")
    print(f"Open cases: {summary['open_cases']}")
    print(f"High-priority cases: {summary['high_priority_cases']}")
    print(f"Estimated exposure: ₹{summary['total_exposure']:,.2f}")
    print("By issue:", summary["by_issue"])
    print(f"Saved: {out}")


if __name__ == "__main__":
    main()
