// ═══════════════════════════════════════════════
// Supply Chain Control Tower — API Service Layer
// ═══════════════════════════════════════════════

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api';

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  try {
    const res = await fetch(url, {
      headers: { 'Content-Type': 'application/json', ...options.headers },
      ...options,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}: ${res.statusText}`);
    return await res.json();
  } catch (err) {
    console.error(`API error [${endpoint}]:`, err.message);
    throw err;
  }
}

// ─── Dashboard ───────────────────────────────
export const dashboardAPI = {
  getMetrics: () => request('/dashboard/metrics'),
  getAlerts:  () => request('/alerts/active'),
  getDecisions: () => request('/decisions/pending'),
};

// ─── Anomalies ───────────────────────────────
export const anomalyAPI = {
  getTimeline: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/anomalies/timeline${qs ? '?' + qs : ''}`);
  },
  resolveAnomaly: (id, body) => request(`/anomalies/${id}/resolve`, {
    method: 'POST', body: JSON.stringify(body),
  }),
};

// ─── Decisions ───────────────────────────────
export const decisionAPI = {
  getPending: () => request('/decisions/pending'),
  update: (id, action) => request(`/decisions/${id}`, {
    method: 'PUT', body: JSON.stringify({ action }),
  }),
};

// ─── Blockchain ──────────────────────────────
export const blockchainAPI = {
  getLogs: (params = {}) => {
    const qs = new URLSearchParams(params).toString();
    return request(`/blockchain/logs${qs ? '?' + qs : ''}`);
  },
};

// ─── Map / Network ───────────────────────────
export const mapAPI = {
  getNetwork: () => request('/map/network'),
};
