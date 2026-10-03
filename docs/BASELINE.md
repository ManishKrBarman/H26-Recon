# Baseline Audit (pre-fix)

Recorded before any changes. Python 3.12.14 / Node 20.20.2, fresh `backend/.venv` from `backend/requirements.txt`.

## What passes

| Check | Command | Result |
|---|---|---|
| Pipeline | `python -m app.pipeline` | OK in 0.85s — but generates only **102 invoices** (100 + 2 dup rows), 12 ground-truth cases, 14 cases, 1 pattern. Contradicts README (1000 invoices / 100 vendors). |
| Evaluation | `python -m app.evaluate` | P/R/F1 = **1.0 on all six issue types** — with only 2 injected cases per type (self-graded on the generator the engine was tuned against). |
| Frontend | `npm ci && npm run build` | Passes clean (all routes compile). |

## Audited problems — reproduced before fixing

| # | Problem | Reproduced? | Evidence |
|---|---|---|---|
| 1 | Review state lost on rerun | **YES** | Recorded `CONFIRM` on CASE-00001 → status `CONFIRMED`. Re-ran pipeline → status back to `OPEN`. `review_decisions` row survives (case_id `CASE-00001` happens to be reused because case ids are positional `CASE-{n:05d}`, but status is never re-applied). Positional ids are inherently unstable: any data change reorders/recounts cases and silently re-points reviews at different cases. |
| 2 | Startup bootstrap checks wrong table | **YES** | `sqlite_master` has no `cases` table (tables: `investigation_cases`, `investigation_cases_patterned`, `investigation_cases_explained`, `investigation_cases_rag`, `error_patterns`, `pattern_memberships`, `review_decisions`, `audit_log`). `ensure_db_initialized` therefore re-runs the full pipeline on **every** API start. |
| 3 | Data/DB path inconsistency | **YES** (by code read) | `api.py` honours `RECON_DATA_DIR` for its own `DB`, but `/api/upload` writes to `ROOT/data`, `/api/pipeline/run` calls `run_pipeline()` with the module default, and `pipeline.py`, `human_review.py`, `feedback.py`, `evaluate.py`, `merge_intelligence.py`, `anomaly.py`, `rag.py`, `schema.py` each hard-code `ROOT/data`. No `config.py` exists. |
| 4 | Fresh dataset tiny, contradicts README | **YES** | `reconciliation.load_data` → `generate(100, seed=42)` → 102 invoices. README claims 1000 invoices / 100 vendors. |
| 5 | Upload unsafe/brittle | **YES** (by code read) | No schema validation, no backup, overwrites live CSVs before pipeline runs synchronously in-request, half-written DB on mid-run failure. |
| 6 | Feedback never influences ranking | **YES** (by code read) | `feedback.py` not imported anywhere; `xgboost` in requirements, unused. |
| 7 | Evaluation self-graded | **YES** | 1.0 across the board, 2 injected cases per type; `evaluate.py` not part of pipeline/API; `/api/metrics` reads a stale CSV. |
| 8 | Hygiene | **YES** | Deprecated `@app.on_event("startup")`; pipeline swallows all exceptions into one string (no per-stage failure); no concurrency guard; no automated tests anywhere; `merge_intelligence.py` dense one-liner style. |

## Drive folder (fetched via gdown)

Folder `1XHllJCKAcszy7Qg377CRlNnYfuD0R_8M` downloaded with `gdown --folder` into `data/external/drive/`.
Contents are a snapshot of a previous pipeline run, **not** new source data. See `data/external/MANIFEST.md` for the full inventory and usage audit. Key finding: `ground_truth.csv` (120 labelled cases) is byte-identical in (invoice_id, discrepancy_type) pairs to the output of `generate(1000, seed=42)` from the current generator, so it serves as an externally-provided evaluation label set.
