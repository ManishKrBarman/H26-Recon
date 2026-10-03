'use client';

import { useParams } from 'next/navigation';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, formatMoney, formatPercent, humanIssue, priorityColor, statusColor } from '../../../lib/api';

export default function PatternPage() {
  const { patternId } = useParams<{ patternId: string }>();
  const [p, setP] = useState<any>(null);
  const [memberships, setMemberships] = useState<any[]>([]);
  const [cases, setCases] = useState<any[]>([]);

  useEffect(() => {
    api.pattern(patternId).then((x) => {
      setP(x.pattern);
      setMemberships(x.memberships || []);
      setCases(x.cases || []);
    }).catch(() => {});
  }, [patternId]);

  if (!p) {
    return (
      <main className="main">
        <div className="loading">Loading pattern</div>
      </main>
    );
  }

  return (
    <main className="main">
      {/* ── Header ──────────────────────────────────── */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Pattern Intelligence</div>
          <h1 className="title">{p.pattern_label || patternId}</h1>
          <div className="subtitle" style={{ display: 'flex', gap: 10, alignItems: 'center', marginTop: 6 }}>
            <span className="tag">{p.pattern_type?.replace(/_/g, ' ') || 'Pattern'}</span>
            <span style={{ color: 'var(--ink-muted)' }}>·</span>
            <span>{humanIssue(p.issue_type)}</span>
            {p.period && p.period !== 'MULTI-PERIOD' && (
              <>
                <span style={{ color: 'var(--ink-muted)' }}>·</span>
                <span className="tag">{p.period}</span>
              </>
            )}
          </div>
        </div>
        <Link href="/patterns" className="btn">← Back to Patterns</Link>
      </div>

      {/* ── Stats ───────────────────────────────────── */}
      <div className="grid stats fade-in">
        <div className="card card-glow">
          <div className="stat-label">Affected Cases</div>
          <div className="stat">{p.occurrence_count || cases.length}</div>
        </div>
        <div className="card">
          <div className="stat-label">Financial Exposure</div>
          <div className="stat" >{formatMoney(p.financial_exposure)}</div>
        </div>
        <div className="card">
          <div className="stat-label">Confidence</div>
          <div className="stat">{formatPercent(p.pattern_confidence)}</div>
        </div>
        <div className="card">
          <div className="stat-label">{p.affected_vendors > 1 ? 'Vendors Affected' : 'Vendor'}</div>
          <div className="stat">{p.affected_vendors > 1 ? p.affected_vendors : (p.vendor_code || 'Cross-vendor')}</div>
        </div>
      </div>

      {/* ── Evidence / Explanation ──────────────────── */}
      <section className="card fade-in" style={{ marginTop: 20 }}>
        <h2 className="section-title">Pattern Evidence</h2>
        <div className="evidence">
          <b>{p.explanation || 'Recurring discrepancy pattern detected.'}</b>
        </div>
        <div className="list" style={{ marginTop: 16 }}>
          <div className="row">
            <span className="muted">Pattern ID</span>
            <span className="mono">{p.pattern_id}</span>
          </div>
          <div className="row">
            <span className="muted">Type</span>
            <span className="tag">{p.pattern_type?.replace(/_/g, ' ')}</span>
          </div>
          <div className="row">
            <span className="muted">Issue Type</span>
            <span>{humanIssue(p.issue_type)}</span>
          </div>
          <div className="row">
            <span className="muted">Period</span>
            <span>{p.period || '—'}</span>
          </div>
          <div className="row">
            <span className="muted">Concentration</span>
            <span>{Number(p.concentration || 0).toFixed(2)}</span>
          </div>
          <div className="row">
            <span className="muted">Affected Invoices</span>
            <b>{p.affected_invoices || 0}</b>
          </div>
        </div>
      </section>

      {/* ── Linked cases ───────────────────────────── */}
      {cases.length > 0 && (
        <section className="card fade-in" style={{ marginTop: 20 }}>
          <h2 className="section-title">Linked Investigation Cases</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Invoice</th>
                  <th>Issue</th>
                  <th>Priority</th>
                  <th>Exposure</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {cases.map((c: any) => (
                  <tr key={c.case_id}>
                    <td><b>{c.case_id}</b></td>
                    <td><span className="mono">{c.invoice_id}</span></td>
                    <td>{humanIssue(c.issue_type)}</td>
                    <td><span className={`badge ${priorityColor(c.priority_band)}`}>{c.priority_band}</span></td>
                    <td><b>{formatMoney(c.financial_exposure)}</b></td>
                    <td><span className={`badge ${statusColor(c.status)}`}>{c.status}</span></td>
                    <td>
                      <Link className="btn" href={`/cases/${c.case_id}`}>Investigate →</Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* ── Memberships ────────────────────────────── */}
      {memberships.length > 0 && (
        <section className="card fade-in" style={{ marginTop: 20 }}>
          <h2 className="section-title">Membership Details</h2>
          <div className="list">
            {memberships.map((m: any, i: number) => (
              <div className="row" key={i}>
                <Link href={`/cases/${m.case_id}`} style={{ color: 'var(--brand-light)', fontWeight: 600 }}>
                  {m.case_id}
                </Link>
                <span className="small">{m.membership_reason}</span>
              </div>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}
