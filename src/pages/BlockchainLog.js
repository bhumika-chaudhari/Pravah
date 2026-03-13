import React, { useState, useEffect, useCallback } from 'react';
import {
  Link2, Search, Filter, Download,
  CheckCircle, AlertTriangle, RefreshCw,
  Shield, ChevronDown, ChevronUp, Hash
} from 'lucide-react';
import { blockchainAPI } from '../services/api';
import './pages.css';

const EVENT_META = {
  ALERT_CREATED:    { color: 'red',    label: 'Alert Created',    chip: 'chip-critical' },
  ALERT_RESOLVED:   { color: 'green',  label: 'Alert Resolved',   chip: 'chip-resolved' },
  DECISION_SAVED:   { color: 'amber',  label: 'Decision Saved',   chip: 'chip-pending' },
  DECISION_EXECUTED:{ color: 'cyan',   label: 'Decision Executed',chip: 'chip-medium' },
};

function getEventMeta(type) {
  return EVENT_META[type] || { color: 'cyan', label: type?.replace(/_/g,' ') || '—', chip: 'chip-medium' };
}

function truncHash(h) {
  if (!h || h.length < 16) return h || '—';
  return `${h.slice(0,10)}…${h.slice(-8)}`;
}

function LogRow({ log, expanded, onToggle }) {
  const meta   = getEventMeta(log.event_type);
  const ts     = log.created_at ? new Date(log.created_at).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit'
  }) : '—';
  const payload = log.payload_json || {};
  const isObj   = typeof payload === 'object';

  return (
    <>
      <tr style={{ cursor: 'pointer' }} onClick={onToggle}>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)' }}>#{log.id}</td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', whiteSpace: 'nowrap' }}>{ts}</td>
        <td>
          <span className={`chip ${meta.chip}`}>{meta.label}</span>
        </td>
        <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-secondary)' }}>
          {log.ref_table} #{log.ref_id}
        </td>
        <td>
          <span
            className="hash-text tooltip"
            data-tip={log.curr_hash}
            onClick={e => { e.stopPropagation(); navigator.clipboard?.writeText?.(log.curr_hash); }}
          >
            {truncHash(log.curr_hash)}
          </span>
        </td>
        <td>
          {log.verified ? (
            <span className="chip chip-verified"><CheckCircle size={10} /> Verified</span>
          ) : (
            <span className="chip chip-critical"><AlertTriangle size={10} /> Unverified</span>
          )}
        </td>
        <td style={{ textAlign: 'right' }}>
          <button className="bc-expand" onClick={onToggle}>
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          </button>
        </td>
      </tr>
      {expanded && (
        <tr>
          <td colSpan={7} style={{ padding: '0 14px 16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, paddingTop: 8 }}>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: '0.1em' }}>PAYLOAD</div>
                <pre className="bc-payload">{JSON.stringify(isObj ? payload : { data: payload }, null, 2)}</pre>
              </div>
              <div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)', marginBottom: 4, letterSpacing: '0.1em' }}>CHAIN HASHES</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', marginBottom: 2 }}>PREV</div>
                    <div className="hash-text" style={{ wordBreak: 'break-all', fontSize: '0.62rem' }}>{log.prev_hash || '(genesis)'}</div>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'center', color: 'var(--border-mid)' }}>↓</div>
                  <div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', marginBottom: 2 }}>CURR</div>
                    <div className="hash-text" style={{ wordBreak: 'break-all', fontSize: '0.62rem', color: 'var(--cyan)' }}>{log.curr_hash || '—'}</div>
                  </div>
                </div>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

const PAGE_SIZE = 15;

export default function BlockchainLog() {
  const [logs, setLogs]           = useState([]);
  const [loading, setLoading]     = useState(true);
  const [error, setError]         = useState(null);
  const [eventFilter, setFilter]  = useState('all');
  const [search, setSearch]       = useState('');
  const [expanded, setExpanded]   = useState(null);
  const [page, setPage]           = useState(1);

  const fetchLogs = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params = { limit: 200, offset: 0 };
      if (eventFilter !== 'all') params.event_type = eventFilter;
      const data = await blockchainAPI.getLogs(params);
      const arr  = Array.isArray(data) ? data : [];
      setLogs(arr);
      setPage(1);
    } catch (err) {
      setError(err.message || 'Failed to load blockchain logs');
    } finally {
      setLoading(false);
    }
  }, [eventFilter]);

  useEffect(() => { fetchLogs(); }, [fetchLogs]);

  const exportLogs = () => {
    const str  = JSON.stringify(filtered, null, 2);
    const blob = new Blob([str], { type: 'application/json' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `blockchain_audit_${new Date().toISOString().slice(0,10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const filtered = logs.filter(log => {
    if (eventFilter !== 'all' && log.event_type !== eventFilter) return false;
    if (search) {
      const q = search.toLowerCase();
      return (
        log.event_type?.toLowerCase().includes(q) ||
        log.ref_table?.toLowerCase().includes(q)  ||
        log.curr_hash?.toLowerCase().includes(q)  ||
        JSON.stringify(log.payload_json)?.toLowerCase().includes(q)
      );
    }
    return true;
  });

  const totalPages  = Math.ceil(filtered.length / PAGE_SIZE);
  const paginated   = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  const stats = {
    total:    logs.length,
    alerts:   logs.filter(l => l.event_type?.includes('ALERT')).length,
    decisions:logs.filter(l => l.event_type?.includes('DECISION')).length,
    verified: logs.filter(l => l.verified).length,
  };

  const allVerified = stats.verified === stats.total && stats.total > 0;

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">BLOCKCHAIN AUDIT CHAIN</h1>
          <div className="section-subtitle">CRYPTOGRAPHIC IMMUTABLE LEDGER · TAMPER-PROOF EVENT LOG</div>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn btn-ghost" onClick={exportLogs}>
            <Download size={13} /> Export JSON
          </button>
          <button className="btn btn-ghost" onClick={fetchLogs}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* ── Stats ── */}
      <div className="grid-4 mb-6">
        {[
          { label: 'Total Entries',    val: stats.total,     icon: Hash,         color: 'cyan' },
          { label: 'Alert Events',     val: stats.alerts,    icon: AlertTriangle,color: 'red' },
          { label: 'Decision Events',  val: stats.decisions, icon: Link2,        color: 'amber' },
          { label: 'Verified',         val: stats.verified,  icon: Shield,       color: 'green' },
        ].map(({ label, val, icon: Icon, color }) => (
          <div key={label} className="metric-card">
            <div className="mc-top">
              <span className="mc-label">{label}</span>
              <div className={`mc-icon mc-icon-${color}`}><Icon size={16} /></div>
            </div>
            <div className={`mc-value mc-value-${color}`}>{val}</div>
          </div>
        ))}
      </div>

      {/* ── Integrity Banner ── */}
      {!loading && !error && (
        <div className={`bc-integrity mb-6 ${!allVerified ? 'bc-integrity-warn' : ''}`}
          style={!allVerified ? { background: 'rgba(255,61,87,0.06)', borderColor: 'rgba(255,61,87,0.3)', color: 'var(--red)' } : {}}
        >
          {allVerified
            ? <><Shield size={14} /> BLOCKCHAIN INTEGRITY VERIFIED — All {stats.total} entries are tamper-proof and chronologically ordered.</>
            : <><AlertTriangle size={14} /> WARNING: {stats.total - stats.verified} unverified entries detected. Review required.</>
          }
        </div>
      )}

      {/* ── Filters ── */}
      <div className="card mb-6" style={{ padding: '14px 20px' }}>
        <div className="filter-bar">
          <Filter size={14} color="var(--text-muted)" />
          <span className="filter-label">FILTER:</span>

          <select className="select" value={eventFilter} onChange={e => setFilter(e.target.value)}>
            <option value="all">All Events</option>
            <option value="ALERT_CREATED">Alert Created</option>
            <option value="ALERT_RESOLVED">Alert Resolved</option>
            <option value="DECISION_SAVED">Decision Saved</option>
            <option value="DECISION_EXECUTED">Decision Executed</option>
          </select>

          <div style={{ position: 'relative', flex: 1, maxWidth: 280 }}>
            <Search size={13} style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', pointerEvents: 'none' }} />
            <input
              className="input"
              style={{ paddingLeft: 30, width: '100%' }}
              placeholder="Search hash, type, payload..."
              value={search}
              onChange={e => { setSearch(e.target.value); setPage(1); }}
            />
          </div>

          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
            {filtered.length} / {stats.total} entries
          </span>
        </div>
      </div>

      {/* ── Table ── */}
      <div className="card" style={{ padding: 20 }}>
        {loading ? (
          <div className="loading-screen"><div className="spinner" /><div className="loading-text">FETCHING AUDIT CHAIN...</div></div>
        ) : error ? (
          <div className="error-box">
            <AlertTriangle size={24} color="var(--red)" />
            <div className="error-title">FETCH FAILED</div>
            <div className="error-msg">{error}</div>
            <button className="btn btn-primary" onClick={fetchLogs}><RefreshCw size={13} /> Retry</button>
          </div>
        ) : filtered.length === 0 ? (
          <div className="empty-state" style={{ padding: 48 }}>
            <CheckCircle size={28} color="var(--green)" />
            <span>No log entries match current filters</span>
          </div>
        ) : (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Timestamp</th>
                    <th>Event Type</th>
                    <th>Reference</th>
                    <th><Hash size={11} style={{ display: 'inline', marginRight: 4 }} />Hash</th>
                    <th>Integrity</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {paginated.map(log => (
                    <LogRow
                      key={log.id}
                      log={log}
                      expanded={expanded === log.id}
                      onToggle={() => setExpanded(e => e === log.id ? null : log.id)}
                    />
                  ))}
                </tbody>
              </table>
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="pagination">
                <span>Page {page} of {totalPages}</span>
                <button className="page-btn" disabled={page === 1} onClick={() => setPage(1)}>«</button>
                <button className="page-btn" disabled={page === 1} onClick={() => setPage(p => p - 1)}>‹</button>
                {Array.from({ length: Math.min(totalPages, 5) }, (_, i) => {
                  const p = Math.max(1, Math.min(totalPages - 4, page - 2)) + i;
                  return p <= totalPages ? (
                    <button key={p} className={`page-btn ${p === page ? 'active' : ''}`} onClick={() => setPage(p)}>{p}</button>
                  ) : null;
                })}
                <button className="page-btn" disabled={page === totalPages} onClick={() => setPage(p => p + 1)}>›</button>
                <button className="page-btn" disabled={page === totalPages} onClick={() => setPage(totalPages)}>»</button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
