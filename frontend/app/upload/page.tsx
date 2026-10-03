'use client';

import { useState } from 'react';
import Link from 'next/link';
import { API_BASE } from '../../lib/api';

const FORMATS = {
  invoices: {
    columns: ['invoice_id', 'vendor_code', 'invoice_date', 'taxable_amount', 'tax_rate', 'tax_amount', 'total_amount'],
    example: [
      ['INV-000001', 'V0009', '2026-07-31', '110280.73', '12.0', '13233.69', '123514.42'],
      ['INV-000002', 'V0042', '2026-07-10', '24450.16', '18.0', '4401.03', '28851.19'],
    ],
  },
  ledger: {
    columns: ['ledger_ref', 'invoice_id', 'vendor_code', 'entry_date', 'taxable_amount', 'tax_amount', 'total_amount'],
    example: [
      ['LED-000001', 'INV-000001', 'V0009', '2026-07-31', '110280.73', '13233.69', '123514.42'],
      ['LED-000002', 'INV-000002', 'V0042', '2026-07-10', '24450.16', '4401.03', '28851.19'],
    ],
  },
  gst: {
    columns: ['gst_ref', 'invoice_id', 'vendor_code', 'filing_date', 'taxable_amount', 'tax_rate', 'tax_amount'],
    example: [
      ['GST-000001', 'INV-000001', 'V0009', '2026-08-03', '110280.73', '12.0', '13233.69'],
      ['GST-000002', 'INV-000002', 'V0042', '2026-07-13', '24450.16', '18.0', '4401.03'],
    ],
  },
};

type FileKey = 'invoices' | 'ledger' | 'gst';

export default function UploadPage() {
  const [files, setFiles] = useState<Record<FileKey, File | null>>({ invoices: null, ledger: null, gst: null });
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState('');
  const [activeTab, setActiveTab] = useState<FileKey>('invoices');

  const allSelected = files.invoices && files.ledger && files.gst;

  const handleFile = (key: FileKey, file: File | null) => {
    setFiles((prev) => ({ ...prev, [key]: file }));
    setError('');
    setResult(null);
  };

  const handleUpload = async () => {
    if (!allSelected) return;
    setUploading(true);
    setError('');
    setResult(null);

    const form = new FormData();
    form.append('invoices', files.invoices!);
    form.append('ledger', files.ledger!);
    form.append('gst', files.gst!);

    try {
      const res = await fetch(`${API_BASE}/api/upload`, { method: 'POST', body: form });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text);
      }
      const data = await res.json();
      setResult(data);
    } catch (e: any) {
      setError(e.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const fmt = FORMATS[activeTab];

  return (
    <main className="main">
      <div className="page-head">
        <div>
          <div className="eyebrow">Data integration</div>
          <h1 className="title">Upload your data</h1>
          <div className="subtitle">
            Upload your invoices, ledger entries, and GST records as CSV files. The pipeline will run automatically.
          </div>
        </div>
      </div>

      <div className="grid two fade-in">
        {/* Left — file pickers */}
        <div className="grid" style={{ gap: 14 }}>
          {(['invoices', 'ledger', 'gst'] as FileKey[]).map((key) => {
            const label = key === 'gst' ? 'GST Records' : key.charAt(0).toUpperCase() + key.slice(1);
            const file = files[key];
            return (
              <section className="card" key={key}>
                <h2 className="section-title">{label} CSV</h2>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  <label className="btn primary" style={{ position: 'relative', overflow: 'hidden' }}>
                    Choose file
                    <input
                      type="file"
                      accept=".csv"
                      onChange={(e) => handleFile(key, e.target.files?.[0] || null)}
                      style={{ position: 'absolute', inset: 0, opacity: 0, cursor: 'pointer' }}
                    />
                  </label>
                  {file ? (
                    <span style={{ fontSize: 13 }}>
                      <b>{file.name}</b>
                      <span className="muted" style={{ marginLeft: 8 }}>
                        ({(file.size / 1024).toFixed(0)} KB)
                      </span>
                    </span>
                  ) : (
                    <span className="muted" style={{ fontSize: 13 }}>No file selected</span>
                  )}
                </div>
                <div className="small" style={{ marginTop: 8 }}>
                  Required columns: {FORMATS[key].columns.map((c) => <code key={c} className="tag" style={{ marginRight: 4, marginBottom: 2 }}>{c}</code>)}
                </div>
              </section>
            );
          })}

          {/* Upload button */}
          <button
            className={`btn ${allSelected ? 'primary' : ''}`}
            disabled={!allSelected || uploading}
            onClick={handleUpload}
            style={{ padding: '12px 24px', fontSize: 14 }}
          >
            {uploading ? '⟳ Uploading & running pipeline…' : '▶ Upload & run pipeline'}
          </button>

          {error && (
            <div className="card" style={{ borderColor: 'var(--danger-border)' }}>
              <b style={{ color: 'var(--danger)', fontSize: 13 }}>Upload failed</b>
              <p className="small" style={{ marginTop: 4, lineHeight: 1.6, wordBreak: 'break-word' }}>{error}</p>
            </div>
          )}
        </div>

        {/* Right — format reference */}
        <div className="grid" style={{ gap: 14, alignContent: 'start' }}>
          <section className="card">
            <h2 className="section-title">Expected CSV format</h2>
            <div style={{ display: 'flex', gap: 4, marginBottom: 14 }}>
              {(['invoices', 'ledger', 'gst'] as FileKey[]).map((key) => (
                <button
                  key={key}
                  className={`btn ${activeTab === key ? 'primary' : ''}`}
                  onClick={() => setActiveTab(key)}
                  style={{ fontSize: 12, padding: '5px 10px' }}
                >
                  {key === 'gst' ? 'GST Records' : key.charAt(0).toUpperCase() + key.slice(1)}
                </button>
              ))}
            </div>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    {fmt.columns.map((c) => <th key={c}>{c}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {fmt.example.map((row, i) => (
                    <tr key={i}>
                      {row.map((val, j) => <td key={j} className="mono">{val}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="small" style={{ marginTop: 10, lineHeight: 1.7 }}>
              <b>Notes:</b>
              <ul style={{ margin: '4px 0 0 16px' }}>
                <li>Files must be UTF-8 encoded CSV with a header row</li>
                <li>Dates should be YYYY-MM-DD format</li>
                <li>Amounts are numeric (no currency symbols)</li>
                <li>invoice_id is the join key between all three files</li>
                <li>vendor_code groups transactions by supplier</li>
              </ul>
            </div>
          </section>

          <section className="card">
            <h2 className="section-title">How it works</h2>
            <div className="list">
              <div className="row" style={{ gap: 10 }}>
                <span className="tag" style={{ minWidth: 20, textAlign: 'center' }}>1</span>
                <span style={{ fontSize: 13 }}>Upload your three CSV files</span>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <span className="tag" style={{ minWidth: 20, textAlign: 'center' }}>2</span>
                <span style={{ fontSize: 13 }}>Pipeline runs: reconciliation → anomaly detection → pattern analysis → root cause</span>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <span className="tag" style={{ minWidth: 20, textAlign: 'center' }}>3</span>
                <span style={{ fontSize: 13 }}>Investigation cases appear in the queue, ready for review</span>
              </div>
              <div className="row" style={{ gap: 10 }}>
                <span className="tag" style={{ minWidth: 20, textAlign: 'center' }}>4</span>
                <span style={{ fontSize: 13 }}>ML model is trained on your data and saved for future scoring</span>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Pipeline result */}
      {result && (
        <div className="card fade-in" style={{ marginTop: 16, borderColor: result.pipeline?.ok ? 'var(--success-border)' : 'var(--danger-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <b style={{ color: result.pipeline?.ok ? 'var(--success)' : 'var(--danger)', fontSize: 14 }}>
              Pipeline {result.pipeline?.ok ? 'completed' : 'failed'}
            </b>
            <span className="tag">{result.pipeline?.total_elapsed_s}s</span>
          </div>

          {/* Uploaded summary */}
          <div className="grid three" style={{ marginBottom: 14 }}>
            {Object.entries(result.uploaded || {}).map(([name, info]: any) => (
              <div key={name} style={{ background: '#f7f8fa', borderRadius: 'var(--radius-sm)', padding: '10px 14px' }}>
                <div className="stat-label">{name}</div>
                <b>{info.rows} rows</b>
                <div className="small">{info.columns.length} columns</div>
              </div>
            ))}
          </div>

          {/* Stages */}
          {result.pipeline?.stages && (
            <div>
              {result.pipeline.stages.map((s: any, i: number) => (
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

          {result.pipeline?.ok && (
            <div style={{ marginTop: 14, display: 'flex', gap: 8 }}>
              <Link href="/cases" className="btn primary">View investigation queue →</Link>
              <Link href="/" className="btn">Go to dashboard</Link>
            </div>
          )}

          {result.pipeline?.error && (
            <p style={{ color: 'var(--danger)', marginTop: 8, fontSize: 13 }}>{result.pipeline.error}</p>
          )}
        </div>
      )}
    </main>
  );
}
