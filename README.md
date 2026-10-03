# ReconAI — Intelligent Tax Reconciliation & Investigation

ReconAI is a fintech tool that automates the investigation of financial and tax discrepancies across invoices, accounting ledgers, and GST records. It goes beyond simple invoice matching — it detects errors, finds recurring patterns, explains root causes, estimates financial exposure, and keeps humans in control of every final decision.

---

## The Problem

Finance teams reconcile invoices, payments, ledgers and GST records across disconnected systems. This is painful because:

- **Duplicate or missing records** slip through when data lives in separate spreadsheets and ERPs.
- **Amount, tax, and date mismatches** between invoice, ledger, and GST records go unnoticed until audit time.
- **Unusual transactions** (outlier amounts, odd timing) don't get flagged unless someone manually spots them.
- **Recurring vendor errors** repeat quarter after quarter because each exception is treated in isolation.
- **Late detection** means the financial impact (wrong ITC claims, overpayments, compliance risk) compounds silently.
- **Poor auditability** — when issues are found, there's no trail of who reviewed what, when, or why.

The result: wasted analyst hours, missed tax exposures, and compliance risk that surfaces too late.

---

## How ReconAI Solves It

ReconAI runs an end-to-end investigation pipeline that processes raw financial data through nine stages, producing prioritized investigation cases that analysts can review, decide on, and audit.

```
Source Data → Cleaning → 3-Way Reconciliation → Investigation Cases →
ML Anomaly Detection → Intelligence Merge → Pattern Detection →
Root-Cause Analysis → GST Rule Context → Human Review → Audit Trail
```

The core philosophy:

1. **Deterministic rules for objective checks** — amount/tax/date comparisons, duplicate detection, and missing-record identification use exact and fuzzy matching with configurable tolerances. No black-box guessing for financial arithmetic.

2. **ML for anomaly detection** — an Isolation Forest model learns normal transaction behaviour per vendor (amounts, frequencies, timing) and flags statistical outliers. This catches things rules can't: unusual vendor patterns, spike transactions, timing anomalies.

3. **Human approval for final decisions** — every flagged case goes through human review. Analysts see evidence, root-cause explanations, and GST context, then explicitly Confirm, Reject, or mark as Needs Review. No automated action without human sign-off.

---

## Approach & Architecture

### Stage 1: Synthetic Data Generation

[`generate_data.py`](backend/app/generate_data.py) creates a realistic dataset with controlled discrepancy injection:

- 1000 invoices across 100 vendors with varied amounts, tax rates (5/12/18/28% GST), and dates
- Matching ledger entries and GST filing records
- **Intentionally injected discrepancies** (2% each): duplicate invoices, missing ledger entries, missing GST records, amount mismatches (8% alteration), tax mismatches (10% alteration), date mismatches (15-day shift)
- A ground truth CSV for measurable evaluation (precision/recall/F1)

This makes the system demo-ready and testable — every detected issue can be verified against known injections.

### Stage 2: Three-Way Reconciliation

[`reconciliation.py`](backend/app/reconciliation.py) performs deterministic matching across three data sources:

- **ID matching**: Fuzzy matching using RapidFuzz on normalised invoice identifiers with a 94% similarity threshold to prevent false cross-matches
- **Composite scoring**: Weighted combination of ID similarity (45%), vendor match (15%), amount similarity (20%), date proximity (10%), and tax similarity (10%)
- **Duplicate detection**: Identifies near-duplicate invoices by fingerprinting (same vendor + similar amount + close date + high ID similarity)
- **Issue flagging**: Each invoice row gets tagged with specific issues (`duplicate_invoice`, `missing_ledger`, `missing_gst`, `amount_mismatch`, `tax_mismatch`, `date_mismatch`) with evidence strings explaining what was found

The output is one row per invoice with match confidence, issue flags, severity, and financial exposure.

### Stage 3: Investigation Case Builder

[`investigation.py`](backend/app/investigation.py) turns row-level reconciliation flags into structured, actionable investigation cases:

- **One case per issue** — if an invoice has both a duplicate flag and a tax mismatch, that produces two separate cases, each independently reviewable
- **Priority scoring** — a bounded formula combining severity weight (45%), financial exposure (30%, log-scaled), match confidence (15%), and issue criticality (10%)
- **Structured metadata** — each case carries the issue type, category, severity, evidence, recommended action, and links to the source invoice/ledger/GST references

### Stage 4: ML Anomaly Detection

[`anomaly.py`](backend/app/anomaly.py) uses an Isolation Forest trained on per-vendor behavioural features:

| Feature | What it captures |
|---------|-----------------|
| `taxable_amount`, `tax_amount`, `total_amount` | Raw transaction scale |
| `vendor_txn_count` | Vendor transaction frequency |
| `vendor_amount_mean_ratio` | How this transaction compares to the vendor's average |
| `vendor_amount_std_ratio` | How far from the vendor's historical spread |
| `vendor_tax_mean_ratio` | Tax amount vs vendor baseline |
| `day_of_month`, `day_of_week` | Timing patterns |

The model scores every transaction 0–100 and provides human-readable anomaly reasons by identifying which features deviate most from the learned baseline.

### Stage 5: Intelligence Merge

[`merge_intelligence.py`](backend/app/merge_intelligence.py) combines deterministic reconciliation signals with ML anomaly scores:

- Merges anomaly scores, ML anomaly flags, and anomaly reasons onto investigation cases
- Computes a combined priority score that accounts for both rule-based findings and statistical outliers
- Tags each case as `DETERMINISTIC`, `DETERMINISTIC + ML`, or `ML_ONLY`

### Stage 6: Error Pattern Intelligence

[`pattern_intelligence.py`](backend/app/pattern_intelligence.py) moves from isolated exceptions to connected financial signals using NetworkX-based relationship analysis:

- **Vendor-issue recurrence** — detects when the same vendor repeatedly produces the same discrepancy type (≥3 occurrences). This identifies systematic vendor problems, not one-off errors.
- **Cross-vendor period patterns** — detects when multiple vendors share the same issue type in the same month (≥4 cases across ≥2 vendors). This identifies systemic process problems like month-end timing issues.
- **Recurring ML anomaly patterns** — detects vendors with repeated statistical outliers, catching behavioural patterns that rules alone miss.

Each pattern gets a confidence score (recurrence count + concentration strength), total financial exposure, and a plain-English explanation.

### Stage 7: Root-Cause Analysis

[`root_cause.py`](backend/app/root_cause.py) enriches every case with:

- **Likely root cause** — deterministic identification based on issue type and source record comparison (e.g., "Invoice taxable ₹1,62,500 vs ledger taxable ₹1,75,500 — difference ₹13,000")
- **Refined financial exposure** — recalculated from source records rather than approximations
- **Combined explanation** — merges the root-cause detail, pattern context, and ML anomaly signals into one investigation narrative
- **Priority banding** — CRITICAL (≥80), HIGH (≥60), MEDIUM (≥35), LOW (<35)

### Stage 8: GST Rule Context (RAG)

[`rag.py`](backend/app/rag.py) implements retrieval-augmented context from a curated GST knowledge base:

- **Knowledge base**: 6 curated chunks from CBIC GST rules covering tax invoice requirements, ITC documentation, invoice matching rules, and automated conclusion cautions — each with source URLs for traceability
- **Retrieval**: TF-IDF vectorisation with bigram support and cosine similarity ranking
- **Issue-specific queries**: Each issue type maps to a targeted retrieval query (e.g., tax mismatch → "taxable value tax rate tax amount charged invoice tax calculation")
- **Disclaimer**: Every retrieved context explicitly states it's not a legal determination — compliance decisions remain with the human reviewer

### Stage 9: Human Review & Audit Trail

[`human_review.py`](backend/app/human_review.py) provides the human-in-the-loop workflow:

- **Three decisions**: `CONFIRM` (validated finding), `REJECT` (false positive), `NEEDS_REVIEW` (escalate)
- **Status tracking**: Cases move from OPEN → CONFIRMED/REJECTED/NEEDS_REVIEW
- **Reviewer attribution**: Every decision records who made it and when
- **Audit log**: Immutable event trail — every review decision, status change, and note is logged with timestamps
- **Export**: Full reviewed dataset exportable as CSV for downstream reporting

---

## Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Data processing | Pandas, NumPy | Tabular data wrangling and feature engineering |
| Fuzzy matching | RapidFuzz | Fast string similarity for ID reconciliation |
| ML | Scikit-learn (Isolation Forest) | Unsupervised anomaly detection |
| Graph analysis | NetworkX | Vendor-issue relationship modelling for pattern detection |
| Knowledge retrieval | Scikit-learn (TF-IDF) | Lightweight RAG over GST knowledge base |
| Database | SQLite | Single-file persistence for cases, patterns, reviews, audit |
| API | FastAPI | REST API with validation, CORS, and auto-documentation |
| Frontend | Next.js 14 + TypeScript | Investigation dashboard and review interface |
| Evaluation | Ground truth CSV | Precision/recall/F1 measurement against known discrepancies |

---

## Project Structure

```
ReconAI/
├── backend/
│   ├── app/
│   │   ├── api.py                    # FastAPI endpoints
│   │   ├── pipeline.py               # End-to-end pipeline orchestrator
│   │   ├── generate_data.py          # Synthetic data with injected discrepancies
│   │   ├── reconciliation.py         # 3-way invoice/ledger/GST matching
│   │   ├── investigation.py          # Case builder with priority scoring
│   │   ├── anomaly.py                # Isolation Forest anomaly detection
│   │   ├── merge_intelligence.py     # Combine deterministic + ML signals
│   │   ├── pattern_intelligence.py   # Recurring pattern detection
│   │   ├── root_cause.py             # Root-cause analysis + exposure
│   │   ├── rag.py                    # GST knowledge base retrieval
│   │   ├── human_review.py           # Review decisions + audit trail
│   │   ├── evaluate.py               # Precision/recall against ground truth
│   │   ├── feedback.py               # Review feedback analytics
│   │   ├── schema.py                 # SQLAlchemy ORM models
│   │   └── init_db.py                # Database initialisation
│   └── requirements.txt
├── frontend/
│   ├── app/
│   │   ├── page.tsx                  # Dashboard
│   │   ├── cases/page.tsx            # Investigation queue
│   │   ├── cases/[caseId]/page.tsx   # Case detail + review
│   │   ├── patterns/page.tsx         # Pattern list
│   │   ├── patterns/[patternId]/page.tsx  # Pattern detail
│   │   ├── layout.tsx                # Root layout
│   │   └── globals.css               # Design system
│   ├── lib/api.ts                    # API client + helpers
│   └── package.json
├── data/                             # Generated by pipeline (gitignored)
│   └── gst_knowledge_base.json       # Curated GST rules (committed)
└── .gitignore
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Service health check |
| `/api/dashboard` | GET | Summary stats, issue breakdown, priorities, top vendors |
| `/api/cases` | GET | Filtered, paginated case list (status, priority, issue type, search) |
| `/api/cases/{id}` | GET | Full case detail with reviews and audit trail |
| `/api/cases/{id}/review` | POST | Submit review decision (CONFIRM / REJECT / NEEDS_REVIEW) |
| `/api/patterns` | GET | All detected recurring patterns |
| `/api/patterns/{id}` | GET | Pattern detail with linked cases |
| `/api/audit/{id}` | GET | Audit trail for a specific case |
| `/api/pipeline/run` | POST | Run the full 9-stage processing pipeline |
| `/api/pipeline/status` | GET | Check if the database is populated |
| `/api/export/cases` | GET | Export all cases as CSV or JSON |
| `/api/export/audit` | GET | Export full audit trail as CSV |
| `/api/metrics` | GET | Evaluation metrics (precision/recall/F1) |
| `/api/rules/search` | GET | Search the GST knowledge base |

---

## Getting Started

### Prerequisites

- Python 3.11+
- Node.js 18+

### Backend

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

**Generate synthetic data** (only needed on first setup):

```bash
python -m app.generate_data --n 1000 --seed 42
```

**Start the API server**:

```bash
uvicorn app.api:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### Run the Pipeline

Either click **"Run Pipeline"** on the dashboard, or:

```bash
curl -X POST http://localhost:8000/api/pipeline/run
```

This executes all 9 stages (~7 seconds) and populates the database. The dashboard and investigation queue will reflect the results immediately.

---

## Deployment

ReconAI is fully containerized and production-ready for deployment on any cloud VPS (AWS, GCP, DigitalOcean, Hetzner), PaaS, or bare-metal Linux server.

### 1-Command Deployment with Docker Compose

```bash
# Clone and launch all services with volume persistence
git clone https://github.com/ManishKrBarman/H26-Recon.git
cd Recon
docker compose up -d --build
```

- **Frontend**: `http://<your-server-ip>:3000`
- **Backend API & Swagger Docs**: `http://<your-server-ip>:8000/docs`

The SQLite database and trained ML models are persisted in `./data` and `./models`. On a fresh clone, the backend automatically initializes demo data and runs the pipeline on first boot.

### Single-Domain Production with Nginx & SSL

For unified single-domain deployment with SSL on ports 80/443 and 100MB file upload limits:

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

👉 **For the complete production runbook, see [DEPLOYMENT.md](DEPLOYMENT.md)** covering Let's Encrypt SSL, automated database backups, systemd service units, and cloud deployment on Vercel + Render/Railway.

---

## Evaluation

The system can be evaluated against the synthetic ground truth:

```bash
cd backend
python -m app.evaluate
```

This computes precision, recall, and F1 for each discrepancy type by comparing detected issues against the known injected discrepancies.

---

## Key Design Decisions

1. **One case per issue, not per invoice** — an invoice with both a duplicate flag and a tax mismatch produces two independent cases. This makes the review workflow granular and each decision self-contained.

2. **Bounded priority scoring** — financial exposure is log-scaled to prevent a single large transaction from overwhelming the queue. Priority combines severity, exposure, confidence, and issue criticality.

3. **Pattern detection over graph relationships** — instead of just counting issues, the pattern engine builds vendor-issue-invoice graphs to detect structural recurrence. A vendor with 5 tax mismatches across 5 months is a different signal than 5 vendors each with 1 mismatch.

4. **RAG with disclaimers** — GST rule context is retrieved to support investigation, but every piece of retrieved context carries an explicit disclaimer. The system never claims to make legal or compliance determinations.

5. **Immutable audit trail** — review decisions are append-only. Changing a decision creates a new record with the previous status preserved. This is critical for compliance and audit readiness.

6. **Pipeline as a single operation** — all processing stages run through one orchestrator. This avoids partial states where reconciliation is fresh but patterns are stale.

---

## License

MIT
