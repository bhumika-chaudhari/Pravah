import React, { useState, useEffect, useCallback } from 'react';
import {
  Cpu, Clock,
  CheckCircle, XCircle, AlertTriangle, RefreshCw,
  ChevronRight, Zap, X
} from 'lucide-react';
import {
  PieChart, Pie, Cell, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip
} from 'recharts';
import { decisionAPI } from '../services/api';
import './pages.css';

const formatINR = (v) => {
  if (!v && v !== 0) return '—';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(v);
};

const STATUS_COLORS = {
  auto_approved:    'resolved',
  pending_approval: 'pending',
  rejected:         'critical',
  executed:         'info',
};

function DecisionModal({ decision, onClose, onApprove, onReject }) {
  if (!decision) return null;

  const recs = Array.isArray(decision.recommendations) ? decision.recommendations : [];

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-header">
          <div>
            <div className="modal-title">DECISION #{decision.id} · {decision.component}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 3 }}>
              Issue: {decision.issue}
            </div>
          </div>
          <button className="btn btn-ghost" onClick={onClose} style={{ padding: '6px' }}>
            <X size={16} />
          </button>
        </div>

        <div className="modal-body">
          {/* Issue Context */}
          <div style={{ padding: '12px 16px', background: 'rgba(255,176,32,0.06)', border: '1px solid rgba(255,176,32,0.2)', borderRadius: 'var(--radius-md)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--amber)', marginBottom: 4 }}>DETECTED ANOMALY</div>
            <div style={{ color: 'var(--text-primary)', fontSize: '0.85rem' }}>{decision.issue}</div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 4 }}>
              Component: {decision.component} · Timestamp: {decision.timestamp ? new Date(decision.timestamp).toLocaleString('en-IN') : '—'}
            </div>
          </div>

          {/* Recommendations */}
          <div>
            <div className="card-title mb-3">AI RECOMMENDATIONS</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {recs.length === 0 ? (
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-muted)', padding: 16 }}>
                  {typeof recs[0] === 'string' ? decision.recommendations.join(', ') : 'No detailed recommendations available.'}
                </div>
              ) : (
                recs.map((rec, i) => {
                  const isStr = typeof rec === 'string';
                  const title = isStr ? rec : (rec.description || rec.action || `Option ${i+1}`);
                  const isRec = !isStr && rec.recommended;
                  return (
                    <div key={i} className={`rec-card ${isRec ? 'recommended' : ''}`}>
                      <div className="rec-header">
                        <div className="rec-title">{title}</div>
                        {isRec && <span className="chip chip-medium">★ RECOMMENDED</span>}
                      </div>
                      {!isStr && (
                        <div className="rec-metrics">
                          <div className="rec-metric">
                            <span className="rec-metric-label">Cost</span>
                            <span className="rec-metric-val" style={{ color: 'var(--red)' }}>
                              {rec.cost != null ? formatINR(rec.cost) : '—'}
                            </span>
                          </div>
                          <div className="rec-metric">
                            <span className="rec-metric-label">Time Saved</span>
                            <span className="rec-metric-val" style={{ color: 'var(--green)' }}>
                              {rec.timeSaved != null ? `${rec.timeSaved}d` : '—'}
                            </span>
                          </div>
                          <div className="rec-metric">
                            <span className="rec-metric-label">Risk</span>
                            <span className="rec-metric-val" style={{ color: 'var(--amber)' }}>
                              {rec.risk != null ? `${(rec.risk * 100).toFixed(0)}%` : '—'}
                            </span>
                          </div>
                          <div className="rec-metric">
                            <span className="rec-metric-label">Confidence</span>
                            <span className="rec-metric-val" style={{ color: 'var(--cyan)' }}>
                              {rec.score != null ? `${(rec.score * 100).toFixed(0)}%` : '—'}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>
          </div>
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Close</button>
          {decision.status === 'pending_approval' && (
            <>
              <button className="btn btn-danger" onClick={() => { onReject(decision.id); onClose(); }}>
                <XCircle size={13} /> Reject
              </button>
              <button className="btn btn-success" onClick={() => { onApprove(decision.id); onClose(); }}>
                <CheckCircle size={13} /> Approve
              </button>
            </>
          )}
        </div>
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
        <div key={p.dataKey} className="chart-tooltip-row" style={{ color: p.color || 'var(--cyan)' }}>
          <span>{p.name}</span><span>{p.value}</span>
        </div>
      ))}
    </div>
  );
};

export default function DecisionEngine() {
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null);

  const fetchDecisions = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await decisionAPI.getPending();
      setDecisions(Array.isArray(data) ? data : []);
    } catch (err) {
      setError(err.message || 'Failed to load decisions');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDecisions(); }, [fetchDecisions]);

  const handleApprove = useCallback(async (id) => {
    try {
      await decisionAPI.update(id, 'approve');
      setDecisions(prev => prev.map(d => d.id === id ? { ...d, status: 'executed' } : d));
    } catch {
      setDecisions(prev => prev.map(d => d.id === id ? { ...d, status: 'executed' } : d));
    }
  }, []);

  const handleReject = useCallback(async (id) => {
    try {
      await decisionAPI.update(id, 'reject');
      setDecisions(prev => prev.map(d => d.id === id ? { ...d, status: 'rejected' } : d));
    } catch {
      setDecisions(prev => prev.map(d => d.id === id ? { ...d, status: 'rejected' } : d));
    }
  }, []);

  const stats = {
    total:    decisions.length,
    auto:     decisions.filter(d => d.status === 'auto_approved').length,
    pending:  decisions.filter(d => d.status === 'pending_approval').length,
    executed: decisions.filter(d => d.status === 'executed').length,
  };

  const statusPie = [
    { name: 'Auto Approved', value: stats.auto,     color: '#00ff88' },
    { name: 'Pending',       value: stats.pending,  color: '#ffb020' },
    { name: 'Executed',      value: stats.executed, color: '#00c8ff' },
    { name: 'Other',         value: Math.max(0, stats.total - stats.auto - stats.pending - stats.executed), color: '#3d6080' },
  ].filter(d => d.value > 0);

  const getRecs = (d) => {
    const recs = Array.isArray(d.recommendations) ? d.recommendations : [];
    const first = recs[0];
    if (!first) return { title: '—', cost: null };
    if (typeof first === 'string') return { title: first, cost: null };
    return { title: first.description || first.action || '—', cost: first.cost };
  };

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">AI DECISION ENGINE</h1>
          <div className="section-subtitle">AUTONOMOUS RESPONSE SYSTEM · COST-OPTIMIZED RECOMMENDATIONS</div>
        </div>
        <div className="flex items-center gap-3">
          <button className="btn btn-primary" onClick={fetchDecisions}>
            <Cpu size={13} /> Run Analysis
          </button>
          <button className="btn btn-ghost" onClick={fetchDecisions}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* ── KPI Row ── */}
      <div className="grid-4 mb-6">
        {[
          { label: 'Total Decisions', val: stats.total,    icon: Cpu,          color: 'cyan' },
          { label: 'Auto Approved',   val: stats.auto,     icon: CheckCircle,  color: 'green' },
          { label: 'Pending Approval',val: stats.pending,  icon: Clock,        color: 'amber' },
          { label: 'Executed',        val: stats.executed, icon: Zap,          color: 'purple' },
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

      {/* ── Charts ── */}
      {!loading && !error && decisions.length > 0 && (
        <div className="grid-8-4 mb-6">
          <div className="card" style={{ padding: 20 }}>
            <div className="card-title mb-4">DECISION ACTION DISTRIBUTION</div>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart
                data={Object.entries(
                  decisions.reduce((acc, d) => {
                    const recs = Array.isArray(d.recommendations) ? d.recommendations : [];
                    const first = recs[0];
                    const key = (typeof first === 'string' ? first : first?.action) || 'unknown';
                    const label = key.replace(/_/g, ' ').slice(0, 16);
                    acc[label] = (acc[label] || 0) + 1;
                    return acc;
                  }, {})
                ).map(([name, count]) => ({ name, count }))}
                margin={{ top: 0, right: 5, bottom: 30, left: -20 }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,200,255,0.05)" />
                <XAxis dataKey="name" tick={{ fill: 'var(--text-muted)', fontSize: 9, fontFamily: 'IBM Plex Mono' }} angle={-20} textAnchor="end" />
                <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'IBM Plex Mono' }} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="count" fill="var(--cyan)" name="Count" radius={[3,3,0,0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>

          <div className="card" style={{ padding: 20 }}>
            <div className="card-title mb-4">APPROVAL STATUS</div>
            {statusPie.length > 0 ? (
              <>
                <ResponsiveContainer width="100%" height={160}>
                  <PieChart>
                    <Pie data={statusPie} cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={3} dataKey="value">
                      {statusPie.map((entry, i) => <Cell key={i} fill={entry.color} />)}
                    </Pie>
                    <Tooltip formatter={(v, n) => [v, n]} contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-mid)', borderRadius: 8, fontFamily: 'IBM Plex Mono', fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {statusPie.map(s => (
                    <div key={s.name} style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: '0.68rem' }}>
                      <div style={{ width: 10, height: 10, borderRadius: '50%', background: s.color, flexShrink: 0 }} />
                      <span style={{ color: 'var(--text-secondary)', flex: 1 }}>{s.name}</span>
                      <span style={{ color: s.color }}>{s.value}</span>
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state">No data</div>
            )}
          </div>
        </div>
      )}

      {/* ── Table ── */}
      <div className="card" style={{ padding: 20 }}>
        <div className="card-title mb-4">DECISION QUEUE</div>

        {loading ? (
          <div className="loading-screen"><div className="spinner" /><div className="loading-text">LOADING DECISIONS...</div></div>
        ) : error ? (
          <div className="error-box">
            <AlertTriangle size={24} color="var(--red)" />
            <div className="error-title">FETCH FAILED</div>
            <div className="error-msg">{error}</div>
            <button className="btn btn-primary" onClick={fetchDecisions}><RefreshCw size={13} /> Retry</button>
          </div>
        ) : decisions.length === 0 ? (
          <div className="empty-state" style={{ padding: 48 }}>
            <CheckCircle size={28} color="var(--green)" />
            <span>No decisions in queue</span>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Component</th>
                  <th>Issue</th>
                  <th>Recommended Action</th>
                  <th>Cost</th>
                  <th>Status</th>
                  <th>Timestamp</th>
                  <th style={{ textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {decisions.map(d => {
                  const { title: recTitle, cost: recCost } = getRecs(d);
                  const ts = d.timestamp ? new Date(d.timestamp).toLocaleString('en-IN', {
                    day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit'
                  }) : '—';
                  return (
                    <tr key={d.id}>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>#{d.id}</td>
                      <td>
                        <div style={{ fontFamily: 'var(--font-display)', fontWeight: 600, letterSpacing: '0.03em' }}>{d.component}</div>
                        {d.anomaly_id && <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.62rem', color: 'var(--text-muted)' }}>Anomaly #{d.anomaly_id}</div>}
                      </td>
                      <td style={{ maxWidth: 200, fontSize: '0.8rem', color: 'var(--text-secondary)' }}>{d.issue}</td>
                      <td style={{ fontSize: '0.8rem' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                          <Zap size={11} color="var(--amber)" />
                          {recTitle}
                        </div>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: recCost ? 'var(--red)' : 'var(--text-muted)' }}>
                        {recCost != null ? formatINR(recCost) : '—'}
                      </td>
                      <td>
                        <span className={`chip chip-${STATUS_COLORS[d.status] || 'medium'}`}>
                          {d.status?.replace(/_/g, ' ')}
                        </span>
                      </td>
                      <td style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>{ts}</td>
                      <td>
                        <div className="flex items-center gap-2 justify-end">
                          <button className="btn btn-ghost" style={{ padding: '5px 8px' }} onClick={() => setSelected(d)}>
                            Details <ChevronRight size={11} />
                          </button>
                          {d.status === 'pending_approval' && (
                            <>
                              <button className="btn btn-success" style={{ padding: '5px 10px' }} onClick={() => handleApprove(d.id)}>
                                <CheckCircle size={11} /> Approve
                              </button>
                              <button className="btn btn-danger" style={{ padding: '5px 10px' }} onClick={() => handleReject(d.id)}>
                                <XCircle size={11} /> Reject
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ── Modal ── */}
      {selected && (
        <DecisionModal
          decision={selected}
          onClose={() => setSelected(null)}
          onApprove={handleApprove}
          onReject={handleReject}
        />
      )}
    </div>
  );
}
