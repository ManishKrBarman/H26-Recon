"""GST knowledge-base retrieval (RAG).

Uses TF-IDF cosine similarity to retrieve relevant GST rule context
for each investigation case.  The fitted vectorizer and document matrix
are cached to ``models/`` so that subsequent queries don't rebuild them.

Model artifacts
---------------
    models/rag_vectorizer.joblib   – fitted TfidfVectorizer
    models/rag_matrix.joblib       – TF-IDF document matrix
    models/rag_docs.joblib         – knowledge base docs list
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

try:
    import joblib
except ImportError:
    from sklearn.externals import joblib  # type: ignore[attr-defined]

from . import config

ROOT = config.ROOT
DATA = config.DATA_DIR
DB = config.DB_PATH
KB = config.KB_PATH
MODELS = config.MODELS_DIR

# Curated, high-level excerpts from official CBIC GST material. These are retrieval context,
# not a complete legal database. Source URLs are kept with every chunk for traceability.
KNOWLEDGE = [
    {"id": "INV-01", "title": "Tax invoice particulars", "text": "A tax invoice should contain prescribed particulars including supplier and recipient details, a unique consecutive invoice number, issue date, HSN or accounting code, description, total and taxable value, applicable tax rate and amount of tax charged, place of supply where applicable, and reverse-charge indication where applicable.", "source": "CBIC GST - Tax Invoice Rules", "url": "https://cbic-gst.gov.in/gst-invoice-rules.html"},
    {"id": "ITC-01", "title": "ITC documentary requirements", "text": "Input tax credit is availed on specified documents such as a supplier invoice or debit note, subject to the applicable conditions and prescribed particulars.", "source": "CBIC GST - Input Tax Credit Rules", "url": "https://cbic-gst.gov.in/input-tax-credit-rules.html"},
    {"id": "ITC-02", "title": "ITC and supplier-reported information", "text": "CBIC material describes conditions around input tax credit and supplier-reported invoice information, including the role of GSTR-2B in the applicable framework.", "source": "CBIC GST - Input Tax Credit Rules", "url": "https://cbic-gst.gov.in/input-tax-credit-rules.html"},
    {"id": "MATCH-01", "title": "Invoice matching context", "text": "Invoice matching should consider invoice or debit note number, invoice or debit note date, and tax amount among the relevant matching information described in GST rules.", "source": "CBIC GST Rules - Matching provisions", "url": "https://cbic-gst.gov.in/pdf/01062021-CGST-Rules-2017-Part-A-Rules.pdf"},
    {"id": "INV-02", "title": "Invoice tax calculation fields", "text": "Tax invoice rules require the invoice to state taxable value, rate of tax and amount of tax charged. These fields can be used as source evidence when ReconAI checks arithmetic consistency.", "source": "CBIC GST - Tax Invoice Rules", "url": "https://cbic-gst.gov.in/gst-invoice-rules.html"},
    {"id": "ITC-03", "title": "Caution on automated ITC conclusions", "text": "GST input tax credit rules contain conditions, documentary requirements and circumstances affecting eligibility. A reconciliation flag should therefore be treated as a review signal rather than an automatic legal conclusion.", "source": "CBIC GST - Input Tax Credit Rules", "url": "https://cbic-gst.gov.in/input-tax-credit-rules.html"},
]


# ── Knowledge base management ─────────────────────────────────────────

def save_kb():
    """Write the curated knowledge base to disk."""
    DATA.mkdir(parents=True, exist_ok=True)
    KB.write_text(json.dumps(KNOWLEDGE, indent=2), encoding="utf-8")


def load_kb() -> List[Dict]:
    """Load the knowledge base, creating it if missing."""
    if not KB.exists():
        save_kb()
    return json.loads(KB.read_text(encoding="utf-8"))


# ── Vectorizer persistence ────────────────────────────────────────────

def build_retriever():
    """Fit the TF-IDF vectorizer on the knowledge base and persist it."""
    docs = load_kb()
    corpus = [d["title"] + " " + d["text"] for d in docs]

    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
    X = vec.fit_transform(corpus)

    MODELS.mkdir(parents=True, exist_ok=True)
    joblib.dump(vec, MODELS / "rag_vectorizer.joblib")
    joblib.dump(X, MODELS / "rag_matrix.joblib")
    joblib.dump(docs, MODELS / "rag_docs.joblib")
    return vec, X, docs


def load_retriever():
    """Load cached vectorizer, matrix, and docs. Returns None if not cached."""
    vpath = MODELS / "rag_vectorizer.joblib"
    mpath = MODELS / "rag_matrix.joblib"
    dpath = MODELS / "rag_docs.joblib"
    if vpath.exists() and mpath.exists() and dpath.exists():
        return joblib.load(vpath), joblib.load(mpath), joblib.load(dpath)
    return None


def get_retriever():
    """Get the retriever, loading from cache or building fresh."""
    loaded = load_retriever()
    if loaded is not None:
        return loaded
    return build_retriever()


# ── Retrieval ──────────────────────────────────────────────────────────

def retrieve(query: str, k: int = 3) -> List[Dict]:
    """Retrieve the top-k most relevant knowledge chunks for a query."""
    vec, X, docs = get_retriever()
    q = vec.transform([query])
    scores = cosine_similarity(q, X).ravel()
    order = scores.argsort()[::-1][:k]
    out = []
    for i in order:
        d = dict(docs[int(i)])
        d["score"] = round(float(scores[int(i)]), 4)
        out.append(d)
    return out


# ── Issue-specific queries ─────────────────────────────────────────────

def query_for_case(row: pd.Series) -> str:
    """Generate a retrieval query tailored to the case's issue type."""
    issue = str(row.get("issue_type", ""))
    queries = {
        "tax_mismatch": "taxable value tax rate tax amount charged invoice tax calculation",
        "missing_gst": "input tax credit invoice supplier reported information GSTR-2B documentary requirements",
        "duplicate_invoice": "invoice number invoice date tax amount matching duplicate invoice",
        "amount_mismatch": "taxable value total value invoice accounting record mismatch",
        "date_mismatch": "invoice date invoice matching date accounting filing period",
        "missing_ledger": "invoice accounting records tax invoice particulars",
    }
    return queries.get(issue, "GST tax invoice input tax credit reconciliation requirements")


# ── Enrichment ─────────────────────────────────────────────────────────

def enrich_with_rag(base: Path = DATA) -> pd.DataFrame:
    """Enrich investigation cases with retrieved GST rule context."""
    cases = pd.read_csv(base / "investigation_cases_explained.csv")
    rows = []
    for _, row in cases.iterrows():
        results = retrieve(query_for_case(row), 3)
        usable = [r for r in results if r["score"] > 0]
        top = usable[0] if usable else {
            "id": "", "title": "No relevant rule retrieved",
            "text": "No sufficiently relevant knowledge-base item was retrieved.",
            "source": "", "url": "", "score": 0.0,
        }
        context = " ".join([f"{r['title']}: {r['text']}" for r in usable[:3]])
        rec = row.to_dict()
        rec.update({
            "gst_rule_context": top["text"],
            "gst_rule_title": top["title"],
            "gst_rule_source": top["source"],
            "gst_rule_url": top["url"],
            "gst_rule_relevance": top["score"],
            "gst_retrieved_context": context,
            "gst_rule_disclaimer": "Retrieved GST context supports investigation; it is not a legal or tax determination.",
        })
        rows.append(rec)
    return pd.DataFrame(rows)


def save_outputs(df: pd.DataFrame, base: Path | None = None, db_path: Path | None = None):
    base = Path(base) if base else config.DATA_DIR
    db_path = Path(db_path) if db_path else config.DB_PATH
    df.to_csv(base / "investigation_cases_rag.csv", index=False)
    with sqlite3.connect(db_path) as conn:
        df.to_sql("investigation_cases_rag", conn, if_exists="replace", index=False)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rag_rule ON investigation_cases_rag(gst_rule_title)")
        conn.commit()


def main():
    save_kb()
    build_retriever()  # Build and cache the vectorizer
    df = enrich_with_rag()
    save_outputs(df)
    print({"cases": len(df), "knowledge_chunks": len(KNOWLEDGE),
           "avg_top_relevance": round(float(df.gst_rule_relevance.mean()), 4)})
    print(f"Retriever saved to {MODELS}")


if __name__ == "__main__":
    main()
