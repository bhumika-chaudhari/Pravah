import React, { useState, useEffect, useCallback } from 'react';
import {
  Activity, Clock, AlertTriangle, CheckCircle,
  Filter, RefreshCw, Package, Wifi
} from 'lucide-react';
import {
  BarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer
} from 'recharts';
import { anomalyAPI } from '../services/api';
import './pages.css';

const SEV_ORDER = ['critical', 'high', 'medium', 'low'];

const TYPE_ICONS = {
  delay:       <Clock size={14} />,
  quality:     <AlertTriangle size={14} />,
  inventory:   <Package size={14} />,
  reliability: <Wifi size={14} />,
  default:     <Activity size={14} />,
};

function getTypeIcon(type) {
  return TYPE_ICONS[type?.toLowerCase()] || TYPE_ICONS.default;
}

function SeveritySummary({ anomalies }) {
  const counts = SEV_ORDER.reduce((acc, s) => {
    acc[s] = anomalies.filter(a => a.severity === s).length;
    return acc;
  }, {});

  const colors = { critical: 'var(--red)', high: 'var(--amber)', medium: 'var(--cyan)', low: 'var(--green)' };

  return (
    <div className="grid-4">
      {SEV_ORDER.map(s => (
        <div key={s} className="metric-card">
          <div className="mc-top">
            <span className="mc-label">{s}</span>
            <div className={`mc-icon mc-icon-${s === 'critical' ? 'red' : s === 'high' ? 'amber' : s === 'medium' ? 'cyan' : 'green'}`}>
              {getTypeIcon(s === 'critical' ? 'quality' : s === 'high' ? 'delay' : 'default')}
            </div>
          </div>
          <div className="mc-value" style={{ color: colors[s], fontSize: '1.8rem' }}>{counts[s]}</div>
          <div className="mc-sub">{anomalies.filter(a=>a.severity===s&&a.status==='active').length} active</div>
        </div>
      ))}
    </div>
  );
}

function TimelineItem({ anomaly }) {
  const sev = anomaly.severity || 'medium';
  const ts = anomaly.timestamp ? new Date(anomaly.timestamp).toLocaleString('en-IN', {
    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
  }) : '—';

  return (
    <div className="tl-item">
      <div className={`tl-dot tl-dot-${sev}`}>
        {getTypeIcon(anomaly.type)}
      </div>
      <div className="tl-content">
        <div className="tl-header">
          <div className="tl-title">
            {anomaly.component}
            {anomaly.supplier && anomaly.supplier !== 'Internal' && (
              <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: '0.78rem' }}> · {anomaly.supplier}</span>
            )}
          </div>
          <div className="tl-tags">
            <span className={`chip chip-${sev}`}>{sev}</span>
            <span className={`chip chip-${anomaly.status === 'resolved' ? 'resolved' : anomaly.status === 'active' ? 'active' : 'pending'}`}>
              {anomaly.status}
            </span>
          </div>
        </div>
        <div className="tl-desc">{anomaly.description}</div>
        {anomaly.impact && (
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 3 }}>
            Impact: {anomaly.impact}
          </div>
        )}
        <div className="tl-meta">
          <span>{ts}</span>
          {anomaly.type && <span>TYPE: {anomaly.type.toUpperCase()}</span>}
        </div>
        {anomaly.resolution && (
          <div className="tl-resolution">
            <CheckCircle size={11} style={{ display: 'inline', marginRight: 5 }} />
            {anomaly.resolution.action}
            {anomaly.resolution.timestamp && (
              <span style={{ marginLeft: 8, opacity: 0.7 }}>
                · {new Date(anomaly.resolution.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="chart-tooltip-row" style={{ color: p.color }}>
          <span>{p.name}</span><span>{p.value}</span>
        </div>
      ))}
    </div>
  );
};

export default function AnomalyTimeline() {
  const [anomalies, setAnomalies] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [severityFilter, setSeverityFilter] = useState('all');
  const [statusFilter, setStatusFilter] = useState('all');
  const [timeRange, setTimeRange] = useState('7d');

  const fetchAnomalies = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const params = {};
      if (severityFilter !== 'all') params.severity = severityFilter;
      const data = await anomalyAPI.getTimeline(params);
      setAnomalies(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load anomaly timeline');
    } finally {
      setLoading(false);
    }
  }, [severityFilter]);

  useEffect(() => { fetchAnomalies(); }, [fetchAnomalies]);

  // Build chart data from actual anomalies
  const chartData = React.useMemo(() => {
    if (!anomalies.length) return [];
    const buckets = {};
    anomalies.forEach(a => {
      if (!a.timestamp) return;
      const d = new Date(a.timestamp);
      const key = d.toLocaleDateString('en-IN', { month: 'short', day: '2-digit' });
      if (!buckets[key]) buckets[key] = { date: key, critical: 0, high: 0, medium: 0, resolved: 0 };
      buckets[key][a.severity] = (buckets[key][a.severity] || 0) + 1;
      if (a.status === 'resolved') buckets[key].resolved++;
    });
    return Object.values(buckets).slice(-10);
  }, [anomalies]);

  const filtered = anomalies.filter(a => {
    if (severityFilter !== 'all' && a.severity !== severityFilter) return false;
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    return true;
  });

  const sorted = [...filtered].sort((a, b) => {
    const sa = SEV_ORDER.indexOf(a.severity);
    const sb = SEV_ORDER.indexOf(b.severity);
    if (sa !== sb) return sa - sb;
    return new Date(b.timestamp) - new Date(a.timestamp);
  });

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">ANOMALY DETECTION FEED</h1>
          <div className="section-subtitle">ML-POWERED PATTERN RECOGNITION · REAL-TIME MONITORING</div>
        </div>
        <button className="btn btn-ghost" onClick={fetchAnomalies}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* ── Summary ── */}
      {!loading && !error && (
        <div className="mb-6">
          <SeveritySummary anomalies={anomalies} />
        </div>
      )}

      {/* ── Chart ── */}
      {!loading && !error && chartData.length > 0 && (
        <div className="grid-8-4 mb-6">
          <div className="card" style={{ padding: 20 }}>
            <div className="card-title mb-4">ANOMALY TRENDS BY SEVERITY</div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={chartData} margin={{ top: 0, right: 5, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,200,255,0.05)" />
                <XAxis dataKey="date" tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'IBM Plex Mono' }} />
                <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'IBM Plex Mono' }} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="critical" stackId="a" fill="#ff3d57" name="Critical" />
                <Bar dataKey="high"     stackId="a" fill="#ffb020" name="High" />
                <Bar dataKey="medium"   stackId="a" fill="#00c8ff" name="Medium" />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <div className="card-title mb-4">QUICK STATS</div>
            <div className="flex flex-col gap-3">
              {[
                { label: 'Total Detected', val: anomalies.length, color: 'cyan' },
                { label: 'Active',         val: anomalies.filter(a=>a.status==='active').length,     color: 'red' },
                { label: 'Resolved',       val: anomalies.filter(a=>a.status==='resolved').length,   color: 'green' },
                { label: 'Investigating',  val: anomalies.filter(a=>a.status==='investigating').length, color: 'amber' },
              ].map(item => (
                <div key={item.label} className="flex items-center justify-between" style={{
                  padding: '8px 12px',
                  background: 'var(--bg-surface)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-muted)' }}>{item.label}</span>
                  <span style={{ fontFamily: 'var(--font-display)', fontSize: '1.1rem', fontWeight: 700, color: `var(--${item.color})` }}>
                    {item.val}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── Filters ── */}
      <div className="card mb-6" style={{ padding: '14px 20px' }}>
        <div className="filter-bar">
          <Filter size={14} color="var(--text-muted)" />
          <span className="filter-label">FILTER:</span>

          <select
            className="select"
            value={severityFilter}
            onChange={e => setSeverityFilter(e.target.value)}
          >
            <option value="all">All Severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>

          <select
            className="select"
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
          >
            <option value="all">All Statuses</option>
            <option value="active">Active</option>
            <option value="investigating">Investigating</option>
            <option value="resolved">Resolved</option>
          </select>

          <select
            className="select"
            value={timeRange}
            onChange={e => setTimeRange(e.target.value)}
          >
            <option value="1h">Last Hour</option>
            <option value="24h">Last 24 Hours</option>
            <option value="7d">Last 7 Days</option>
            <option value="30d">Last 30 Days</option>
          </select>

          <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
            {sorted.length} results
          </span>
        </div>
      </div>

      {/* ── Content ── */}
      {loading ? (
        <div className="loading-screen">
          <div className="spinner" />
          <div className="loading-text">SCANNING ANOMALY DATABASE...</div>
        </div>
      ) : error ? (
        <div className="error-box">
          <AlertTriangle size={28} color="var(--red)" />
          <div className="error-title">FETCH FAILED</div>
          <div className="error-msg">{error}</div>
          <button className="btn btn-primary" onClick={fetchAnomalies} style={{ marginTop: 8 }}>
            <RefreshCw size={13} /> Retry
          </button>
        </div>
      ) : sorted.length === 0 ? (
        <div className="empty-state" style={{ padding: 64 }}>
          <CheckCircle size={32} color="var(--green)" />
          <span>No anomalies match current filters</span>
        </div>
      ) : (
        <div className="card" style={{ padding: 20 }}>
          <div className="card-title mb-4">
            ANOMALY TIMELINE
            <span style={{ marginLeft: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: '0.7rem', fontWeight: 400 }}>
              ({sorted.length} entries, sorted by severity)
            </span>
          </div>
          <div className="timeline-list">
            {sorted.map(a => (
              <TimelineItem key={a.id} anomaly={a} />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
