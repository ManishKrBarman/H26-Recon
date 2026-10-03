# Drive data manifest (`data/external/drive/`)

Source: Google Drive folder `1XHllJCKAcszy7Qg377CRlNnYfuD0R_8M` ("Recon"), fetched with
`gdown --folder https://drive.google.com/drive/folders/1XHllJCKAcszy7Qg377CRlNnYfuD0R_8M -O data/external/drive`
on 2026-10-03. Raw files are gitignored (see `.gitignore`); this manifest is committed.

## Verdict up front

**The Drive folder contains no new source data.** It is a snapshot of an earlier run of this
repository's own pipeline, plus model artifacts. There are no GSTR-1/2A/2B exports, no vendor
statement PDFs, no GST circulars/notifications, no problem statement, and no unlabelled
real-world data. Two items are still valuable and are integrated:

1. `ground_truth.csv` — 120 labelled cases. Verified byte-equivalent in
   (invoice_id, discrepancy_type) pairs to the current generator's `generate(1000, seed=42)`
   output, so it is used as the **primary, externally-sourced evaluation label set** and is
   copied to `data/external/ground_truth_drive.csv` (committed) so evaluation never depends
   on re-downloading the Drive folder.
2. `vendors.csv` — 100-vendor master (code, name, GSTIN). Loaded into the DB as the vendor
   master table and used for vendor normalisation/GSTIN-format validation during ingestion.

## Inventory

| File | Type | Size | Rows / keys | What it appears to be |
|---|---|---|---|---|
| `data/invoices.csv` | CSV | 3,097 B | 50 rows × 7 cols | Invoice register snapshot, standard schema, Aug-2026 dates, 14 vendors |
| `data/ledger.csv` | CSV | 3,411 B | 50 rows × 7 cols | Ledger entries matching those 50 invoices |
| `data/gst_records.csv` | CSV | 3,182 B | 50 rows × 7 cols | GST records matching those 50 invoices |
| `data/vendors.csv` | CSV | 4,112 B | 100 rows × 3 cols | Vendor master: vendor_code, vendor_name, gstin |
| `data/ground_truth.csv` | CSV | 9,115 B | 120 rows × 4 cols | Injected-discrepancy labels: 20 per each of the 6 issue types, for a 1,000-invoice run |
| `data/gst_knowledge_base.json` | JSON | 2,525 B | 6 chunks | Same curated 6-chunk GST knowledge base the repo commits |
| `data/anomaly_results.csv` | CSV | 5,252 B | 50 rows × 6 cols | IsolationForest scores for the 50-invoice slice |
| `data/reconciliation_results.csv` | CSV | 4,795 B | 50 rows × 14 cols | Reconciliation output for the 50-invoice slice |
| `data/investigation_cases.csv` | CSV | 206 B | 0 rows × 17 cols | Empty case table (headers only) |
| `data/investigation_cases_enriched.csv` | CSV | 8,018 B | 20 rows × 24 cols | Cases after ML merge |
| `data/investigation_cases_patterned.csv` | CSV | 10,519 B | 20 rows × 31 cols | Cases after pattern enrichment |
| `data/investigation_cases_explained.csv` | CSV | 30,332 B | 20 rows × 41 cols | Cases after root-cause enrichment (UTF-8-BOM) |
| `data/investigation_cases_rag.csv` | CSV | 54,526 B | 20 rows × 48 cols | Final served cases with RAG context |
| `data/error_patterns.csv` | CSV | 1,033 B | 4 rows × 13 cols | Detected patterns |
| `data/pattern_memberships.csv` | CSV | 1,078 B | 20 rows × 3 cols | Pattern ↔ case memberships |
| `data/reconciliation_metrics.csv` | CSV | 283 B | 6 rows × 7 cols | Self-graded eval (1.0 everywhere) from the earlier run |
| `models/anomaly_model.joblib` | binary | 1,335,769 B | — | Trained IsolationForest |
| `models/anomaly_scaler.joblib` | binary | 783 B | — | Fitted StandardScaler |
| `models/anomaly_stats.joblib` | binary | 2,721 B | — | Median/MAD reference stats |
| `models/rag_vectorizer.joblib` | binary | 5,935 B | — | TF-IDF vectorizer |
| `models/rag_matrix.joblib` | binary | 3,563 B | — | TF-IDF document matrix |
| `models/rag_docs.joblib` | binary | 2,170 B | — | KB docs list |
| `models/.gitkeep` | file | 103 B | — | Placeholder |

## Drive usage audit

| File | What it contains | Used by (grep across repo, pre-integration) | Status after this workstream |
|---|---|---|---|
| `data/ground_truth.csv` | 120 labelled injected discrepancies for the 1,000-invoice seed-42 run | `evaluate.py` reads `data/ground_truth.csv` (repo-local), never the Drive copy | **USED** — copied to `data/external/ground_truth_drive.csv`; primary eval label set in `evaluate.py` (`--labels drive`); verified 1:1 with `generate(1000, seed=42)` |
| `data/vendors.csv` | 100-vendor master incl. GSTINs | Nothing (repo generator writes its own identical file) | **USED** — loaded into `vendors` DB table by pipeline; drives GSTIN-format validation in `ingest.py` and vendor names in API/UI |
| `data/invoices.csv` | 50-row invoice snapshot | Nothing | **USED (demo/reference)** — ingested by `python -m app.ingest_external` as the small demo dataset; exercises the alias/normalisation ingestion layer |
| `data/ledger.csv` | 50-row ledger snapshot | Nothing | **USED (demo/reference)** — same as above |
| `data/gst_records.csv` | 50-row GST snapshot | Nothing | **USED (demo/reference)** — same as above |
| `data/gst_knowledge_base.json` | 6 curated GST chunks | `rag.py` uses the repo's own identical copy | **USED** — repo copy kept as canonical; Drive copy verified identical (hash-compared) and documented |
| `data/anomaly_results.csv` | ML scores from old run | Nothing | **UNUSED** — historical pipeline output; superseded by re-running the pipeline (retraining takes <1 s) |
| `data/reconciliation_results.csv` | Old recon output | Nothing | **UNUSED** — same reason |
| `data/investigation_cases*.csv` (5 files) | Old case tables | Nothing | **UNUSED** — same reason |
| `data/error_patterns.csv`, `data/pattern_memberships.csv` | Old pattern output | Nothing | **UNUSED** — same reason |
| `data/reconciliation_metrics.csv` | Old self-graded metrics | `/api/metrics` read a repo-local file with the same name (stale-CSV bug); never the Drive one | **UNUSED** — stale-CSV path replaced by fresh in-pipeline evaluation |
| `models/*.joblib` (6 files) | Trained model artifacts from old run | `anomaly.py`/`rag.py` read/write `models/` paths; nothing loads the Drive copies | **UNUSED** — artifacts are retrained each pipeline run; Drive copies kept for provenance only |

NOT ACCESSED: none — every file in the folder was downloaded and inspected.
