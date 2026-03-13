# ⚡ Supply Chain Control Tower — React Frontend

A premium industrial-futuristic React dashboard for the Pune Self-Healing Supply Chain system.

## Architecture

```
src/
├── App.js              ← Root layout: sidebar + header + routing
├── App.css             ← Layout styles (sidebar, header, grid, responsive)
├── index.css           ← Global design system (CSS variables, components)
├── services/
│   └── api.js          ← All API calls (no hardcoding, uses .env)
└── pages/
    ├── DashboardPage.js    ← KPIs, charts, live alerts & decisions
    ├── SupplyChainMap.js   ← SVG network map with live node data
    ├── AnomalyTimeline.js  ← Filtered anomaly feed + trend charts
    ├── DecisionEngine.js   ← AI decision queue + approval workflow
    ├── BlockchainLog.js    ← Paginated audit chain with hash view
    └── pages.css           ← Shared page component styles
```

## Quick Start

### 1. Start the FastAPI Backend
```bash
cd /path/to/supplychain
uvicorn api_server:app --reload --port 8000
```

### 2. Install & Run React App
```bash
cd supply-chain-app
npm install
npm start
```

Open [http://localhost:3000](http://localhost:3000)

## API Endpoints Used

| Page              | Endpoint                     |
|-------------------|------------------------------|
| Dashboard         | `GET /api/dashboard/metrics` |
| Dashboard         | `GET /api/alerts/active`     |
| Dashboard         | `GET /api/decisions/pending` |
| Anomaly Timeline  | `GET /api/anomalies/timeline`|
| Decision Engine   | `GET /api/decisions/pending` |
| Decision Engine   | `PUT /api/decisions/:id`     |
| Blockchain Log    | `GET /api/blockchain/logs`   |
| Network Map       | `GET /api/map/network`       |

## Configuration

Edit `.env` to point to your backend:
```
REACT_APP_API_URL=http://localhost:8000/api
```

## Features

- ✅ **Fully dynamic** — zero hardcoded data, all from FastAPI
- ✅ **Auto-refresh** — Dashboard polls every 30s
- ✅ **Error handling** — Graceful fallback with retry buttons
- ✅ **Responsive** — Works on mobile/tablet/desktop
- ✅ **Industrial UI** — Rajdhani + IBM Plex Mono design system
- ✅ **Interactive Map** — SVG with node hover/click, animated shipment routes
- ✅ **Approval workflow** — Approve/reject decisions inline
- ✅ **Blockchain viewer** — Expandable hash rows + JSON payload display
- ✅ **Paginated logs** — 15 entries/page with search + filter

## Dependencies

Only **4 dependencies** beyond react:
- `react-router-dom` — routing
- `recharts` — charts
- `lucide-react` — icons
- `axios` — *(not used, native fetch is used instead)*

No Material UI, no heavy component libraries — pure CSS design system.
