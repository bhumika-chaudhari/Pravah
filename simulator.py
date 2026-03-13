"""
Supply Chain Data Simulator
Simulates a Pune automotive manufacturer's real-time supply chain:
- 5 component types (semiconductors, steel, rubber, wiring, petrochemicals)
- 3 suppliers per component
- Shipment tracking, inventory levels, supplier reliability
- Realistic disruption events injected probabilistically
"""

import random
import json
import time
import math
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import Optional
import sqlite3
import os

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

COMPONENTS = {
    "semiconductor": {
        "unit_cost_inr": 8500,
        "critical": True,
        "daily_consumption": 200,         # units/day
        "lead_time_days": 14,
        "safety_stock_days": 3,
    },
    "steel_sheets": {
        "unit_cost_inr": 120,
        "critical": True,
        "daily_consumption": 500,
        "lead_time_days": 7,
        "safety_stock_days": 5,
    },
    "rubber_seals": {
        "unit_cost_inr": 45,
        "critical": False,
        "daily_consumption": 1200,
        "lead_time_days": 5,
        "safety_stock_days": 7,
    },
    "wiring_harness": {
        "unit_cost_inr": 3200,
        "critical": True,
        "daily_consumption": 150,
        "lead_time_days": 10,
        "safety_stock_days": 4,
    },
    "petrochemical_resin": {
        "unit_cost_inr": 210,
        "critical": False,
        "daily_consumption": 800,
        "lead_time_days": 6,
        "safety_stock_days": 6,
    },
}

SUPPLIERS = {
    "semiconductor": [
        {"id": "SUP_SC_01", "name": "TaiwanChip Co",    "country": "Taiwan",  "base_reliability": 0.92, "base_delay_days": 1.2},
        {"id": "SUP_SC_02", "name": "Samsung Semi",      "country": "Korea",   "base_reliability": 0.95, "base_delay_days": 0.8},
        {"id": "SUP_SC_03", "name": "IndiaSemi Pvt",     "country": "India",   "base_reliability": 0.80, "base_delay_days": 0.5},
    ],
    "steel_sheets": [
        {"id": "SUP_ST_01", "name": "SAIL India",        "country": "India",   "base_reliability": 0.90, "base_delay_days": 0.5},
        {"id": "SUP_ST_02", "name": "POSCO Korea",       "country": "Korea",   "base_reliability": 0.94, "base_delay_days": 1.0},
        {"id": "SUP_ST_03", "name": "ArcelorMittal",     "country": "Germany", "base_reliability": 0.96, "base_delay_days": 2.0},
    ],
    "rubber_seals": [
        {"id": "SUP_RB_01", "name": "PuneRubber Ltd",   "country": "India",   "base_reliability": 0.88, "base_delay_days": 0.3},
        {"id": "SUP_RB_02", "name": "ThaiSeal Corp",    "country": "Thailand","base_reliability": 0.91, "base_delay_days": 1.5},
        {"id": "SUP_RB_03", "name": "MalayRubber Inc",  "country": "Malaysia","base_reliability": 0.89, "base_delay_days": 1.8},
    ],
    "wiring_harness": [
        {"id": "SUP_WH_01", "name": "Yazaki India",     "country": "India",   "base_reliability": 0.93, "base_delay_days": 0.4},
        {"id": "SUP_WH_02", "name": "Sumitomo Electric","country": "Japan",   "base_reliability": 0.96, "base_delay_days": 1.5},
        {"id": "SUP_WH_03", "name": "Motherson Sumi",   "country": "India",   "base_reliability": 0.91, "base_delay_days": 0.6},
    ],
    "petrochemical_resin": [
        {"id": "SUP_PC_01", "name": "HPCL Mumbai",      "country": "India",   "base_reliability": 0.89, "base_delay_days": 0.5},
        {"id": "SUP_PC_02", "name": "BASF India",       "country": "Germany", "base_reliability": 0.94, "base_delay_days": 2.5},
        {"id": "SUP_PC_03", "name": "Reliance Petro",   "country": "India",   "base_reliability": 0.87, "base_delay_days": 0.6},
    ],
}

# Disruption event types and their probabilities per tick
DISRUPTION_EVENTS = [
    {"type": "port_delay",         "prob": 0.04, "severity": "medium", "delay_multiplier": 2.5, "description": "Mumbai/Chennai port congestion"},
    {"type": "supplier_failure",   "prob": 0.02, "severity": "high",   "delay_multiplier": 5.0, "description": "Supplier production line down"},
    {"type": "weather_event",      "prob": 0.03, "severity": "medium", "delay_multiplier": 3.0, "description": "Cyclone/flood affecting logistics route"},
    {"type": "semiconductor_shock","prob": 0.02, "severity": "critical","delay_multiplier": 8.0, "description": "Global semiconductor allocation cut"},
    {"type": "tariff_change",      "prob": 0.01, "severity": "low",    "delay_multiplier": 1.5, "description": "Import tariff increase on components"},
    {"type": "cyberattack",        "prob": 0.01, "severity": "high",   "delay_multiplier": 4.0, "description": "ERP/logistics system compromised"},
    {"type": "demand_spike",       "prob": 0.05, "severity": "medium", "delay_multiplier": 1.0, "description": "Unexpected production order increase +30%"},
]


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────

@dataclass
class InventoryRecord:
    timestamp: str
    component: str
    current_stock: float        # units on hand
    daily_consumption: float
    days_of_stock: float        # current_stock / daily_consumption
    safety_stock_days: float
    stock_status: str           # "healthy" | "warning" | "critical"
    inbound_shipments: int      # number of shipments in transit

@dataclass
class ShipmentRecord:
    timestamp: str
    shipment_id: str
    component: str
    supplier_id: str
    supplier_name: str
    origin_country: str
    quantity: float
    expected_delivery: str
    actual_delay_days: float
    status: str                 # "on_time" | "delayed" | "critical_delay" | "delivered"
    disruption_type: Optional[str]
    disruption_description: Optional[str]
    cost_inr: float

@dataclass
class SupplierHealthRecord:
    timestamp: str
    supplier_id: str
    supplier_name: str
    component: str
    reliability_score: float    # 0–1, rolling average
    avg_delay_days: float
    recent_disruptions: int
    health_status: str          # "healthy" | "degraded" | "at_risk"

@dataclass
class ExternalSignal:
    timestamp: str
    signal_type: str
    severity: str
    affected_component: Optional[str]
    affected_supplier: Optional[str]
    description: str
    estimated_impact_days: float


# ─────────────────────────────────────────────
# SIMULATOR
# ─────────────────────────────────────────────

class SupplyChainSimulator:
    def __init__(self, db_path: str = "supplychain.db", seed: int = 42):
        random.seed(seed)
        self.db_path = db_path
        self.tick = 0
        self.base_time = datetime.now() - timedelta(days=30)

        # State
        self.inventory = {
            comp: cfg["daily_consumption"] * (cfg["safety_stock_days"] + random.uniform(2, 8))
            for comp, cfg in COMPONENTS.items()
        }
        self.supplier_reliability = {
            comp: {s["id"]: s["base_reliability"] for s in sups}
            for comp, sups in SUPPLIERS.items()
        }
        self.active_shipments = []      # shipments in transit
        self.active_disruptions = []    # ongoing disruption events
        self.shipment_counter = 1000

        self._init_db()
        print(f"[Simulator] Initialized. DB: {db_path}")

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.executescript("""
            CREATE TABLE IF NOT EXISTS inventory (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, component TEXT,
                current_stock REAL, daily_consumption REAL,
                days_of_stock REAL, safety_stock_days REAL,
                stock_status TEXT, inbound_shipments INTEGER
            );
            CREATE TABLE IF NOT EXISTS shipments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, shipment_id TEXT, component TEXT,
                supplier_id TEXT, supplier_name TEXT, origin_country TEXT,
                quantity REAL, expected_delivery TEXT,
                actual_delay_days REAL, status TEXT,
                disruption_type TEXT, disruption_description TEXT, cost_inr REAL
            );
            CREATE TABLE IF NOT EXISTS supplier_health (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, supplier_id TEXT, supplier_name TEXT,
                component TEXT, reliability_score REAL, avg_delay_days REAL,
                recent_disruptions INTEGER, health_status TEXT
            );
            CREATE TABLE IF NOT EXISTS external_signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT, signal_type TEXT, severity TEXT,
                affected_component TEXT, affected_supplier TEXT,
                description TEXT, estimated_impact_days REAL
            );
        """)
        conn.commit()
        conn.close()

    def _now(self) -> str:
        t = self.base_time + timedelta(hours=self.tick * 6)
        return t.isoformat()

    def _maybe_trigger_disruption(self) -> Optional[dict]:
        for event in DISRUPTION_EVENTS:
            if random.random() < event["prob"]:
                # Pick affected component (critical ones more likely)
                weights = [
                    3 if COMPONENTS[c]["critical"] else 1
                    for c in COMPONENTS
                ]
                comp = random.choices(list(COMPONENTS.keys()), weights=weights)[0]
                supplier = random.choice(SUPPLIERS[comp])
                disruption = {
                    **event,
                    "component": comp,
                    "supplier": supplier,
                    "started_at": self._now(),
                    "duration_ticks": random.randint(2, 8),
                    "ticks_remaining": random.randint(2, 8),
                }
                self.active_disruptions.append(disruption)
                return disruption
        return None

    def _generate_shipment(self, component: str) -> ShipmentRecord:
        cfg = COMPONENTS[component]
        supplier = random.choice(SUPPLIERS[component])
        qty = cfg["daily_consumption"] * random.uniform(5, 15)

        # Check if this supplier is affected by active disruption
        disruption = None
        for d in self.active_disruptions:
            if d["component"] == component and d["supplier"]["id"] == supplier["id"]:
                disruption = d
                break

        base_delay = supplier["base_delay_days"] * random.uniform(0.5, 1.8)
        if disruption:
            actual_delay = base_delay * disruption["delay_multiplier"]
        else:
            actual_delay = base_delay

        expected = datetime.fromisoformat(self._now()) + timedelta(days=cfg["lead_time_days"])
        status = (
            "critical_delay" if actual_delay > 5 else
            "delayed"        if actual_delay > 2 else
            "on_time"
        )

        self.shipment_counter += 1
        shp = ShipmentRecord(
            timestamp=self._now(),
            shipment_id=f"SHP-{self.shipment_counter}",
            component=component,
            supplier_id=supplier["id"],
            supplier_name=supplier["name"],
            origin_country=supplier["country"],
            quantity=round(qty),
            expected_delivery=expected.isoformat(),
            actual_delay_days=round(actual_delay, 2),
            status=status,
            disruption_type=disruption["type"] if disruption else None,
            disruption_description=disruption["description"] if disruption else None,
            cost_inr=round(qty * cfg["unit_cost_inr"] * random.uniform(0.95, 1.1)),
        )
        # Track as in-transit for later inventory replenishment
        self.active_shipments.append(shp)
        return shp

    def _update_inventory(self, component: str) -> InventoryRecord:
        cfg = COMPONENTS[component]
        consumption = cfg["daily_consumption"] / 4  # per 6h tick
        noise = random.uniform(0.85, 1.15)
        self.inventory[component] = max(0, self.inventory[component] - consumption * noise)

        # Deliveries arriving
        days_stock = self.inventory[component] / cfg["daily_consumption"]
        inbound = sum(1 for s in self.active_shipments if s.component == component)

        status = (
            "critical" if days_stock < cfg["safety_stock_days"] * 0.5 else
            "warning"  if days_stock < cfg["safety_stock_days"] else
            "healthy"
        )

        return InventoryRecord(
            timestamp=self._now(),
            component=component,
            current_stock=round(self.inventory[component]),
            daily_consumption=cfg["daily_consumption"],
            days_of_stock=round(days_stock, 2),
            safety_stock_days=cfg["safety_stock_days"],
            stock_status=status,
            inbound_shipments=inbound,
        )

    def _process_arrivals(self):
        """
        Apply arrivals from in-transit shipments into on-hand inventory
        when their (expected_delivery + actual_delay_days) is in the past.
        """
        if not self.active_shipments:
            return

        now_dt = datetime.fromisoformat(self._now())
        still_in_transit = []

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        for shp in self.active_shipments:
            try:
                expected_dt = datetime.fromisoformat(shp.expected_delivery)
            except Exception:
                expected_dt = now_dt
            arrival_dt = expected_dt + timedelta(days=shp.actual_delay_days)

            if arrival_dt <= now_dt:
                # Shipment has arrived: add to inventory and mark as delivered
                self.inventory[shp.component] += shp.quantity
                cur.execute(
                    "UPDATE shipments SET status = ? WHERE shipment_id = ?",
                    ("delivered", shp.shipment_id),
                )
            else:
                still_in_transit.append(shp)

        conn.commit()
        conn.close()
        self.active_shipments = still_in_transit

    def _update_supplier_health(self, component: str, supplier: dict) -> SupplierHealthRecord:
        sid = supplier["id"]
        base_rel = supplier["base_reliability"]

        # Degrade reliability if disruptions active
        active = [d for d in self.active_disruptions
                  if d["component"] == component and d["supplier"]["id"] == sid]
        degradation = len(active) * 0.08
        reliability = max(0.3, base_rel - degradation + random.uniform(-0.02, 0.02))

        self.supplier_reliability[component][sid] = reliability

        status = (
            "at_risk"  if reliability < 0.75 else
            "degraded" if reliability < 0.88 else
            "healthy"
        )

        return SupplierHealthRecord(
            timestamp=self._now(),
            supplier_id=sid,
            supplier_name=supplier["name"],
            component=component,
            reliability_score=round(reliability, 3),
            avg_delay_days=round(supplier["base_delay_days"] * (1 + len(active) * 0.5), 2),
            recent_disruptions=len(active),
            health_status=status,
        )

    def tick_once(self) -> dict:
        """Advance simulation by one 6-hour tick. Returns all generated records."""
        self.tick += 1
        results = {
            "tick": self.tick,
            "timestamp": self._now(),
            "inventory": [],
            "shipments": [],
            "supplier_health": [],
            "external_signals": [],
            "disruptions_triggered": [],
        }

        # 1. Maybe trigger disruption
        disruption = self._maybe_trigger_disruption()
        if disruption:
            signal = ExternalSignal(
                timestamp=self._now(),
                signal_type=disruption["type"],
                severity=disruption["severity"],
                affected_component=disruption["component"],
                affected_supplier=disruption["supplier"]["id"],
                description=disruption["description"],
                estimated_impact_days=disruption["delay_multiplier"],
            )
            results["external_signals"].append(signal)
            results["disruptions_triggered"].append(disruption)
            self._save_signal(signal)

        # 2. Age out resolved disruptions
        self.active_disruptions = [
            {**d, "ticks_remaining": d["ticks_remaining"] - 1}
            for d in self.active_disruptions
            if d["ticks_remaining"] > 1
        ]

        # 3. Process arrivals from in-transit shipments
        self._process_arrivals()

        # 4. Per component: update inventory + maybe generate shipment
        for comp in COMPONENTS:
            inv = self._update_inventory(comp)
            results["inventory"].append(inv)
            self._save_inventory(inv)

            # Generate shipment every ~4 ticks (once a day) with jitter
            if self.tick % 4 == (list(COMPONENTS.keys()).index(comp) % 4):
                shp = self._generate_shipment(comp)
                results["shipments"].append(shp)
                self._save_shipment(shp)

        # 5. Supplier health for all
        for comp, sups in SUPPLIERS.items():
            for sup in sups:
                sh = self._update_supplier_health(comp, sup)
                results["supplier_health"].append(sh)
                self._save_supplier_health(sh)

        return results

    def run(self, ticks: int = 120, delay_seconds: float = 0.0):
        """Run simulation for N ticks (default 120 = 30 days of 6h ticks)."""
        print(f"[Simulator] Running {ticks} ticks ({ticks * 6 / 24:.0f} days simulated)...")
        for i in range(ticks):
            result = self.tick_once()
            nd = len(result["disruptions_triggered"])
            ni = len([r for r in result["inventory"] if r.stock_status != "healthy"])
            if nd or ni:
                print(f"  Tick {self.tick:03d} | {result['timestamp'][:16]} "
                      f"| ⚠ {nd} disruption(s) | {ni} inventory warning(s)")
            if delay_seconds:
                time.sleep(delay_seconds)
        print(f"[Simulator] Done. Data saved to {self.db_path}")

    # ── DB save helpers ──
    def _save_inventory(self, r: InventoryRecord):
        self._insert("inventory", asdict(r))

    def _save_shipment(self, r: ShipmentRecord):
        self._insert("shipments", asdict(r))

    def _save_supplier_health(self, r: SupplierHealthRecord):
        self._insert("supplier_health", asdict(r))

    def _save_signal(self, r: ExternalSignal):
        self._insert("external_signals", asdict(r))

    def _insert(self, table: str, data: dict):
        conn = sqlite3.connect(self.db_path)
        cols = ", ".join(data.keys())
        placeholders = ", ".join("?" for _ in data)
        conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(data.values()))
        conn.commit()
        conn.close()

    def get_summary(self) -> dict:
        """Return a quick summary of the simulated dataset."""
        conn = sqlite3.connect(self.db_path)
        summary = {}
        for table in ["inventory", "shipments", "supplier_health", "external_signals"]:
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            summary[table] = count
        disruptions = conn.execute(
            "SELECT disruption_type, COUNT(*) FROM shipments WHERE disruption_type IS NOT NULL GROUP BY disruption_type"
        ).fetchall()
        summary["disruptions_by_type"] = dict(disruptions)
        critical_inv = conn.execute(
            "SELECT component, COUNT(*) FROM inventory WHERE stock_status='critical' GROUP BY component"
        ).fetchall()
        summary["critical_inventory_events"] = dict(critical_inv)
        conn.close()
        return summary


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    db_path = os.path.join(os.path.dirname(__file__), "supplychain.db")

    # Remove old DB if exists
    if os.path.exists(db_path):
        os.remove(db_path)
        print(f"[Simulator] Removed old database.")

    sim = SupplyChainSimulator(db_path=db_path, seed=42)

    # Generate 120 ticks = 30 days of historical data
    sim.run(ticks=120)

    print("\n── DATASET SUMMARY ──")
    summary = sim.get_summary()
    for k, v in summary.items():
        print(f"  {k}: {v}")
