'use client';

import Link from 'next/link';
import { useEffect, useState } from 'react';
import { api, formatMoney, humanIssue } from '../lib/api';

export default function Dashboard() {
  const [d, setD] = useState<any>(null);
  const [err, setErr] = useState('');
  const [running, setRunning] = useState(false);
  const [pipeResult, setPipeResult] = useState<any>(null);

  const load = () => api.dashboard().then(setD).catch((e) => setErr(e.message));

  useEffect(() => {
    load();
  }, []);

  const runPipeline = async () => {
    setRunning(true);
    setPipeResult(null);
    try {
      const r = await api.runPipeline();
      setPipeResult(r);
      await load();
    } catch (e: any) {
      setPipeResult({ ok: false, error: e.message });
    } finally {
      setRunning(false);
    }
  };

  if (err) {
    return (
      <main className="main">
        <div className="card" style={{ maxWidth: 480, margin: '60px auto', textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.4 }}>⚠</div>
          <h2 style={{ fontSize: 16, marginBottom: 6 }}>API Unavailable</h2>
          <p className="muted" style={{ marginBottom: 12, fontSize: 13 }}>
            Start the FastAPI backend on port 8000.
          </p>
          <code className="tag" style={{ fontSize: 11 }}>{err}</code>
        </div>
      </main>
    );
  }

  if (!d) {
    return (
      <main className="main">
        <div className="loading">Loading ReconAI</div>
      </main>
    );
  }

  const core = d.cases || {};
  const issues = d.issue_breakdown || [];
  const decisions = d.review_breakdown || [];
  const vendors = d.top_vendors || [];
  const totalCases = core.total || 0;

  return (
    <main className="main">
      {/* Header */}
      <div className="page-head">
        <div>
          <div className="eyebrow">Financial investigation platform</div>
          <h1 className="title">ReconAI Command Center</h1>
          <div className="subtitle">
            Reconcile, investigate, prioritize and review financial exceptions.
          </div>
        </div>
        <div className="btn-group">
          <button className="btn" onClick={runPipeline} disabled={running}>
            {running ? '⟳ Running…' : '▶ Run Pipeline'}
          </button>
          <Link className="btn primary" href="/cases">
            Open investigation queue →
          </Link>
        </div>
      </div>

      {/* Pipeline result */}
      {pipeResult && (
        <div
          className="card fade-in"
          style={{
            marginBottom: 16,
            borderColor: pipeResult.ok ? 'var(--success-border)' : 'var(--danger-border)',
          }}
        >
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <div>
              <b style={{ color: pipeResult.ok ? 'var(--success)' : 'var(--danger)', fontSize: 13 }}>
                Pipeline {pipeResult.ok ? 'completed' : 'failed'}
              </b>
              <span className="small" style={{ marginLeft: 10 }}>
                {pipeResult.total_elapsed_s}s
              </span>
            </div>
            <button className="btn" onClick={() => setPipeResult(null)} style={{ padding: '3px 8px', fontSize: 11 }}>✕</button>
          </div>
          {pipeResult.stages && (
            <div style={{ marginTop: 10 }}>
              {pipeResult.stages.map((s: any, i: number) => (
                <div className="pipeline-stage" key={i}>
                  <div className="stage-icon stage-done">✓</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 12 }}>{s.name.replace(/_/g, ' ')}</div>
                    <div className="small">{s.detail}</div>
                  </div>
                  <span className="tag">{s.elapsed_s}s</span>
                </div>
              ))}
            </div>
          )}
          {pipeResult.error && <p style={{ color: 'var(--danger)', marginTop: 8, fontSize: 12 }}>{pipeResult.error}</p>}
        </div>
      )}

      {/* Stats */}
      <div className="grid stats fade-in">
        <div className="card">
          <div className="stat-label">Invoices Analyzed</div>
          <div className="stat">{d.processed_transactions ?? totalCases}</div>
          <div className="stat-change" style={{ color: 'var(--success, #16a34a)', fontWeight: 500 }}>
            {d.clean_transactions ?? 0} clean ({d.clean_rate ?? 100}%)
          </div>
        </div>
        <div className="card card-glow">
          <div className="stat-label">Flagged Exceptions</div>
          <div className="stat">{totalCases}</div>
          <div className="bar bar-brand" style={{ marginTop: 8 }}>
            <i style={{ width: '100%' }} />
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Pending Review</div>
          <div className="stat">{core.open_cases || 0}</div>
          <div className="bar bar-brand" style={{ marginTop: 8 }}>
            <i style={{ width: totalCases ? `${((core.open_cases || 0) / totalCases) * 100}%` : '0%' }} />
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Critical / High</div>
          <div className="stat">{(core.critical_priority || 0) + (core.high_priority || 0)}</div>
          <div className="bar bar-danger" style={{ marginTop: 8 }}>
            <i style={{ width: totalCases ? `${(((core.critical_priority || 0) + (core.high_priority || 0)) / totalCases) * 100}%` : '0%' }} />
          </div>
        </div>
        <div className="card">
          <div className="stat-label">Financial Exposure</div>
          <div className="stat">{formatMoney(core.total_exposure)}</div>
          <div className="stat-change">{totalCases} exceptions tracked</div>
        </div>
      </div>


      {/* Issue + Decisions + Priority */}
      <div className="grid two" style={{ marginTop: 16 }}>
        <section className="card fade-in">
          <h2 className="section-title">Issue landscape</h2>
          <div className="list">
            {issues.map((x: any) => {
              const pct = totalCases ? (x.count / totalCases) * 100 : 0;
              return (
                <div className="row" key={x.issue_type}>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{humanIssue(x.issue_type)}</div>
                    <div className="bar bar-brand" style={{ width: '100%', marginTop: 3 }}>
                      <i style={{ width: `${pct}%` }} />
                    </div>
                  </div>
                  <b style={{ fontSize: 14 }}>{x.count}</b>
                </div>
              );
            })}
          </div>
        </section>

        <div className="grid" style={{ gap: 14 }}>
          <section className="card fade-in">
            <h2 className="section-title">Review decisions</h2>
            {decisions.length === 0 ? (
              <div className="empty-state" style={{ padding: 16 }}>
                <span className="muted" style={{ fontSize: 12 }}>No reviews yet</span>
              </div>
            ) : (
              <div className="list">
                {decisions.map((x: any) => (
                  <div className="row" key={x.decision}>
                    <span className={`badge ${x.decision?.toLowerCase()}`}>{x.decision}</span>
                    <b>{x.count}</b>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="card fade-in">
            <h2 className="section-title">Priority distribution</h2>
            <div className="list">
              {[
                { label: 'Critical', count: core.critical_priority || 0, cls: 'critical' },
                { label: 'High', count: core.high_priority || 0, cls: 'high' },
                { label: 'Medium', count: core.medium_priority || 0, cls: 'medium' },
                { label: 'Low', count: core.low_priority || 0, cls: 'low' },
              ].map((p) => (
                <div className="row" key={p.label}>
                  <span className={`badge ${p.cls}`}>{p.label}</span>
                  <b>{p.count}</b>
                </div>
              ))}
            </div>
          </section>
        </div>
      </div>

      {/* Top Vendors */}
      {vendors.length > 0 && (
        <section className="card fade-in" style={{ marginTop: 16 }}>
          <h2 className="section-title">Top vendors by exposure</h2>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Vendor</th>
                  <th>Cases</th>
                  <th>Total exposure</th>
                  <th style={{ width: '35%' }}>Share</th>
                </tr>
              </thead>
              <tbody>
                {vendors.slice(0, 8).map((v: any) => {
                  const maxExp = vendors[0]?.total_exposure || 1;
                  return (
                    <tr key={v.vendor_code}>
                      <td><b>{v.vendor_code}</b></td>
                      <td>{v.case_count}</td>
                      <td>{formatMoney(v.total_exposure)}</td>
                      <td>
                        <div className="bar bar-warn" style={{ width: '100%' }}>
                          <i style={{ width: `${(v.total_exposure / maxExp) * 100}%` }} />
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Quick links */}
      <div className="grid three" style={{ marginTop: 16 }}>
        <Link href="/cases" className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, marginBottom: 6, opacity: 0.5 }}>🔍</div>
          <b style={{ fontSize: 13 }}>Investigation queue</b>
          <div className="small">Review prioritized discrepancies</div>
        </Link>
        <Link href="/patterns" className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, marginBottom: 6, opacity: 0.5 }}>🔗</div>
          <b style={{ fontSize: 13 }}>Pattern intelligence</b>
          <div className="small">Explore recurring error signals</div>
        </Link>
        <a href={api.exportCases('csv')} target="_blank" className="card" style={{ textAlign: 'center' }}>
          <div style={{ fontSize: 20, marginBottom: 6, opacity: 0.5 }}>📊</div>
          <b style={{ fontSize: 13 }}>Export report</b>
          <div className="small">Download full investigation CSV</div>
        </a>
      </div>
    </main>
  );
}
