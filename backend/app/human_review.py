from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
DB = DATA / 'reconai.db'
INPUT = DATA / 'investigation_cases_rag.csv'
OUTPUT = DATA / 'investigation_cases_reviewed.csv'
VALID_DECISIONS = {'CONFIRM', 'REJECT', 'NEEDS_REVIEW'}

SCHEMA = '''
CREATE TABLE IF NOT EXISTS review_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('CONFIRM','REJECT','NEEDS_REVIEW')),
    reviewer TEXT NOT NULL,
    notes TEXT,
    decided_at TEXT NOT NULL,
    previous_status TEXT,
    UNIQUE(case_id)
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor TEXT NOT NULL,
    event_data TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_review_case ON review_decisions(case_id);
CREATE INDEX IF NOT EXISTS idx_audit_case ON audit_log(case_id);
'''


def init_review_tables(db: Path = DB) -> None:
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
        conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_decision(case_id: str, decision: str, reviewer: str,
                    notes: str = '', db: Path = DB) -> dict:
    decision = decision.upper().strip()
    if decision not in VALID_DECISIONS:
        raise ValueError(f'Invalid decision: {decision}. Use {sorted(VALID_DECISIONS)}')
    reviewer = reviewer.strip()
    if not reviewer:
        raise ValueError('reviewer is required')
    init_review_tables(db)
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            'SELECT status FROM investigation_cases_rag WHERE case_id = ?', (case_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f'Unknown case_id: {case_id}')
        previous_status = row[0]
        now = _now()
        conn.execute('''
            INSERT INTO review_decisions(case_id, decision, reviewer, notes, decided_at, previous_status)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                decision=excluded.decision,
                reviewer=excluded.reviewer,
                notes=excluded.notes,
                decided_at=excluded.decided_at,
                previous_status=excluded.previous_status
        ''', (case_id, decision, reviewer, notes, now, previous_status))
        new_status = {'CONFIRM': 'CONFIRMED', 'REJECT': 'REJECTED', 'NEEDS_REVIEW': 'NEEDS_REVIEW'}[decision]
        conn.execute('UPDATE investigation_cases_rag SET status = ? WHERE case_id = ?', (new_status, case_id))
        conn.execute('''INSERT INTO audit_log(case_id,event_type,actor,event_data,created_at)
                        VALUES (?,?,?,?,?)''',
                     (case_id, 'REVIEW_DECISION', reviewer,
                      f'decision={decision};previous_status={previous_status};notes={notes}', now))
        conn.commit()
    return {'case_id': case_id, 'decision': decision, 'status': new_status, 'reviewer': reviewer, 'decided_at': now}


def record_event(case_id: str, event_type: str, actor: str, event_data: str = '', db: Path = DB) -> dict:
    init_review_tables(db)
    now = _now()
    with sqlite3.connect(db) as conn:
        conn.execute('INSERT INTO audit_log(case_id,event_type,actor,event_data,created_at) VALUES (?,?,?,?,?)',
                     (case_id, event_type, actor, event_data, now))
        conn.commit()
    return {'case_id': case_id, 'event_type': event_type, 'actor': actor, 'created_at': now}


def load_review_queue(db: Path = DB, status: Optional[str] = 'OPEN', limit: int = 50) -> pd.DataFrame:
    init_review_tables(db)
    q = 'SELECT * FROM investigation_cases_rag'
    params = []
    if status:
        q += ' WHERE status = ?'
        params.append(status)
    q += ' ORDER BY priority_score DESC, financial_exposure DESC LIMIT ?'
    params.append(limit)
    with sqlite3.connect(db) as conn:
        return pd.read_sql_query(q, conn, params=params)


def export_reviewed_cases(db: Path = DB, output: Path = OUTPUT) -> pd.DataFrame:
    init_review_tables(db)
    with sqlite3.connect(db) as conn:
        df = pd.read_sql_query('''
            SELECT c.*, r.decision AS human_decision, r.reviewer, r.notes AS review_notes,
                   r.decided_at
            FROM investigation_cases_rag c
            LEFT JOIN review_decisions r ON c.case_id = r.case_id
            ORDER BY c.priority_score DESC, c.financial_exposure DESC
        ''', conn)
    df.to_csv(output, index=False)
    return df


def feedback_summary(db: Path = DB) -> dict:
    init_review_tables(db)
    with sqlite3.connect(db) as conn:
        rows = conn.execute('SELECT decision, COUNT(*) FROM review_decisions GROUP BY decision').fetchall()
        total = conn.execute('SELECT COUNT(*) FROM review_decisions').fetchone()[0]
        return {'total_reviewed': total, 'by_decision': {k: v for k, v in rows}}


if __name__ == '__main__':
    init_review_tables()
    df = export_reviewed_cases()
    print({'cases_exported': len(df), **feedback_summary()})
