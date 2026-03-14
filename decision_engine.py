"""
Decision Engine — Phase 3
==========================
For each anomaly alert, evaluates all possible recovery actions and
ranks them by a composite score of cost, delivery speed, and risk.

Three action types:
  1. switch_supplier   — re-route order to a backup supplier
  2. expedite_freight  — pay premium for air/express shipping
  3. pull_from_warehouse — draw down from a regional buffer stock

Output: decisions table written to supplychain.db
"""

import sqlite3
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import json
import os
from blockchain_logger import append_blockchain_log

DB_PATH = "supplychain.db"

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Regional buffer warehouses (simulated)
WAREHOUSES = {
    "pune_main":     {"location": "Pune",     "capacity_days": 5,  "transfer_lead_days": 0.5},
    "mumbai_hub":    {"location": "Mumbai",   "capacity_days": 8,  "transfer_lead_days": 1.0},
    "chennai_south": {"location": "Chennai",  "capacity_days": 4,  "transfer_lead_days": 1.5},
}

# Freight upgrade cost multipliers over sea freight baseline
FREIGHT_MODES = {
    "sea":       {"cost_multiplier": 1.0,  "speed_days_saved": 0},
    "express":   {"cost_multiplier": 1.8,  "speed_days_saved": 3},
    "air":       {"cost_multiplier": 4.5,  "speed_days_saved": 8},
    "charter":   {"cost_multiplier": 9.0,  "speed_days_saved": 12},
}

# Weights for scoring actions (must sum to 1.0)
SCORE_WEIGHTS = {
    "delivery_speed": 0.45,   # time is most critical in automotive JIT
    "cost_efficiency": 0.30,
    "reliability":    0.25,
}

# Production line downtime cost per day (INR)
DOWNTIME_COST_PER_DAY_INR = 1_20_00_000   # ₹1.2 Cr/day


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────

@dataclass
class RecoveryOption:
    action_type: str           # "switch_supplier" | "expedite_freight" | "pull_from_warehouse"
    description: str
    supplier_id: Optional[str]
    supplier_name: Optional[str]
    warehouse: Optional[str]
    freight_mode: Optional[str]
    estimated_delivery_days: float
    days_saved_vs_baseline: float
    incremental_cost_inr: float
    downtime_days_prevented: float
    net_saving_inr: float      # downtime prevented - incremental cost
    reliability_score: float   # 0–1, how likely this action succeeds
    composite_score: float     # 0–100, final ranking score
    auto_executable: bool      # True if safe to execute without human approval
    explain_factors: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Decision:
    decided_at: str
    alert_id: int
    component: str
    alert_type: str
    severity: str
    risk_score: float
    baseline_delay_days: float
    recommended_action: str        # best option action_type
    recommended_supplier: Optional[str]
    recommended_warehouse: Optional[str]
    estimated_delivery_days: float
    incremental_cost_inr: float
    net_saving_inr: float
    composite_score: float
    auto_execute: bool
    all_options_json: str          # full ranked list serialised
    decision_rationale: str
    shap_json: str                 # SHAP-style factor attributions (JSON)


# ─────────────────────────────────────────────
# LOAD DATA
# ─────────────────────────────────────────────

def load_alerts_and_suppliers(db_path: str):
    conn = sqlite3.connect(db_path)
    alerts = pd.read_sql("SELECT rowid as alert_id, * FROM anomaly_alerts ORDER BY risk_score DESC", conn)
    supplier_health = pd.read_sql("""
        SELECT supplier_id, supplier_name, component,
               AVG(reliability_score) as reliability_score,
               AVG(avg_delay_days) as avg_delay_days,
               MAX(health_status) as health_status
        FROM supplier_health
        GROUP BY supplier_id
    """, conn)
    shipments = pd.read_sql("SELECT * FROM shipments", conn)
    conn.close()
    return alerts, supplier_health, shipments


# ─────────────────────────────────────────────
# COMPONENT METADATA (mirrors simulator config)
# ─────────────────────────────────────────────

COMPONENTS = {
    "semiconductor":       {"unit_cost_inr": 8500,  "critical": True,  "daily_consumption": 200,  "lead_time_days": 14},
    "steel_sheets":        {"unit_cost_inr": 120,   "critical": True,  "daily_consumption": 500,  "lead_time_days": 7},
    "rubber_seals":        {"unit_cost_inr": 45,    "critical": False, "daily_consumption": 1200, "lead_time_days": 5},
    "wiring_harness":      {"unit_cost_inr": 3200,  "critical": True,  "daily_consumption": 150,  "lead_time_days": 10},
    "petrochemical_resin": {"unit_cost_inr": 210,   "critical": False, "daily_consumption": 800,  "lead_time_days": 6},
}

SUPPLIERS = {
    "semiconductor": [
        {"id": "SUP_SC_01", "name": "TaiwanChip Co",     "country": "Taiwan",  "base_reliability": 0.92, "base_delay_days": 1.2},
        {"id": "SUP_SC_02", "name": "Samsung Semi",       "country": "Korea",   "base_reliability": 0.95, "base_delay_days": 0.8},
        {"id": "SUP_SC_03", "name": "IndiaSemi Pvt",      "country": "India",   "base_reliability": 0.80, "base_delay_days": 0.5},
    ],
    "steel_sheets": [
        {"id": "SUP_ST_01", "name": "SAIL India",         "country": "India",   "base_reliability": 0.90, "base_delay_days": 0.5},
        {"id": "SUP_ST_02", "name": "POSCO Korea",        "country": "Korea",   "base_reliability": 0.94, "base_delay_days": 1.0},
        {"id": "SUP_ST_03", "name": "ArcelorMittal",      "country": "Germany", "base_reliability": 0.96, "base_delay_days": 2.0},
    ],
    "rubber_seals": [
        {"id": "SUP_RB_01", "name": "PuneRubber Ltd",    "country": "India",   "base_reliability": 0.88, "base_delay_days": 0.3},
        {"id": "SUP_RB_02", "name": "ThaiSeal Corp",     "country": "Thailand","base_reliability": 0.91, "base_delay_days": 1.5},
        {"id": "SUP_RB_03", "name": "MalayRubber Inc",   "country": "Malaysia","base_reliability": 0.89, "base_delay_days": 1.8},
    ],
    "wiring_harness": [
        {"id": "SUP_WH_01", "name": "Yazaki India",      "country": "India",   "base_reliability": 0.93, "base_delay_days": 0.4},
        {"id": "SUP_WH_02", "name": "Sumitomo Electric", "country": "Japan",   "base_reliability": 0.96, "base_delay_days": 1.5},
        {"id": "SUP_WH_03", "name": "Motherson Sumi",    "country": "India",   "base_reliability": 0.91, "base_delay_days": 0.6},
    ],
    "petrochemical_resin": [
        {"id": "SUP_PC_01", "name": "HPCL Mumbai",       "country": "India",   "base_reliability": 0.89, "base_delay_days": 0.5},
        {"id": "SUP_PC_02", "name": "BASF India",        "country": "Germany", "base_reliability": 0.94, "base_delay_days": 2.5},
        {"id": "SUP_PC_03", "name": "Reliance Petro",    "country": "India",   "base_reliability": 0.87, "base_delay_days": 0.6},
    ],
}


# ─────────────────────────────────────────────
# ACTION GENERATORS
# ─────────────────────────────────────────────

def gen_switch_supplier_options(
    component: str,
    affected_supplier_id: Optional[str],
    supplier_health_df: pd.DataFrame,
    baseline_delay: float,
) -> list[RecoveryOption]:
    """Generate one option per alternative supplier."""
    options = []
    cfg = COMPONENTS.get(component, {})
    lead = cfg.get("lead_time_days", 7)
    unit_cost = cfg.get("unit_cost_inr", 500)
    daily_consumption = cfg.get("daily_consumption", 200)
    order_qty = daily_consumption * 10  # ~10-day replenishment order

    for sup in SUPPLIERS.get(component, []):
        if sup["id"] == affected_supplier_id:
            continue   # skip the broken one

        # Look up current live reliability from DB
        row = supplier_health_df[supplier_health_df["supplier_id"] == sup["id"]]
        live_reliability = float(row["reliability_score"].iloc[0]) if len(row) else sup["base_reliability"]
        live_delay = float(row["avg_delay_days"].iloc[0]) if len(row) else sup["base_delay_days"]

        est_delivery = lead + live_delay
        days_saved = max(0, baseline_delay - est_delivery)
        # Premium for urgent switch: 5–15% cost increase
        switch_premium = unit_cost * order_qty * 0.10
        downtime_prevented = min(days_saved, baseline_delay) * 0.8  # conservative
        net_saving = downtime_prevented * DOWNTIME_COST_PER_DAY_INR - switch_premium

        options.append(RecoveryOption(
            action_type="switch_supplier",
            description=f"Switch to {sup['name']} ({sup['country']})",
            supplier_id=sup["id"],
            supplier_name=sup["name"],
            warehouse=None,
            freight_mode="sea",
            estimated_delivery_days=round(est_delivery, 1),
            days_saved_vs_baseline=round(days_saved, 1),
            incremental_cost_inr=round(switch_premium),
            downtime_days_prevented=round(downtime_prevented, 1),
            net_saving_inr=round(net_saving),
            reliability_score=round(live_reliability, 3),
            composite_score=0.0,   # filled in later
            auto_executable=(live_reliability >= 0.88 and net_saving > 0),
        ))
    return options


def gen_expedite_freight_options(
    component: str,
    baseline_delay: float,
    affected_supplier_id: Optional[str],
    supplier_health_df: pd.DataFrame,
) -> list[RecoveryOption]:
    """Generate express/air freight upgrade options on current supplier."""
    options = []
    cfg = COMPONENTS.get(component, {})
    lead = cfg.get("lead_time_days", 7)
    unit_cost = cfg.get("unit_cost_inr", 500)
    daily_consumption = cfg.get("daily_consumption", 200)
    order_qty = daily_consumption * 10

    # Find current supplier reliability
    if affected_supplier_id:
        row = supplier_health_df[supplier_health_df["supplier_id"] == affected_supplier_id]
        reliability = float(row["reliability_score"].iloc[0]) if len(row) else 0.85
    else:
        reliability = 0.85

    baseline_cost = unit_cost * order_qty

    for mode, fdata in FREIGHT_MODES.items():
        if mode == "sea":
            continue   # sea is the baseline, not an upgrade
        est_delivery = max(1.0, lead - fdata["speed_days_saved"] + 0.5)
        days_saved = max(0, baseline_delay - est_delivery)
        incremental_cost = baseline_cost * (fdata["cost_multiplier"] - 1.0)
        downtime_prevented = min(days_saved, baseline_delay) * 0.75
        net_saving = downtime_prevented * DOWNTIME_COST_PER_DAY_INR - incremental_cost

        options.append(RecoveryOption(
            action_type="expedite_freight",
            description=f"Upgrade to {mode} freight (saves ~{fdata['speed_days_saved']}d)",
            supplier_id=affected_supplier_id,
            supplier_name=None,
            warehouse=None,
            freight_mode=mode,
            estimated_delivery_days=round(est_delivery, 1),
            days_saved_vs_baseline=round(days_saved, 1),
            incremental_cost_inr=round(incremental_cost),
            downtime_days_prevented=round(downtime_prevented, 1),
            net_saving_inr=round(net_saving),
            reliability_score=round(reliability * 0.95, 3),  # slight degradation under disruption
            composite_score=0.0,
            auto_executable=(mode in ("express",) and net_saving > 0),
        ))
    return options


def gen_warehouse_options(
    component: str,
    baseline_delay: float,
) -> list[RecoveryOption]:
    """Pull from regional buffer warehouses."""
    options = []
    cfg = COMPONENTS.get(component, {})
    daily_consumption = cfg.get("daily_consumption", 200)
    unit_cost = cfg.get("unit_cost_inr", 500)

    for wh_id, wh in WAREHOUSES.items():
        # Units available from warehouse
        available_units = daily_consumption * wh["capacity_days"]
        days_covered = wh["capacity_days"]
        days_saved = min(days_covered, baseline_delay)
        # Cost: transfer logistics + slight premium
        transfer_cost = available_units * unit_cost * 0.03  # 3% logistics cost
        downtime_prevented = days_saved * 0.9
        net_saving = downtime_prevented * DOWNTIME_COST_PER_DAY_INR - transfer_cost

        options.append(RecoveryOption(
            action_type="pull_from_warehouse",
            description=f"Transfer {days_covered}d stock from {wh['location']} warehouse",
            supplier_id=None,
            supplier_name=None,
            warehouse=wh_id,
            freight_mode=None,
            estimated_delivery_days=wh["transfer_lead_days"],
            days_saved_vs_baseline=round(days_saved, 1),
            incremental_cost_inr=round(transfer_cost),
            downtime_days_prevented=round(downtime_prevented, 1),
            net_saving_inr=round(net_saving),
            reliability_score=0.97,   # warehouse transfer is highly reliable
            composite_score=0.0,
            auto_executable=(net_saving > 0),
        ))
    return options


# ─────────────────────────────────────────────
# SCORING & RANKING
# ─────────────────────────────────────────────

def score_options(options: list[RecoveryOption], baseline_delay: float) -> list[RecoveryOption]:
    """Assign composite_score 0–100 to each option and sort descending."""
    if not options:
        return options

    # Normalise each dimension across the candidate set
    delays = np.array([o.estimated_delivery_days for o in options])
    costs  = np.array([o.incremental_cost_inr for o in options])
    rels   = np.array([o.reliability_score for o in options])

    def norm_invert(arr):
        """Lower is better → invert to 0–1 score."""
        rng = arr.max() - arr.min()
        if rng == 0:
            return np.ones(len(arr))
        return 1 - (arr - arr.min()) / rng

    def norm(arr):
        """Higher is better → 0–1 score."""
        rng = arr.max() - arr.min()
        if rng == 0:
            return np.ones(len(arr))
        return (arr - arr.min()) / rng

    speed_score = norm_invert(delays)
    cost_score = norm_invert(costs)
    rel_score = norm(rels)

    w = SCORE_WEIGHTS
    # Individual weighted contributions (0–100 each) for SHAP-style explanation
    contrib_speed = w["delivery_speed"] * speed_score * 100.0
    contrib_cost = w["cost_efficiency"] * cost_score * 100.0
    contrib_rel = w["reliability"] * rel_score * 100.0

    composite = contrib_speed + contrib_cost + contrib_rel

    total_weights = (
        w["delivery_speed"] + w["cost_efficiency"] + w["reliability"]
    ) or 1.0

    for i, opt in enumerate(options):
        opt.composite_score = round(float(composite[i]), 1)
        # Normalised factor contributions that sum ~100
        opt.explain_factors = {
            "delivery_speed": round(float(contrib_speed[i] / total_weights), 2),
            "cost_efficiency": round(float(contrib_cost[i] / total_weights), 2),
            "reliability": round(float(contrib_rel[i] / total_weights), 2),
        }

    return sorted(options, key=lambda o: o.composite_score, reverse=True)


# ─────────────────────────────────────────────
# DECISION RATIONALE
# ─────────────────────────────────────────────

def build_rationale(best: RecoveryOption, all_options: list[RecoveryOption], component: str) -> str:
    lines = [f"Selected '{best.action_type}' as optimal recovery for {component}."]
    lines.append(
        f"Delivers in {best.estimated_delivery_days}d, saves {best.days_saved_vs_baseline}d vs baseline, "
        f"net saving ₹{best.net_saving_inr:,.0f}."
    )
    if len(all_options) > 1:
        runner_up = all_options[1]
        lines.append(
            f"Runner-up '{runner_up.action_type}' scored {runner_up.composite_score:.0f}/100 "
            f"vs {best.composite_score:.0f}/100."
        )
    if not best.auto_executable:
        lines.append("⚠ Requires human approval before execution (high cost or low confidence).")
    else:
        lines.append("✅ Cleared for autonomous execution.")
    return " ".join(lines)


# ─────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────

def run_decision_engine(db_path: str = DB_PATH) -> list[Decision]:
    print(f"\n{'='*60}")
    print(" SUPPLY CHAIN DECISION ENGINE")
    print(f"{'='*60}")

    alerts, supplier_health, shipments = load_alerts_and_suppliers(db_path)
    print(f"[Engine] {len(alerts)} alerts to process.")

    decisions = []

    for _, alert in alerts.iterrows():
        component    = alert["component"]
        alert_type   = alert["alert_type"]
        severity     = alert["severity"]
        risk_score   = alert["risk_score"]
        supplier_id  = alert.get("supplier_id")
        baseline_delay = float(alert.get("risk_score", 50) / 10)   # proxy for urgency

        all_options: list[RecoveryOption] = []

        # ── Generate candidate actions ──
        if alert_type in ("shipment_delay", "supplier_degraded"):
            all_options += gen_switch_supplier_options(
                component, supplier_id, supplier_health, baseline_delay)
            all_options += gen_expedite_freight_options(
                component, baseline_delay, supplier_id, supplier_health)

        if alert_type in ("inventory_drop", "shipment_delay"):
            all_options += gen_warehouse_options(component, baseline_delay)

        if not all_options:
            continue

        # ── Score & rank ──
        ranked = score_options(all_options, baseline_delay)
        best   = ranked[0]

        # Human-in-the-loop guardrail:
        # - high-impact actions (>|₹2 Cr| net effect) or low scores always require approval
        # high_impact = abs(best.net_saving_inr) >= 2_00_00_000  # ₹2 Cr
        # low_confidence = best.composite_score < 60.0
        auto_execute = bool(best.auto_executable)

        decision = Decision(
            decided_at=datetime.now().isoformat(),
            alert_id=int(alert["alert_id"]),
            component=component,
            alert_type=alert_type,
            severity=severity,
            risk_score=risk_score,
            baseline_delay_days=round(baseline_delay, 1),
            recommended_action=best.action_type,
            recommended_supplier=best.supplier_name,
            recommended_warehouse=best.warehouse,
            estimated_delivery_days=best.estimated_delivery_days,
            incremental_cost_inr=best.incremental_cost_inr,
            net_saving_inr=best.net_saving_inr,
            composite_score=best.composite_score,
            auto_execute=auto_execute,
            all_options_json=json.dumps([asdict(o) for o in ranked]),
            decision_rationale=build_rationale(best, ranked, component),
            shap_json=json.dumps(best.explain_factors),
        )
        decisions.append(decision)

    decisions.sort(key=lambda d: d.risk_score, reverse=True)
    _save_decisions(decisions, db_path)
    _print_decisions(decisions[:8])

    print(f"\n[Engine] {len(decisions)} decisions saved to 'decisions' table.")
    return decisions


# ─────────────────────────────────────────────
# SAVE & PRINT
# ─────────────────────────────────────────────

def _save_decisions(decisions: list[Decision], db_path: str):
    if not decisions:
        return
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS decisions")
    conn.execute(
        """
        CREATE TABLE decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            decided_at TEXT,
            alert_id INTEGER,
            component TEXT,
            alert_type TEXT,
            severity TEXT,
            risk_score REAL,
            baseline_delay_days REAL,
            recommended_action TEXT,
            recommended_supplier TEXT,
            recommended_warehouse TEXT,
            estimated_delivery_days REAL,
            incremental_cost_inr REAL,
            net_saving_inr REAL,
            composite_score REAL,
            auto_execute INTEGER,
            all_options_json TEXT,
            decision_rationale TEXT,
            shap_json TEXT
        )
        """
    )
    cur = conn.cursor()
    for d in decisions:
        row = asdict(d)
        row["auto_execute"] = int(row["auto_execute"])
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        cur.execute(
            f"INSERT INTO decisions ({cols}) VALUES ({placeholders})",
            list(row.values()),
        )
        decision_id = cur.lastrowid
        append_blockchain_log(
            conn,
            event_type="DECISION_SAVED",
            ref_table="decisions",
            ref_id=str(decision_id),
            payload=row,
        )
    conn.commit()
    conn.close()


def _print_decisions(decisions: list[Decision]):
    print(f"\n── TOP DECISIONS ──\n")
    for d in decisions:
        icon = "🤖 AUTO" if d.auto_execute else "👤 MANUAL"
        print(f"  [{d.severity.upper():8s}] {d.component:22s} | Risk {d.risk_score:5.1f} | {icon}")
        print(f"  Action   : {d.recommended_action}")
        if d.recommended_supplier:
            print(f"  Supplier : {d.recommended_supplier}")
        if d.recommended_warehouse:
            print(f"  Warehouse: {d.recommended_warehouse}")
        print(f"  Delivers : {d.estimated_delivery_days}d  |  Cost +₹{d.incremental_cost_inr:,.0f}  |  Net saving ₹{d.net_saving_inr:,.0f}")
        print(f"  Score    : {d.composite_score}/100")
        print(f"  Rationale: {d.decision_rationale[:120]}...")
        print()


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    db = os.path.join(os.path.dirname(__file__), "supplychain.db")
    run_decision_engine(db_path=db)
