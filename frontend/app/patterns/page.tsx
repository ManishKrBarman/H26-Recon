'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, formatMoney, formatPercent, humanIssue } from '../../lib/api';

export default function Patterns() {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    api.patterns().then(setData).catch(() => {});
  }, []);

  const items = data?.items || [];

  return (
    <main className="main">
      {/* ── Header ──────────────────────────────────── */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Error Pattern Intelligence</div>
          <h1 className="title">Recurring Patterns</h1>
          <div className="subtitle">
            Move from isolated exceptions to connected financial signals — identify systemic vendor and cross-vendor discrepancies.
          </div>
        </div>
      </div>

      {/* ── Summary stats ──────────────────────────── */}
      {items.length > 0 && (
        <div className="grid stats fade-in" style={{ marginBottom: 20 }}>
          <div className="card">
            <div className="stat-label">Total Patterns</div>
            <div className="stat">{items.length}</div>
          </div>
          <div className="card">
            <div className="stat-label">Total Exposure</div>
            <div className="stat">
              {formatMoney(items.reduce((s: number, x: any) => s + Number(x.financial_exposure || 0), 0))}
            </div>
          </div>
          <div className="card">
            <div className="stat-label">Vendor-Level</div>
            <div className="stat">
              {items.filter((x: any) => x.pattern_type === 'VENDOR_ISSUE_RECURRENCE').length}
            </div>
          </div>
          <div className="card">
            <div className="stat-label">Cross-Vendor</div>
            <div className="stat">
              {items.filter((x: any) => x.pattern_type === 'CROSS_VENDOR_PERIOD').length}
            </div>
          </div>
        </div>
      )}

      {/* ── Table ───────────────────────────────────── */}
      <div className="card fade-in">
        {!data ? (
          <div className="loading">Loading patterns</div>
        ) : items.length === 0 ? (
          <div className="empty-state">
            <span style={{ fontSize: 36 }}>🔗</span>
            <span>No recurring patterns detected. Run the pipeline to analyze data.</span>
          </div>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Pattern</th>
                  <th>Type</th>
                  <th>Issue</th>
                  <th>Vendor</th>
                  <th>Cases</th>
                  <th>Exposure</th>
                  <th>Confidence</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {items.map((x: any) => (
                  <tr key={x.pattern_id}>
                    <td>
                      <div>
                        <b style={{ fontSize: 13 }}>{x.pattern_id}</b>
                        <div className="small" style={{ whiteSpace: 'normal', maxWidth: 280, lineHeight: 1.4 }}>
                          {x.pattern_label}
                        </div>
                      </div>
                    </td>
                    <td>
                      <span className="tag">
                        {x.pattern_type === 'VENDOR_ISSUE_RECURRENCE' ? 'Vendor'
                          : x.pattern_type === 'CROSS_VENDOR_PERIOD' ? 'Cross-Vendor'
                          : x.pattern_type === 'RECURRING_ML_ANOMALY' ? 'ML Anomaly'
                          : x.pattern_type?.replace(/_/g, ' ') || '—'}
                      </span>
                    </td>
                    <td>{humanIssue(x.issue_type)}</td>
                    <td>
                      <b>{x.vendor_code === 'MULTIPLE' ? '—' : x.vendor_code}</b>
                      {x.affected_vendors > 1 && (
                        <div className="small">{x.affected_vendors} vendors</div>
                      )}
                    </td>
                    <td><b>{x.occurrence_count || 0}</b></td>
                    <td>
                      <b>{formatMoney(x.financial_exposure)}</b>
                    </td>
                    <td>
                      <span className={`badge ${Number(x.pattern_confidence || 0) >= 80 ? 'high' : Number(x.pattern_confidence || 0) >= 60 ? 'medium' : 'low'}`}>
                        {formatPercent(x.pattern_confidence)}
                      </span>
                    </td>
                    <td>
                      <Link className="btn" href={`/patterns/${x.pattern_id}`}>
                        Explore →
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </main>
  );
}
