import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Truck, Package, MapPin,
  RefreshCw, FileText, ArrowRightCircle, AlertCircle, CheckCircle
} from 'lucide-react';
import { shipmentAPI } from '../services/api';
import './pages.css';

const STATUS_META = {
  ordered:      { label: 'Ordered',    chip: 'chip-info' },
  dispatched:   { label: 'Dispatched', chip: 'chip-medium' },
  in_transit:   { label: 'In Transit', chip: 'chip-info' },
  at_warehouse: { label: 'At Warehouse', chip: 'chip-medium' },
  delivered:    { label: 'Delivered',  chip: 'chip-resolved' },
  delayed:      { label: 'Delayed',    chip: 'chip-critical' },
};

const fmtMoney = (val) => (val == null ? '—' : `₹${Number(val).toLocaleString()}`);

function StatusChip({ status }) {
  const meta = STATUS_META[status] || { label: status || 'Unknown', chip: 'chip-info' };
  return <span className={`chip ${meta.chip}`}>{meta.label}</span>;
}

function ShipmentTimeline({ timeline }) {
  if (!Array.isArray(timeline) || timeline.length === 0) {
    return <div className="empty-state">No timeline available for this shipment.</div>;
  }

  return (
    <div className="timeline-panel">
      <div className="card-title mb-3">Shipment Timeline</div>
      <div className="timeline-list">
        {timeline.map((t, idx) => (
          <div key={idx} className="tl-item">
            <div className="tl-dot tl-dot-medium" />
            <div className="tl-content">
              <div className="tl-header">
                <div className="tl-title">{t.stage}</div>
              </div>
              <div className="tl-meta" style={{ fontFamily: 'var(--font-mono)', fontSize: '0.68rem', color: 'var(--text-muted)' }}>
                {t.time || '—'}
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ShipmentDetail({ shipment, onViewMap }) {
  if (!shipment) {
    return (
      <div className="card" style={{ padding: 20 }}>
        <div className="card-title">Select a shipment to view details</div>
        <div className="empty-state">Click any row in the table to view full shipment details, timeline and map.</div>
      </div>
    );
  }

  const balance = shipment.amount != null && shipment.paid != null ? shipment.amount - shipment.paid : null;

  return (
    <div className="card" style={{ padding: 20 }}>
      <div className="flex items-center justify-between mb-4">
        <div>
          <div className="card-title">Shipment Details</div>
          <div className="card-sub">ID: {shipment.id || shipment.shipment_id}</div>
        </div>
        <button className="btn btn-ghost" onClick={() => onViewMap && onViewMap(shipment)}>
          <MapPin size={14} /> View on Map
        </button>
      </div>

      <div className="detail-grid" style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
        <div className="detail-row">
          <div className="detail-key">Supplier</div>
          <div className="detail-val">{shipment.supplier}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Factory</div>
          <div className="detail-val">{shipment.destination}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Driver</div>
          <div className="detail-val">{shipment.driver}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Contact</div>
          <div className="detail-val">{shipment.contact}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Vehicle</div>
          <div className="detail-val">{shipment.vehicle}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Expected Delivery</div>
          <div className="detail-val">{shipment.eta || shipment.expected_delivery || '—'}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Payment Status</div>
          <div className="detail-val"><StatusChip status={shipment.payment_status} /></div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Paid / Total</div>
          <div className="detail-val">{fmtMoney(shipment.paid)} / {fmtMoney(shipment.amount)}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Balance Pending</div>
          <div className="detail-val">{balance != null ? fmtMoney(balance) : '—'}</div>
        </div>
        <div className="detail-row">
          <div className="detail-key">Current Stage</div>
          <div className="detail-val"><StatusChip status={shipment.status} /></div>
        </div>
      </div>

      <ShipmentTimeline timeline={shipment.timeline} />

      <div style={{ marginTop: 16, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        <button className="btn btn-primary" onClick={() => onViewMap && onViewMap(shipment)}>
          <MapPin size={14} /> Highlight on Map
        </button>
        <button className="btn btn-ghost" onClick={() => navigator.clipboard.writeText(JSON.stringify(shipment, null, 2))}>
          <FileText size={14} /> Copy JSON
        </button>
      </div>
    </div>
  );
}

export default function ShipmentTracker() {
  const navigate = useNavigate();
  const [shipments, setShipments] = useState([]);
  const [selected, setSelected] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const detailRef = useRef(null);

  const fetchShipments = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await shipmentAPI.getAll();
      setShipments(Array.isArray(data) ? data : (data.shipments || []));
    } catch (err) {
      setError(err.message || 'Failed to load shipments');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchShipments();
  }, [fetchShipments]);

  const metrics = useMemo(() => {
    const total = shipments.length;

    const counts = shipments.reduce((acc, s) => {
      const status = (s.status || '').toString().toLowerCase();
      const isDelivered = status === 'delivered';
      const isDelayed = status.includes('delay') || status === 'delayed';
      const isInTransit = !isDelivered && !isDelayed;

      acc.delivered += isDelivered ? 1 : 0;
      acc.delayed += isDelayed ? 1 : 0;
      acc.inTransit += isInTransit ? 1 : 0;
      acc.active += isDelivered ? 0 : 1;

      return acc;
    }, { total: 0, active: 0, inTransit: 0, delayed: 0, delivered: 0 });

    return {
      total,
      active: counts.active,
      inTransit: counts.inTransit,
      delayed: counts.delayed,
      delivered: counts.delivered,
    };
  }, [shipments]);

  const handleViewMap = (shipment) => {
    navigate('/map', { state: { highlightShipmentId: shipment.id || shipment.shipment_id } });
  };

  useEffect(() => {
    if (selected && detailRef.current) {
      detailRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
  }, [selected]);

  return (
    <div className="page">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="section-title">SHIPMENT TRACKER</h1>
          <div className="section-subtitle">End-to-end shipment tracking · Live status and timelines</div>
        </div>
        <button className="btn btn-ghost" onClick={fetchShipments}>
          <RefreshCw size={14} /> Refresh
        </button>
      </div>

      <div className="grid-4 mb-6">
        <div className="metric-card">
          <div className="mc-top">
            <span className="mc-label">Active Shipments</span>
            <div className="mc-icon mc-icon-cyan"><Truck size={16} /></div>
          </div>
          <div className="mc-value mc-value-cyan">{loading ? '…' : metrics.active}</div>
          <div className="mc-sub">In transit or dispatched</div>
        </div>
        <div className="metric-card">
          <div className="mc-top">
            <span className="mc-label">In Transit</span>
            <div className="mc-icon mc-icon-amber"><Package size={16} /></div>
          </div>
          <div className="mc-value mc-value-amber">{loading ? '…' : metrics.inTransit}</div>
          <div className="mc-sub">Moving between nodes</div>
        </div>
        <div className="metric-card">
          <div className="mc-top">
            <span className="mc-label">Delayed</span>
            <div className="mc-icon mc-icon-red"><AlertCircle size={16} /></div>
          </div>
          <div className="mc-value mc-value-red">{loading ? '…' : metrics.delayed}</div>
          <div className="mc-sub">Needs attention</div>
        </div>
        <div className="metric-card">
          <div className="mc-top">
            <span className="mc-label">Delivered</span>
            <div className="mc-icon mc-icon-green"><CheckCircle size={16} /></div>
          </div>
          <div className="mc-value mc-value-green">{loading ? '…' : metrics.delivered}</div>
          <div className="mc-sub">Completed shipments</div>
        </div>
      </div>

      {loading ? (
        <div className="loading-screen">
          <div className="spinner" />
          <div className="loading-text">LOADING SHIPMENT DATA...</div>
        </div>
      ) : error ? (
        <div className="error-box">
          <div className="error-title">FAILED TO LOAD SHIPMENTS</div>
          <div className="error-msg">{error}</div>
          <button className="btn btn-primary" onClick={fetchShipments}>
            <RefreshCw size={14} /> Retry
          </button>
        </div>
      ) : (
        <div className="grid-8-4" style={{ gap: 16 }}>
          <div className="card" style={{ padding: 20 }}>
            <div className="card-title mb-4">SHIPMENTS</div>
            {shipments.length === 0 ? (
              <div className="empty-state">No shipments were returned from the API.</div>
            ) : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Shipment</th>
                    <th>Supplier</th>
                    <th>Destination</th>
                    <th>Status</th>
                    <th>ETA</th>
                    <th>Payment</th>
                    <th>Driver</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {shipments.map((s) => (
                    <tr key={s.id || s.shipment_id} onClick={() => setSelected(s)} style={{ cursor: 'pointer' }}>
                      <td>{s.id || s.shipment_id}</td>
                      <td>{s.supplier}</td>
                      <td>{s.destination}</td>
                      <td><StatusChip status={s.status} /></td>
                      <td>{s.eta || s.expected_delivery || '—'}</td>
                      <td>{fmtMoney(s.paid)} / {fmtMoney(s.amount)}</td>
                      <td>{s.driver}</td>
                      <td>
                        <button className="btn btn-ghost" onClick={(e) => { e.stopPropagation(); setSelected(s); }}>
                          <ArrowRightCircle size={16} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div ref={detailRef}>
            <ShipmentDetail shipment={selected} onViewMap={handleViewMap} />
          </div>
        </div>
      )}
    </div>
  );
}
