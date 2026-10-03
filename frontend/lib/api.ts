export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL !== undefined
    ? process.env.NEXT_PUBLIC_API_URL.trim().replace(/\/+$/, '')
    : 'http://127.0.0.1:8000';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    cache: 'no-store',
    headers: {
      'Content-Type': 'application/json',
      ...(options?.headers || {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

export const api = {
  // Health
  health: () => request<any>('/api/health'),

  // Dashboard
  dashboard: () => request<any>('/api/dashboard'),

  // Cases
  cases: (params = '') => request<any>(`/api/cases${params ? `?${params}` : ''}`),
  caseById: (id: string) => request<any>(`/api/cases/${encodeURIComponent(id)}`),
  review: (id: string, decision: string, notes: string, reviewer: string) =>
    request<any>(`/api/cases/${encodeURIComponent(id)}/review`, {
      method: 'POST',
      body: JSON.stringify({ decision, notes, reviewer }),
    }),

  // Patterns
  patterns: () => request<any>('/api/patterns'),
  pattern: (id: string) => request<any>(`/api/patterns/${encodeURIComponent(id)}`),

  // Audit
  audit: (caseId: string) => request<any>(`/api/audit/${encodeURIComponent(caseId)}`),

  // Pipeline
  runPipeline: () => request<any>('/api/pipeline/run', { method: 'POST' }),
  pipelineStatus: () => request<any>('/api/pipeline/status'),

  // Export
  exportCases: (format: 'csv' | 'json' = 'csv') =>
    `${API_BASE}/api/export/cases?format=${format}`,
  exportAudit: () => `${API_BASE}/api/export/audit`,

  // Metrics
  metrics: () => request<any>('/api/metrics'),

  // Rules
  searchRules: (q: string) => request<any>(`/api/rules/search?q=${encodeURIComponent(q)}`),
};

/* ── Formatting helpers ───────────────────────────── */

export function formatMoney(n: number | string | null | undefined): string {
  const v = Number(n || 0);
  return `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`;
}

export function formatPercent(n: number | string | null | undefined): string {
  return `${Number(n || 0).toFixed(0)}%`;
}

export function humanIssue(s: string): string {
  return (s || '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function priorityColor(band: string): string {
  const b = (band || '').toUpperCase();
  if (b === 'CRITICAL') return 'critical';
  if (b === 'HIGH') return 'high';
  if (b === 'MEDIUM') return 'medium';
  return 'low';
}

export function statusColor(status: string): string {
  const s = (status || '').toUpperCase();
  if (s === 'CONFIRMED') return 'confirmed';
  if (s === 'REJECTED') return 'rejected';
  if (s === 'NEEDS_REVIEW') return 'needs_review';
  return 'open';
}
