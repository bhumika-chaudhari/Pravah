import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  RefreshCw, AlertTriangle,
  Truck, Factory, Package, Info, X, Filter
} from 'lucide-react';
import { mapAPI } from '../services/api';
import './pages.css';

// ─── Map Projection (simple equirectangular for India/Asia region) ────────────
// Bounds: lat 6–36, lng 67–100
const MAP_W = 900;
const MAP_H = 520;
const LAT_MIN = 4, LAT_MAX = 38;
const LNG_MIN = 64, LNG_MAX = 102;

function project(lat, lng) {
  const x = ((lng - LNG_MIN) / (LNG_MAX - LNG_MIN)) * MAP_W;
  const y = ((LAT_MAX - lat) / (LAT_MAX - LAT_MIN)) * MAP_H;
  return { x, y };
}

const STATUS_COLOR = {
  active:  '#00ff88',
  online:  '#00ff88',
  warning: '#ffb020',
  delayed: '#ffb020',
  offline: '#ff3d57',
  disrupted: '#ff3d57',
};

function nodeColor(node) {
  const s = node.status?.toLowerCase() || 'active';
  return STATUS_COLOR[s] || '#00c8ff';
}

function nodeStroke(node) {
  return node.type === 'factory' ? '#ffb020' : '#00c8ff';
}

// ─── India SVG outline (simplified) ──────────────────────────────────────────
const INDIA_PATH = `M 310,20 L 330,18 L 360,22 L 390,30 L 420,25 L 450,35
  L 470,50 L 490,45 L 510,60 L 520,80 L 510,100 L 500,120 L 490,140
  L 480,160 L 470,180 L 460,200 L 450,220 L 440,240 L 430,260 L 420,280
  L 410,300 L 400,320 L 390,340 L 380,360 L 370,380 L 360,400 L 350,420
  L 340,440 L 330,460 L 320,480 L 310,490 L 300,480 L 290,460 L 280,440
  L 270,420 L 260,400 L 250,380 L 240,360 L 230,340 L 220,320 L 210,300
  L 200,280 L 190,260 L 185,240 L 190,220 L 195,200 L 200,180 L 210,160
  L 220,140 L 230,120 L 240,100 L 250,80 L 260,60 L 280,45 L 300,30 Z`;

// ─── Sub-components ───────────────────────────────────────────────────────────
function NodeTooltip({ node, pos }) {
  if (!node || !pos) return null;
  const metrics = node.metrics || {};
  return (
    <div style={{
      position: 'absolute',
      left: pos.x + 16,
      top: pos.y - 10,
      background: 'var(--bg-elevated)',
      border: '1px solid var(--border-mid)',
      borderRadius: 'var(--radius-md)',
      padding: '12px 16px',
      minWidth: 200,
      zIndex: 50,
      pointerEvents: 'none',
      boxShadow: '0 8px 24px rgba(0,0,0,0.7)',
    }}>
      <div style={{ fontFamily: 'var(--font-display)', fontSize: '0.9rem', fontWeight: 700, marginBottom: 6, letterSpacing: '0.04em' }}>
        {node.name}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        <span className={`chip ${node.type === 'factory' ? 'chip-high' : 'chip-medium'}`}>{node.type}</span>
        <span style={{ width: 8, height: 8, borderRadius: '50%', background: nodeColor(node), boxShadow: `0 0 6px ${nodeColor(node)}` }} />
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: nodeColor(node) }}>{node.status}</span>
      </div>
      {Object.entries(metrics).map(([k, v]) => (
        <div key={k} className="detail-row" style={{ padding: '4px 0', fontSize: '0.72rem' }}>
          <span className="detail-key">{k.replace(/_/g,' ')}</span>
          <span className="detail-val">{v}</span>
        </div>
      ))}
      {node.location && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.6rem', color: 'var(--text-muted)', marginTop: 6 }}>
          {node.location.lat?.toFixed(3)}° N, {node.location.lng?.toFixed(3)}° E
        </div>
      )}
    </div>
  );
}

function NodeCard({ node, selected, onClick }) {
  const color = nodeColor(node);
  const Icon  = node.type === 'factory' ? Factory : Package;
  const metrics = node.metrics || {};
  return (
    <div
      className={`map-node-card ${selected ? 'selected' : ''}`}
      onClick={() => onClick(node)}
    >
      <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, boxShadow: `0 0 6px ${color}`, flexShrink: 0 }} />
      <Icon size={14} color={node.type === 'factory' ? 'var(--amber)' : 'var(--cyan)'} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div className="node-info-name">{node.name}</div>
        <div className="node-info-meta">
          {node.type} · {node.status}
          {metrics.alerts > 0 && (
            <span style={{ color: 'var(--red)', marginLeft: 6 }}>⚠ {metrics.alerts} alert{metrics.alerts > 1 ? 's' : ''}</span>
          )}
        </div>
      </div>
      {selected && <ChevronActive />}
    </div>
  );
}

function ChevronActive() {
  return <div style={{ width: 6, height: 6, borderRight: '1px solid var(--cyan)', borderTop: '1px solid var(--cyan)', transform: 'rotate(45deg)', flexShrink: 0 }} />;
}

// ─── Main Component ───────────────────────────────────────────────────────────
export default function SupplyChainMap() {
  const [network,   setNetwork]   = useState({ nodes: [], shipments: [] });
  const [loading,   setLoading]   = useState(true);
  const [error,     setError]     = useState(null);
  const [hovered,   setHovered]   = useState(null);
  const [hoveredPos,setHoveredPos]= useState(null);
  const [selected,  setSelected]  = useState(null);
  const [typeFilter,setTypeFilter]= useState('all');
  const svgRef = useRef(null);

  const fetchNetwork = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await mapAPI.getNetwork();
      setNetwork({
        nodes:     Array.isArray(data.nodes)     ? data.nodes     : [],
        shipments: Array.isArray(data.shipments) ? data.shipments : [],
      });
    } catch (err) {
      setError(err.message || 'Failed to load network data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchNetwork(); }, [fetchNetwork]);

  const validNodes = network.nodes.filter(n =>
    n.location?.lat != null && n.location?.lng != null
  );

  const filteredNodes = validNodes.filter(n =>
    typeFilter === 'all' || n.type === typeFilter
  );

  // Build shipment lines from supplier→factory ID matching
  const shipmentLines = network.shipments.map(s => {
    const fromNode = validNodes.find(n => n.id === s.from || String(n.id) === String(s.from));
    const toNode   = validNodes.find(n => n.id === s.to   || String(n.id) === String(s.to));
    if (!fromNode || !toNode) return null;
    return { ...s, fromNode, toNode };
  }).filter(Boolean);

  const handleNodeMouseEnter = (e, node) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (rect) {
      setHoveredPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
    }
    setHovered(node);
  };

  const stats = {
    suppliers: validNodes.filter(n => n.type === 'supplier').length,
    factories: validNodes.filter(n => n.type === 'factory').length,
    shipments: network.shipments.length,
    alerts:    validNodes.reduce((acc, n) => acc + (n.metrics?.alerts || 0), 0),
  };

  return (
    <div className="page">
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">SUPPLY CHAIN NETWORK MAP</h1>
          <div className="section-subtitle">GEO-DISTRIBUTED NODE VISUALIZATION · LIVE SHIPMENT TRACKING</div>
        </div>
        <button className="btn btn-ghost" onClick={fetchNetwork}>
          <RefreshCw size={13} /> Refresh
        </button>
      </div>

      {/* ── KPI Strip ── */}
      <div className="grid-4 mb-6">
        {[
          { label: 'Suppliers',  val: stats.suppliers, color: 'cyan',  icon: Package },
          { label: 'Factories',  val: stats.factories, color: 'amber', icon: Factory },
          { label: 'Shipments',  val: stats.shipments, color: 'green', icon: Truck },
          { label: 'Alerts',     val: stats.alerts,    color: 'red',   icon: AlertTriangle },
        ].map(({ label, val, color, icon: Icon }) => (
          <div key={label} className="metric-card">
            <div className="mc-top">
              <span className="mc-label">{label}</span>
              <div className={`mc-icon mc-icon-${color}`}><Icon size={16} /></div>
            </div>
            <div className={`mc-value mc-value-${color}`}>{loading ? '…' : val}</div>
          </div>
        ))}
      </div>

      {loading ? (
        <div className="loading-screen">
          <div className="spinner" />
          <div className="loading-text">LOADING NETWORK TOPOLOGY...</div>
        </div>
      ) : error ? (
        <div className="error-box">
          <AlertTriangle size={28} color="var(--red)" />
          <div className="error-title">NETWORK FETCH FAILED</div>
          <div className="error-msg">{error}</div>
          <button className="btn btn-primary" onClick={fetchNetwork}><RefreshCw size={13} /> Retry</button>
        </div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 300px', gap: 16 }}>
          {/* ── SVG Map ── */}
          <div className="map-container" style={{ position: 'relative' }} ref={svgRef}>
            <svg
              viewBox={`0 0 ${MAP_W} ${MAP_H}`}
              className="map-svg"
              style={{ display: 'block', background: 'transparent' }}
            >
              {/* Grid */}
              <defs>
                <pattern id="mapGrid" width="50" height="50" patternUnits="userSpaceOnUse">
                  <path d="M 50 0 L 0 0 0 50" fill="none" stroke="rgba(0,200,255,0.04)" strokeWidth="1"/>
                </pattern>
                <radialGradient id="nodeGlow" cx="50%" cy="50%" r="50%">
                  <stop offset="0%" stopColor="#00c8ff" stopOpacity="0.3" />
                  <stop offset="100%" stopColor="#00c8ff" stopOpacity="0" />
                </radialGradient>
              </defs>
              <rect width={MAP_W} height={MAP_H} fill="url(#mapGrid)" />

              {/* India rough coastline */}
              <path
                d={INDIA_PATH}
                fill="rgba(0,200,255,0.025)"
                stroke="rgba(0,200,255,0.12)"
                strokeWidth="1"
                strokeLinejoin="round"
              />

              {/* Shipment lines */}
              {shipmentLines.map((s, i) => {
                const from = project(s.fromNode.location.lat, s.fromNode.location.lng);
                const to   = project(s.toNode.location.lat,   s.toNode.location.lng);
                const isDelayed = s.delay && s.delay !== '0 days';
                const color = isDelayed ? '#ffb020' : '#00c8ff';
                const mx = (from.x + to.x) / 2;
                const my = (from.y + to.y) / 2 - 30;
                return (
                  <g key={i}>
                    <path
                      d={`M ${from.x} ${from.y} Q ${mx} ${my} ${to.x} ${to.y}`}
                      fill="none"
                      stroke={color}
                      strokeWidth={isDelayed ? 1.5 : 1}
                      strokeOpacity={0.35}
                      strokeDasharray={isDelayed ? '6 4' : 'none'}
                    />
                    {/* Moving dot animation */}
                    <circle r="3" fill={color} opacity="0.8">
                      <animateMotion dur={`${3 + i * 0.7}s`} repeatCount="indefinite">
                        <mpath href={`#path-${i}`} />
                      </animateMotion>
                    </circle>
                    <path id={`path-${i}`} d={`M ${from.x} ${from.y} Q ${mx} ${my} ${to.x} ${to.y}`} fill="none" stroke="none" />
                  </g>
                );
              })}

              {/* Nodes */}
              {filteredNodes.map(node => {
                const { x, y } = project(node.location.lat, node.location.lng);
                const color    = nodeColor(node);
                const stroke   = nodeStroke(node);
                const hasAlert = (node.metrics?.alerts || 0) > 0;
                const r        = node.type === 'factory' ? 8 : 6;
                const isSelected = selected?.id === node.id;

                return (
                  <g
                    key={node.id}
                    transform={`translate(${x},${y})`}
                    style={{ cursor: 'pointer' }}
                    onMouseEnter={e => handleNodeMouseEnter(e, node)}
                    onMouseLeave={() => setHovered(null)}
                    onClick={() => setSelected(s => s?.id === node.id ? null : node)}
                  >
                    {/* Pulse ring */}
                    <circle r={r + 8} fill="none" stroke={color} strokeWidth="1" opacity="0">
                      <animate attributeName="opacity" values="0.4;0;0.4" dur="3s" repeatCount="indefinite" />
                      <animate attributeName="r" values={`${r+6};${r+14};${r+6}`} dur="3s" repeatCount="indefinite" />
                    </circle>
                    {/* Selected ring */}
                    {isSelected && (
                      <circle r={r + 10} fill="none" stroke={color} strokeWidth="2" opacity="0.6" />
                    )}
                    {/* Node body */}
                    <circle r={r} fill={color} stroke={stroke} strokeWidth="1.5" opacity="0.9" />
                    {/* Alert indicator */}
                    {hasAlert && (
                      <circle r="4" cx={r - 2} cy={-r + 2} fill="#ff3d57" stroke="var(--bg-deep)" strokeWidth="1.5">
                        <animate attributeName="opacity" values="1;0.4;1" dur="1.5s" repeatCount="indefinite" />
                      </circle>
                    )}
                    {/* Label */}
                    <text
                      y={r + 14}
                      textAnchor="middle"
                      fill="var(--text-secondary)"
                      fontSize="9"
                      fontFamily="IBM Plex Mono"
                      style={{ pointerEvents: 'none' }}
                    >
                      {node.name?.split(' ').slice(0, 2).join(' ')}
                    </text>
                  </g>
                );
              })}
            </svg>

            {/* Hover tooltip */}
            {hovered && hoveredPos && (
              <NodeTooltip node={hovered} pos={hoveredPos} />
            )}

            {/* Legend */}
            <div style={{ position: 'absolute', bottom: 12, left: 12, display: 'flex', flexDirection: 'column', gap: 5 }}>
              {[
                { color: '#00c8ff', label: 'Supplier' },
                { color: '#ffb020', label: 'Factory' },
                { color: '#00ff88', label: 'Online' },
                { color: '#ff3d57', label: 'Alert' },
                { color: '#ffb020', dash: true, label: 'Delayed Route' },
              ].map(({ color, label, dash }) => (
                <div key={label} className="map-legend-item">
                  {dash
                    ? <div style={{ width: 16, height: 2, background: `repeating-linear-gradient(90deg,${color} 0,${color} 4px,transparent 4px,transparent 8px)` }} />
                    : <div style={{ width: 10, height: 10, borderRadius: '50%', background: color, boxShadow: `0 0 5px ${color}` }} />
                  }
                  <span>{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* ── Right Panel ── */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
            {/* Filter */}
            <div className="card" style={{ padding: '12px 16px' }}>
              <div className="filter-bar" style={{ gap: 8 }}>
                <Filter size={12} color="var(--text-muted)" />
                <select className="select" value={typeFilter} onChange={e => setTypeFilter(e.target.value)} style={{ flex: 1 }}>
                  <option value="all">All Nodes ({validNodes.length})</option>
                  <option value="supplier">Suppliers ({validNodes.filter(n=>n.type==='supplier').length})</option>
                  <option value="factory">Factories ({validNodes.filter(n=>n.type==='factory').length})</option>
                </select>
              </div>
            </div>

            {/* Selected Detail */}
            {selected ? (
              <div className="detail-panel">
                <div className="flex items-center justify-between mb-3">
                  <div style={{ fontFamily: 'var(--font-display)', fontWeight: 700, letterSpacing: '0.04em' }}>{selected.name}</div>
                  <button className="btn btn-ghost" style={{ padding: '4px 6px' }} onClick={() => setSelected(null)}>
                    <X size={13} />
                  </button>
                </div>
                <div className="flex items-center gap-2 mb-3">
                  <span className={`chip ${selected.type === 'factory' ? 'chip-high' : 'chip-medium'}`}>{selected.type}</span>
                  <span style={{ width: 8, height: 8, borderRadius: '50%', background: nodeColor(selected), boxShadow: `0 0 5px ${nodeColor(selected)}` }} />
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: nodeColor(selected) }}>{selected.status}</span>
                </div>
                {Object.entries(selected.metrics || {}).map(([k, v]) => (
                  <div key={k} className="detail-row">
                    <span className="detail-key">{k.replace(/_/g,' ')}</span>
                    <span className="detail-val">{v}</span>
                  </div>
                ))}
                <div className="detail-row">
                  <span className="detail-key">Coordinates</span>
                  <span className="detail-val" style={{ fontSize: '0.68rem' }}>
                    {selected.location?.lat?.toFixed(3)}°N {selected.location?.lng?.toFixed(3)}°E
                  </span>
                </div>
              </div>
            ) : (
              <div style={{ padding: '12px 14px', background: 'var(--bg-surface)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 8 }}>
                <Info size={13} /> Click a node on the map to view details
              </div>
            )}

            {/* Node List */}
            <div className="card" style={{ padding: '14px 16px', flex: 1, overflow: 'hidden' }}>
              <div className="card-title mb-3">NODES ({filteredNodes.length})</div>
              <div className="map-node-list">
                {filteredNodes.length === 0 ? (
                  <div className="empty-state" style={{ padding: 20 }}>No nodes found</div>
                ) : (
                  filteredNodes.map(node => (
                    <NodeCard
                      key={node.id}
                      node={node}
                      selected={selected?.id === node.id}
                      onClick={setSelected}
                    />
                  ))
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
