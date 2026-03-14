import React, { useState, useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import { LayoutDashboard, Map, Activity, Cpu, Link2, ChevronRight, Radio, Menu, X, Truck } from 'lucide-react';
import DashboardPage from './pages/DashboardPage';
import SupplyChainMap from './pages/SupplyChainMap';
import AnomalyTimeline from './pages/AnomalyTimeline';
import DecisionEngine from './pages/DecisionEngine';
import BlockchainLog from './pages/BlockchainLog';
import ShipmentTracker from './pages/ShipmentTracker';
import './App.css';

const NAV_ITEMS = [
  { path: '/',           label: 'Control Tower',  icon: LayoutDashboard, subtitle: 'Overview' },
  { path: '/map',        label: 'Network Map',     icon: Map,             subtitle: 'Geo Nodes' },
  { path: '/shipments',  label: 'Shipment Tracker',icon: Truck,           subtitle: 'Live Tracking' },
  { path: '/timeline',   label: 'Anomaly Feed',    icon: Activity,        subtitle: 'Detection' },
  { path: '/decisions',  label: 'AI Engine',       icon: Cpu,             subtitle: 'Decisions' },
  { path: '/blockchain', label: 'Audit Chain',     icon: Link2,           subtitle: 'Ledger' },
];

function Sidebar({ open, onClose }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [time, setTime] = useState(new Date());

  useEffect(() => {
    const t = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(t);
  }, []);

  const handleNav = (path) => {
    navigate(path);
    onClose?.();
  };

  return (
    <>
      {open && (
        <div className="sidebar-overlay" onClick={onClose} />
      )}
      <aside className={`sidebar ${open ? 'sidebar-open' : ''}`}>
        {/* Logo */}
        <div className="sidebar-logo">
          <div className="logo-icon">
            <Radio size={18} />
          </div>
          <div className="logo-text">
            <span className="logo-title">Pravah</span>
          </div>
          <button className="sidebar-close" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        {/* System Clock */}
        <div className="sidebar-clock">
          <div className="clock-time">{time.toLocaleTimeString('en-US', { hour12: false })}</div>
          <div className="clock-date">{time.toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' })}</div>
          <div className="clock-status">
            <span className="live-dot" />
            <span>LIVE MONITORING</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="sidebar-nav">
          <div className="nav-label">MODULES</div>
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const isActive = location.pathname === item.path;
            return (
              <button
                key={item.path}
                className={`nav-item ${isActive ? 'nav-item-active' : ''}`}
                onClick={() => handleNav(item.path)}
              >
                <div className="nav-item-icon">
                  <Icon size={16} />
                </div>
                <div className="nav-item-text">
                  <span className="nav-item-label">{item.label}</span>
                  <span className="nav-item-sub">{item.subtitle}</span>
                </div>
                {isActive && <ChevronRight size={12} className="nav-item-arrow" />}
              </button>
            );
          })}
        </nav>

        {/* System Status */}
        <div className="sidebar-footer">
          <div className="sys-status">
            <div className="sys-status-row">
              <span>API</span>
              <span className="status-green">ONLINE</span>
            </div>
            <div className="sys-status-row">
              <span>DB</span>
              <span className="status-green">SYNCED</span>
            </div>
            <div className="sys-status-row">
              <span>ML</span>
              <span className="status-amber">RUNNING</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
}

function Header({ onMenuClick, currentPath }) {
  const page = NAV_ITEMS.find(n => n.path === currentPath) || NAV_ITEMS[0];
  return (
    <header className="app-header">
      <div className="header-left">
        <button className="menu-btn" onClick={onMenuClick}>
          <Menu size={18} />
        </button>
        <div className="header-breadcrumb">
          <span className="breadcrumb-root">PUNE SELF-HEALING SUPPLY CHAIN</span>
          <ChevronRight size={12} className="breadcrumb-sep" />
          <span className="breadcrumb-page">{page.label.toUpperCase()}</span>
        </div>
      </div>
      <div className="header-right">
        <div className="header-badge">
          <span className="live-dot" style={{ width: 6, height: 6 }} />
          <span>SYSTEM NOMINAL</span>
        </div>
      </div>
    </header>
  );
}

function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();

  return (
    <div className="app-layout">
      <div className="grid-bg" />
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="app-main">
        <Header onMenuClick={() => setSidebarOpen(!sidebarOpen)} currentPath={location.pathname} />
        <main className="app-content">
          <Routes>
            <Route path="/"           element={<DashboardPage />} />
            <Route path="/map"        element={<SupplyChainMap />} />
            <Route path="/shipments"  element={<ShipmentTracker />} />
            <Route path="/timeline"   element={<AnomalyTimeline />} />
            <Route path="/decisions"  element={<DecisionEngine />} />
            <Route path="/blockchain" element={<BlockchainLog />} />
          </Routes>
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <Router>
      <AppLayout />
    </Router>
  );
}
