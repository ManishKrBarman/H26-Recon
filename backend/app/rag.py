from __future__ import annotations
import json, sqlite3
from pathlib import Path
from typing import List, Dict
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'data'
DB = DATA / 'reconai.db'
KB = DATA / 'gst_knowledge_base.json'

# Curated, high-level excerpts from official CBIC GST material. These are retrieval context,
# not a complete legal database. Source URLs are kept with every chunk for traceability.
KNOWLEDGE = [
 {"id":"INV-01","title":"Tax invoice particulars","text":"A tax invoice should contain prescribed particulars including supplier and recipient details, a unique consecutive invoice number, issue date, HSN or accounting code, description, total and taxable value, applicable tax rate and amount of tax charged, place of supply where applicable, and reverse-charge indication where applicable.","source":"CBIC GST - Tax Invoice Rules","url":"https://cbic-gst.gov.in/gst-invoice-rules.html"},
 {"id":"ITC-01","title":"ITC documentary requirements","text":"Input tax credit is availed on specified documents such as a supplier invoice or debit note, subject to the applicable conditions and prescribed particulars.","source":"CBIC GST - Input Tax Credit Rules","url":"https://cbic-gst.gov.in/input-tax-credit-rules.html"},
 {"id":"ITC-02","title":"ITC and supplier-reported information","text":"CBIC material describes conditions around input tax credit and supplier-reported invoice information, including the role of GSTR-2B in the applicable framework.","source":"CBIC GST - Input Tax Credit Rules","url":"https://cbic-gst.gov.in/input-tax-credit-rules.html"},
 {"id":"MATCH-01","title":"Invoice matching context","text":"Invoice matching should consider invoice or debit note number, invoice or debit note date, and tax amount among the relevant matching information described in GST rules.","source":"CBIC GST Rules - Matching provisions","url":"https://cbic-gst.gov.in/pdf/01062021-CGST-Rules-2017-Part-A-Rules.pdf"},
 {"id":"INV-02","title":"Invoice tax calculation fields","text":"Tax invoice rules require the invoice to state taxable value, rate of tax and amount of tax charged. These fields can be used as source evidence when ReconAI checks arithmetic consistency.","source":"CBIC GST - Tax Invoice Rules","url":"https://cbic-gst.gov.in/gst-invoice-rules.html"},
 {"id":"ITC-03","title":"Caution on automated ITC conclusions","text":"GST input tax credit rules contain conditions, documentary requirements and circumstances affecting eligibility. A reconciliation flag should therefore be treated as a review signal rather than an automatic legal conclusion.","source":"CBIC GST - Input Tax Credit Rules","url":"https://cbic-gst.gov.in/input-tax-credit-rules.html"},
]


def save_kb():
    DATA.mkdir(parents=True, exist_ok=True)
    KB.write_text(json.dumps(KNOWLEDGE, indent=2), encoding='utf-8')


def retrieve(query: str, k: int = 3) -> List[Dict]:
    if not KB.exists(): save_kb()
    docs = json.loads(KB.read_text(encoding='utf-8'))
    corpus = [d['title'] + ' ' + d['text'] for d in docs]
    vec = TfidfVectorizer(stop_words='english', ngram_range=(1,2))
    X = vec.fit_transform(corpus)
    q = vec.transform([query])
    scores = cosine_similarity(q, X).ravel()
    order = scores.argsort()[::-1][:k]
    out=[]
    for i in order:
        d=dict(docs[int(i)])
        d['score']=round(float(scores[int(i)]),4)
        out.append(d)
    return out


def query_for_case(row: pd.Series) -> str:
    issue = str(row.get('issue_type',''))
    if issue == 'tax_mismatch': return 'taxable value tax rate tax amount charged invoice tax calculation'
    if issue == 'missing_gst': return 'input tax credit invoice supplier reported information GSTR-2B documentary requirements'
    if issue == 'duplicate_invoice': return 'invoice number invoice date tax amount matching duplicate invoice'
    if issue == 'amount_mismatch': return 'taxable value total value invoice accounting record mismatch'
    if issue == 'date_mismatch': return 'invoice date invoice matching date accounting filing period'
    if issue == 'missing_ledger': return 'invoice accounting records tax invoice particulars'
    return 'GST tax invoice input tax credit reconciliation requirements'


def enrich_with_rag(base: Path = DATA) -> pd.DataFrame:
    cases = pd.read_csv(base / 'investigation_cases_explained.csv')
    rows=[]
    for _, row in cases.iterrows():
        results = retrieve(query_for_case(row), 3)
        usable=[r for r in results if r['score'] > 0]
        top = usable[0] if usable else {"id":"","title":"No relevant rule retrieved","text":"No sufficiently relevant knowledge-base item was retrieved.","source":"","url":"","score":0.0}
        context = ' '.join([f"{r['title']}: {r['text']}" for r in usable[:3]])
        rec=row.to_dict()
        rec.update({
            'gst_rule_context': top['text'],
            'gst_rule_title': top['title'],
            'gst_rule_source': top['source'],
            'gst_rule_url': top['url'],
            'gst_rule_relevance': top['score'],
            'gst_retrieved_context': context,
            'gst_rule_disclaimer': 'Retrieved GST context supports investigation; it is not a legal or tax determination.'
        })
        rows.append(rec)
    return pd.DataFrame(rows)


def save_outputs(df: pd.DataFrame, base: Path = DATA):
    df.to_csv(base / 'investigation_cases_rag.csv', index=False)
    with sqlite3.connect(DB) as conn:
        df.to_sql('investigation_cases_rag', conn, if_exists='replace', index=False)
        conn.execute('CREATE INDEX IF NOT EXISTS idx_rag_rule ON investigation_cases_rag(gst_rule_title)')
        conn.commit()


def main():
    save_kb()
    df=enrich_with_rag()
    save_outputs(df)
    print({'cases':len(df), 'knowledge_chunks':len(KNOWLEDGE), 'avg_top_relevance':round(float(df.gst_rule_relevance.mean()),4)})

if __name__=='__main__': main()
