from __future__ import annotations
import sqlite3
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / 'data' / 'reconai.db'


def build_feedback_dataset(db: Path = DB) -> pd.DataFrame:
    with sqlite3.connect(db) as conn:
        return pd.read_sql_query('''
            SELECT c.case_id, c.issue_type, c.priority_score, c.financial_exposure,
                   c.anomaly_score, c.pattern_confidence,
                   r.decision, r.reviewer, r.decided_at
            FROM investigation_cases_rag c
            JOIN review_decisions r ON c.case_id = r.case_id
            ORDER BY r.decided_at
        ''', conn)


def feedback_metrics(db: Path = DB) -> dict:
    df = build_feedback_dataset(db)
    if df.empty:
        return {'reviewed_cases': 0, 'confirmation_rate': 0.0, 'rejection_rate': 0.0}
    return {
        'reviewed_cases': int(len(df)),
        'confirmation_rate': round(float((df.decision == 'CONFIRM').mean()), 4),
        'rejection_rate': round(float((df.decision == 'REJECT').mean()), 4),
        'needs_review_rate': round(float((df.decision == 'NEEDS_REVIEW').mean()), 4),
    }
