'use client';

import Link from 'next/link';
import { useEffect, useState, useCallback } from 'react';
import { api, formatMoney, formatPercent, humanIssue, priorityColor, statusColor } from '../../lib/api';

export default function Cases() {
  const [data, setData] = useState<any>(null);
  const [status, setStatus] = useState('');
  const [priority, setPriority] = useState('');
  const [issueType, setIssueType] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const limit = 50;

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (priority) params.set('priority', priority);
    if (issueType) params.set('issue_type', issueType);
    if (search.trim()) params.set('search', search.trim());
    params.set('limit', String(limit));
    params.set('offset', String(page * limit));
    api.cases(params.toString()).then(setData).catch(() => {});
  }, [status, priority, issueType, search, page]);

  useEffect(() => {
    load();
  }, [load]);

  const items = data?.items || [];
  const total = data?.total || 0;
  const totalPages = Math.ceil(total / limit);

  return (
    <main className="main">
      {/* ── Header ──────────────────────────────────── */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Investigation Queue</div>
          <h1 className="title">Cases</h1>
          <div className="subtitle">
            Prioritized discrepancies with evidence, root-cause analysis, and recommended actions.
          </div>
        </div>
        <div className="btn-group">
          <a href={api.exportCases('csv')} target="_blank" className="btn">
            ↓ Export CSV
          </a>
          <a href={api.exportCases('json')} target="_blank" className="btn">
            ↓ Export JSON
          </a>
        </div>
      </div>

      {/* ── Filters ─────────────────────────────────── */}
      <div className="filters">
        <input
          className="input"
          placeholder="Search case, invoice, vendor…"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
          style={{ minWidth: 220 }}
        />
        <select className="select" value={status} onChange={(e) => { setStatus(e.target.value); setPage(0); }}>
          <option value="">All statuses</option>
          <option value="OPEN">Open</option>
          <option value="CONFIRMED">Confirmed</option>
          <option value="REJECTED">Rejected</option>
          <option value="NEEDS_REVIEW">Needs Review</option>
        </select>
        <select className="select" value={priority} onChange={(e) => { setPriority(e.target.value); setPage(0); }}>
          <option value="">All priorities</option>
          <option value="CRITICAL">Critical</option>
          <option value="HIGH">High</option>
          <option value="MEDIUM">Medium</option>
          <option value="LOW">Low</option>
        </select>
        <select className="select" value={issueType} onChange={(e) => { setIssueType(e.target.value); setPage(0); }}>
          <option value="">All issue types</option>
          <option value="duplicate_invoice">Duplicate Invoice</option>
          <option value="missing_ledger">Missing Ledger</option>
          <option value="missing_gst">Missing GST</option>
          <option value="amount_mismatch">Amount Mismatch</option>
          <option value="tax_mismatch">Tax Mismatch</option>
          <option value="date_mismatch">Date Mismatch</option>
        </select>
        {(status || priority || issueType || search) && (
          <button
            className="btn"
            onClick={() => { setStatus(''); setPriority(''); setIssueType(''); setSearch(''); setPage(0); }}
            style={{ fontSize: 12 }}
          >
            ✕ Clear
          </button>
        )}
        <span className="muted" style={{ marginLeft: 'auto', fontSize: 12 }}>
          {total} case{total !== 1 ? 's' : ''} found
        </span>
      </div>

      {/* ── Table ───────────────────────────────────── */}
      <div className="card fade-in">
        <div className="table-wrap">
          {!data ? (
            <div className="loading">Loading cases</div>
          ) : items.length === 0 ? (
            <div className="empty-state">
              <span style={{ fontSize: 36 }}>📋</span>
              <span>No cases match the current filters.</span>
            </div>
          ) : (
            <table className="table">
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Invoice</th>
                  <th>Vendor</th>
                  <th>Issue</th>
                  <th>Priority</th>
                  <th>Exposure</th>
                  <th>Confidence</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((c: any) => (
                  <tr key={c.case_id}>
                    <td>
                      <b>{c.case_id}</b>
                    </td>
                    <td>
                      <span className="mono">{c.invoice_id}</span>
                    </td>
                    <td>{c.vendor_code}</td>
                    <td>{humanIssue(c.issue_type)}</td>
                    <td>
                      <span className={`badge ${priorityColor(c.priority_band)}`}>
                        {c.priority_band || 'LOW'}
                      </span>
                    </td>
                    <td><b>{formatMoney(c.financial_exposure)}</b></td>
                    <td>{formatPercent(c.match_confidence)}</td>
                    <td>
                      <span className={`badge ${statusColor(c.status)}`}>
                        {c.status || 'OPEN'}
                      </span>
                    </td>
                    <td>
                      <Link className="btn" href={`/cases/${c.case_id}`}>
                        Investigate →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Pagination ─────────────────────────────── */}
        {totalPages > 1 && (
          <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginTop: 16 }}>
            <button className="btn" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              ← Previous
            </button>
            <span className="muted" style={{ padding: '9px 0', fontSize: 13 }}>
              Page {page + 1} of {totalPages}
            </span>
            <button className="btn" disabled={page >= totalPages - 1} onClick={() => setPage((p) => p + 1)}>
              Next →
            </button>
          </div>
        )}
      </div>
    </main>
  );
}
