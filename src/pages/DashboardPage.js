import React, { useState, useEffect, useCallback } from 'react';
import {
  AlertTriangle, Clock, CheckCircle, TrendingUp, TrendingDown,
  Package, Truck, Activity, RefreshCw, Zap
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import { dashboardAPI } from '../services/api';

// ─── Helpers ─────────────────────────────────
const fmt = (v, suffix = '') => v != null ? `${v}${suffix}` : '—';
const sev = (s) => ['critical','high','medium','low'].includes(s) ? s : 'medium';

// ─── Sub-components ───────────────────────────
function MetricCard({ label, value, sub, icon: Icon, color = 'cyan', trend, trendUp }) {
  return (
    <div className="metric-card fade-in">
      <div className="mc-top">
        <span className="mc-label">{label}</span>
        <div className={`mc-icon mc-icon-${color}`}>
          <Icon size={16} />
        </div>
      </div>
      <div className={`mc-value mc-value-${color}`}>{value}</div>
      {sub && <div className="mc-sub">{sub}</div>}
      {trend != null && (
        <div className={`mc-trend ${trendUp ? 'trend-up' : 'trend-down'}`}>
          {trendUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
          <span>{trend}</span>
        </div>
      )}
    </div>
  );
}

function HealthBar({ label, value, color }) {
  const colors = { cyan: 'progress-cyan', green: 'progress-green', amber: 'progress-amber', red: 'progress-red' };
  return (
    <div className="health-bar-row">
      <div className="health-bar-header">
        <span className="health-label">{label}</span>
        <span className={`health-value health-${color}`}>{fmt(value, '%')}</span>
      </div>
      <div className="progress-bar">
        <div className={`progress-fill ${colors[color]}`} style={{ width: `${Math.min(value || 0, 100)}%` }} />
      </div>
    </div>
  );
}

function AlertRow({ alert }) {
  const ts = alert.timestamp ? new Date(alert.timestamp).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit' }) : '—';
  return (
    <div className={`alert-row alert-${sev(alert.severity)}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="alert-comp">{alert.component}</span>
        <div className="flex items-center gap-2">
          <span className={`chip chip-${sev(alert.severity)}`}>{alert.severity}</span>
          <span className="alert-ts">{ts}</span>
        </div>
      </div>
      <div className="alert-desc">{alert.description}</div>
      {alert.impact && <div className="alert-impact">{alert.impact}</div>}
    </div>
  );
}

function DecisionRow({ decision }) {
  const rec = Array.isArray(decision.recommendations) ? decision.recommendations[0] : null;
  const recText = typeof rec === 'string' ? rec : rec?.description || rec?.action || '—';
  return (
    <div className="decision-row">
      <div className="flex items-center justify-between gap-3">
        <span className="dec-comp">{decision.component}</span>
        <span className={`chip chip-${decision.status === 'auto_approved' ? 'resolved' : 'pending'}`}>
          {decision.status?.replace('_', ' ')}
        </span>
      </div>
      <div className="dec-issue">{decision.issue}</div>
      <div className="dec-rec">
        <Zap size={10} className="dec-rec-icon" />
        {recText}
      </div>
    </div>
  );
}

// ─── Custom Tooltip ───────────────────────────
const ChartTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="chart-tooltip-label">{label}</div>
      {payload.map(p => (
        <div key={p.dataKey} className="chart-tooltip-row" style={{ color: p.color }}>
          <span>{p.name}</span>
          <span>{p.value}</span>
        </div>
      ))}
    </div>
  );
};

// ─── Main Component ───────────────────────────
export default function DashboardPage() {
  const [metrics, setMetrics] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [decisions, setDecisions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState(new Date());

  // Simulated time-series for chart (since backend gives current snapshot only)
  const [chartData] = useState(() => {
    const hours = Array.from({ length: 12 }, (_, i) => {
      const h = (new Date().getHours() - 11 + i + 24) % 24;
      return {
        time: `${String(h).padStart(2,'0')}:00`,
        alerts: Math.floor(Math.random() * 8) + 1,
        resolved: Math.floor(Math.random() * 6),
      };
    });
    return hours;
  });

  const fetchAll = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const [m, a, d] = await Promise.all([
        dashboardAPI.getMetrics(),
        dashboardAPI.getAlerts(),
        dashboardAPI.getDecisions(),
      ]);
      setMetrics(m);
      setAlerts(Array.isArray(a) ? a : []);
      setDecisions(Array.isArray(d) ? d : []);
      setLastRefresh(new Date());
    } catch (err) {
      setError(err.message || 'Failed to connect to API. Ensure the FastAPI server is running on port 8000.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 30000); // auto-refresh every 30s
    return () => clearInterval(id);
  }, [fetchAll]);

  if (loading) return (
    <div className="loading-screen">
      <div className="spinner" />
      <div className="loading-text">FETCHING CONTROL TOWER DATA...</div>
    </div>
  );

  if (error) return (
    <div className="error-box">
      <AlertTriangle size={28} color="var(--red)" />
      <div className="error-title">CONNECTION FAILED</div>
      <div className="error-msg">{error}</div>
      <button className="btn btn-primary" onClick={fetchAll} style={{ marginTop: 8 }}>
        <RefreshCw size={14} /> Retry
      </button>
    </div>
  );

  const criticalAlerts = alerts.filter(a => a.severity === 'critical' || a.severity === 'high');
  const normalAlerts   = alerts.filter(a => a.severity !== 'critical' && a.severity !== 'high');

  return (
    <div className="page">
      {/* ── Page Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">SUPPLY CHAIN CONTROL TOWER</h1>
          <div className="section-subtitle">
            PUNE AUTONOMOUS SUPPLY CHAIN · REAL-TIME INTELLIGENCE
          </div>
        </div>
        <div className="flex items-center gap-3">
          <span className="refresh-ts">
            Updated {lastRefresh.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
          </span>
          <button className="btn btn-ghost" onClick={fetchAll}>
            <RefreshCw size={13} /> Refresh
          </button>
        </div>
      </div>

      {/* ── KPI Row ── */}
      <div className="grid-4 mb-6">
        <MetricCard
          label="Active Alerts"
          value={fmt(metrics?.total_alerts)}
          sub={`${alerts.filter(a=>a.severity==='critical').length} critical`}
          icon={AlertTriangle}
          color="red"
          trend="-12% vs yesterday"
          trendUp={false}
        />
        <MetricCard
          label="Active Anomalies"
          value={fmt(metrics?.active_anomalies)}
          sub="Under investigation"
          icon={Activity}
          color="amber"
          trend="+5 this hour"
          trendUp={true}
        />
        <MetricCard
          label="Resolved Today"
          value={fmt(metrics?.resolved_today)}
          sub="Auto + manual"
          icon={CheckCircle}
          color="green"
          trend="+25% efficiency"
          trendUp={true}
        />
        <MetricCard
          label="Avg Resolution"
          value={metrics?.avg_resolution_time || 'N/A'}
          sub="Mean time to resolve"
          icon={Clock}
          color="cyan"
          trend="-8% faster"
          trendUp={false}
        />
      </div>

      {/* ── Chart + System Health ── */}
      <div className="grid-8-4 mb-6">
        <div className="card" style={{ padding: 20 }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="card-title">ALERT ACTIVITY</div>
              <div className="card-sub">Last 12 hours · Auto-refreshes every 30s</div>
            </div>
            <span className="chip chip-medium">LIVE</span>
          </div>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={chartData} margin={{ top: 5, right: 5, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="alertGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#ff3d57" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#ff3d57" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="resolveGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%"  stopColor="#00ff88" stopOpacity={0.2} />
                  <stop offset="95%" stopColor="#00ff88" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,200,255,0.05)" />
              <XAxis dataKey="time" tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'IBM Plex Mono' }} />
              <YAxis tick={{ fill: 'var(--text-muted)', fontSize: 10, fontFamily: 'IBM Plex Mono' }} />
              <Tooltip content={<ChartTooltip />} />
              <Legend wrapperStyle={{ fontFamily: 'IBM Plex Mono', fontSize: 10, color: 'var(--text-muted)' }} />
              <Area type="monotone" dataKey="alerts"   stroke="#ff3d57" fill="url(#alertGrad)"   strokeWidth={2} name="New Alerts" />
              <Area type="monotone" dataKey="resolved" stroke="#00ff88" fill="url(#resolveGrad)" strokeWidth={2} name="Resolved" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        <div className="card" style={{ padding: 20 }}>
          <div className="card-title mb-4">SYSTEM HEALTH</div>
          <div className="flex flex-col gap-4">
            <HealthBar label="Inventory Levels"    value={metrics?.inventory_levels}    color="green" />
            <HealthBar label="Supplier Reliability" value={metrics?.supplier_reliability} color="cyan" />
            <HealthBar label="On-Time Delivery"    value={metrics?.on_time_delivery}    color="amber" />
          </div>

          <div className="health-stats-grid">
            <div className="health-stat">
              <Package size={18} color="var(--cyan)" />
              <span className="health-stat-val">{fmt(metrics?.inventory_levels, '%')}</span>
              <span className="health-stat-label">Inventory</span>
            </div>
            <div className="health-stat">
              <Truck size={18} color="var(--green)" />
              <span className="health-stat-val">{fmt(metrics?.on_time_delivery, '%')}</span>
              <span className="health-stat-label">On-Time</span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Alerts + Decisions ── */}
      <div className="grid-6-6">
        {/* Active Alerts */}
        <div className="card" style={{ padding: 20 }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="card-title">ACTIVE ALERTS</div>
              <div className="card-sub">{alerts.length} total · {criticalAlerts.length} high-priority</div>
            </div>
            <span className={`chip ${alerts.length > 0 ? 'chip-critical' : 'chip-resolved'}`}>
              {alerts.length} ACTIVE
            </span>
          </div>
          <div className="alerts-list">
            {alerts.length === 0 ? (
              <div className="empty-state">
                <CheckCircle size={24} color="var(--green)" />
                <span>No active alerts</span>
              </div>
            ) : (
              [...criticalAlerts, ...normalAlerts].slice(0, 8).map(alert => (
                <AlertRow key={alert.id} alert={alert} />
              ))
            )}
          </div>
        </div>

        {/* AI Decisions */}
        <div className="card" style={{ padding: 20 }}>
          <div className="flex items-center justify-between mb-4">
            <div>
              <div className="card-title">AI DECISIONS</div>
              <div className="card-sub">{decisions.length} in queue</div>
            </div>
            <span className={`chip ${decisions.length > 0 ? 'chip-pending' : 'chip-resolved'}`}>
              {decisions.length} PENDING
            </span>
          </div>
          <div className="decisions-list">
            {decisions.length === 0 ? (
              <div className="empty-state">
                <CheckCircle size={24} color="var(--green)" />
                <span>No pending decisions</span>
              </div>
            ) : (
              decisions.slice(0, 6).map(dec => (
                <DecisionRow key={dec.id} decision={dec} />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
