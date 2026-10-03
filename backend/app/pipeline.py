"""ReconAI pipeline orchestrator.

Runs every processing stage in order and persists the final enriched
investigation table (``investigation_cases_rag``) into SQLite so the
API layer can serve it immediately.

Usage
-----
    python -m app.pipeline          # from backend/
    POST /api/pipeline/run          # from the API
"""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List

import pandas as pd

from .reconciliation import reconcile, load_data
from .investigation import build_investigation_cases, save_cases_to_sqlite
from .anomaly import detect_anomalies
from .merge_intelligence import merge_anomaly_signals
from .pattern_intelligence import detect_patterns, enrich_cases_with_patterns, save_pattern_outputs
from .root_cause import enrich_root_cause, save_root_cause_outputs
from .rag import enrich_with_rag, save_outputs as save_rag_outputs, save_kb
from .human_review import init_review_tables

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
DB = DATA / "reconai.db"


@dataclass
class StageResult:
    name: str
    rows: int = 0
    elapsed_s: float = 0.0
    detail: str = ""


@dataclass
class PipelineResult:
    ok: bool = True
    stages: List[StageResult] = field(default_factory=list)
    total_elapsed_s: float = 0.0
    error: str = ""


def run_pipeline(data_dir: Path = DATA) -> PipelineResult:
    """Execute the full ReconAI processing pipeline end-to-end."""
    result = PipelineResult()
    t0 = time.perf_counter()

    try:
        # ── Stage 1: Load source data ────────────────────────────────
        t = time.perf_counter()
        invoices, ledger, gst = load_data(data_dir)
        result.stages.append(StageResult(
            "load_data", rows=len(invoices),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Loaded {len(invoices)} invoices, {len(ledger)} ledger, {len(gst)} GST rows",
        ))

        # ── Stage 2: 3-way reconciliation ────────────────────────────
        t = time.perf_counter()
        recon = reconcile(invoices, ledger, gst)
        recon.to_csv(data_dir / "reconciliation_results.csv", index=False)
        flagged = int((recon["issue_count"] > 0).sum())
        result.stages.append(StageResult(
            "reconciliation", rows=len(recon),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Reconciled {len(recon)} rows; flagged {flagged}",
        ))

        # ── Stage 3: Build investigation cases ───────────────────────
        t = time.perf_counter()
        cases = build_investigation_cases(recon, invoices)
        cases.to_csv(data_dir / "investigation_cases.csv", index=False)
        save_cases_to_sqlite(cases, data_dir / "reconai.db")
        result.stages.append(StageResult(
            "investigation_cases", rows=len(cases),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Created {len(cases)} investigation cases",
        ))

        # ── Stage 4: ML anomaly detection ────────────────────────────
        t = time.perf_counter()
        anomalies = detect_anomalies(invoices)
        anomalies.to_csv(data_dir / "anomaly_results.csv", index=False)
        ml_count = int(anomalies["ml_anomaly"].sum())
        result.stages.append(StageResult(
            "anomaly_detection", rows=len(anomalies),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Scored {len(anomalies)} transactions; {ml_count} ML anomalies",
        ))

        # ── Stage 5: Merge ML intelligence with cases ────────────────
        t = time.perf_counter()
        enriched = merge_anomaly_signals(cases, anomalies, invoices)
        enriched.to_csv(data_dir / "investigation_cases_enriched.csv", index=False)
        result.stages.append(StageResult(
            "merge_intelligence", rows=len(enriched),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Enriched {len(enriched)} cases with anomaly signals",
        ))

        # ── Stage 6: Error pattern intelligence ──────────────────────
        t = time.perf_counter()
        patterns, memberships = detect_patterns(enriched, invoices)
        patterned = enrich_cases_with_patterns(enriched, patterns, memberships)
        save_pattern_outputs(patterns, memberships, patterned, data_dir)
        result.stages.append(StageResult(
            "pattern_intelligence", rows=len(patterns),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Detected {len(patterns)} patterns across {len(memberships)} memberships",
        ))

        # ── Stage 7: Root-cause & exposure analysis ──────────────────
        t = time.perf_counter()
        explained = enrich_root_cause(patterned, data_dir)
        save_root_cause_outputs(explained, data_dir)
        result.stages.append(StageResult(
            "root_cause_analysis", rows=len(explained),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"Root-cause explanations for {len(explained)} cases",
        ))

        # ── Stage 8: GST RAG enrichment ──────────────────────────────
        t = time.perf_counter()
        save_kb()
        rag_df = enrich_with_rag(data_dir)
        save_rag_outputs(rag_df, data_dir)
        result.stages.append(StageResult(
            "gst_rag_enrichment", rows=len(rag_df),
            elapsed_s=round(time.perf_counter() - t, 3),
            detail=f"RAG-enriched {len(rag_df)} cases with GST context",
        ))

        # ── Stage 9: Initialise review/audit tables ──────────────────
        t = time.perf_counter()
        init_review_tables(DB)
        result.stages.append(StageResult(
            "init_review_tables", rows=0,
            elapsed_s=round(time.perf_counter() - t, 3),
            detail="Review & audit tables initialised",
        ))

    except Exception as exc:
        result.ok = False
        result.error = f"{type(exc).__name__}: {exc}"

    result.total_elapsed_s = round(time.perf_counter() - t0, 3)
    return result


if __name__ == "__main__":
    r = run_pipeline()
    for s in r.stages:
        print(f"  [{s.name}] {s.detail}  ({s.elapsed_s}s)")
    print(f"\nPipeline {'OK' if r.ok else 'FAILED'} in {r.total_elapsed_s}s")
    if r.error:
        print(f"Error: {r.error}")
