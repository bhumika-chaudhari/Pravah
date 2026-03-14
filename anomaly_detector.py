"""
Anomaly Detection Engine — Phase 5
====================================
Reads from supplychain.db and detects disruptions using:

  1. Isolation Forest   — unsupervised, catches unknown anomaly shapes
  2. Rule-based layer   — hard thresholds for inventory / delay spikes
  3. Composite scorer   — merges both signals into a 0–100 risk score

Output: anomalies table written back to the same SQLite DB,
        plus a printable alert list,
        an interactive supply chain map,
        and an autonomous self-healing loop that closes alerts.
"""

import sqlite3
import pandas as pd
import numpy as np
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import plotly.graph_objects as go
from blockchain_logger import append_blockchain_log

try:
    # Optional: gradient-boosted disruption classifier
    from xgboost import XGBClassifier  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    XGBClassifier = None

DB_PATH = "supplychain.db"

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────

# Isolation Forest contamination = expected fraction of anomalies
IF_CONTAMINATION = 0.08   # ~8% of ticks expected to be disrupted

# Rule-based hard thresholds
RULES = {
    "delay_critical":        5.0,   # actual_delay_days > this → flag
    "delay_warning":         2.0,
    "days_stock_critical":   1.5,   # days_of_stock < this → flag
    "days_stock_warning":    3.0,
    "reliability_critical":  0.75,
    "reliability_warning":   0.85,
}

SEVERITY_SCORE = {
    "critical": 90,
    "high":     70,
    "medium":   50,
    "low":      25,
    "none":     0,
}


# Approximate geo coordinates for map visualisation
COUNTRY_COORDS = {
    "India": (20.5937, 78.9629),
    "Korea": (35.9078, 127.7669),
    "South Korea": (35.9078, 127.7669),
    "Japan": (36.2048, 138.2529),
    "Taiwan": (23.6978, 120.9605),
    "Germany": (51.1657, 10.4515),
    "Thailand": (15.8700, 100.9925),
    "Malaysia": (4.2105, 101.9758),
}

# Simple illustrative network: 3 warehouses feeding a single factory
WAREHOUSES = {
    "WH_West": {"lat": 19.0760, "lon": 72.8777, "city": "Mumbai"},
    "WH_North": {"lat": 28.7041, "lon": 77.1025, "city": "Delhi"},
    "WH_South": {"lat": 12.9716, "lon": 77.5946, "city": "Bengaluru"},
}

FACTORY = {
    "name": "Main Factory",
    "lat": 23.0225,
    "lon": 72.5714,  # Ahmedabad
}


# ─────────────────────────────────────────────
# DATA MODELS
# ─────────────────────────────────────────────

@dataclass
class AnomalyAlert:
    detected_at: str
    component: str
    alert_type: str          # "shipment_delay" | "inventory_drop" | "supplier_degraded" | "composite"
    severity: str            # "low" | "medium" | "high" | "critical"
    risk_score: float        # 0–100
    description: str
    supplier_id: Optional[str]
    shipment_id: Optional[str]
    isolation_score: float   # raw IF anomaly score (more negative = more anomalous)
    rule_triggered: str      # which rule fired, or "none"
    recommended_action: str


# ─────────────────────────────────────────────
# FEATURE ENGINEERING
# ─────────────────────────────────────────────

def load_data(db_path: str) -> dict[str, pd.DataFrame]:
    conn = sqlite3.connect(db_path)
    tables = {}
    for t in ["inventory", "shipments", "supplier_health", "external_signals"]:
        tables[t] = pd.read_sql(f"SELECT * FROM {t}", conn, parse_dates=["timestamp"])
    conn.close()
    print(
        "[Detector] Loaded data: "
        + ", ".join(f"{k}={len(v)}" for k, v in tables.items())
    )
    return tables


def build_external_risk_boost(
    external_signals: pd.DataFrame,
) -> dict[str, float]:
    """
    Compute a simple per-component risk boost based on recent external signals.

    - critical  → +15 risk points
    - high      → +10
    - medium    → +5
    """
    if external_signals.empty:
        return {}

    severity_weight = {"critical": 15.0, "high": 10.0, "medium": 5.0}
    boosts: dict[str, float] = {}

    for _, row in external_signals.iterrows():
        comp = row.get("affected_component")
        sev = row.get("severity", "medium")
        if not isinstance(comp, str):
            continue
        w = severity_weight.get(sev, 0.0)
        prev = boosts.get(comp, 0.0)
        boosts[comp] = max(prev, w)

    if boosts:
        print(
            "[Detector] External signal boosts: "
            + ", ".join(f"{k}:+{v:.1f}" for k, v in boosts.items())
        )
    return boosts


def build_shipment_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Features per shipment:
      - actual_delay_days
      - delay_ratio            (actual / expected baseline of 1.0)
      - is_critical_component
      - origin_risk            (overseas = higher baseline risk)
      - cost_zscore            (cost spike signals disruption)
    """
    feat = df.copy()
    feat["delay_ratio"] = feat["actual_delay_days"].clip(upper=20) / 2.0
    feat["is_critical"] = feat["component"].isin(
        ["semiconductor", "steel_sheets", "wiring_harness"]
    ).astype(int)
    feat["origin_risk"] = feat["origin_country"].map({
        "India": 0.1, "Korea": 0.3, "Japan": 0.3,
        "Taiwan": 0.5, "Germany": 0.4, "Thailand": 0.6, "Malaysia": 0.6,
    }).fillna(0.5)

    # Cost z-score per component (spike = anomaly)
    feat["cost_zscore"] = feat.groupby("component")["cost_inr"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )
    feat["has_disruption"] = feat["disruption_type"].notna().astype(int)

    return feat[[
        "shipment_id", "component", "supplier_id", "supplier_name",
        "actual_delay_days", "delay_ratio", "is_critical",
        "origin_risk", "cost_zscore", "has_disruption", "status"
    ]]


def build_inventory_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Features per inventory record:
      - days_of_stock
      - stock_ratio           (days_of_stock / safety_stock_days)
      - consumption_spike     (rolling z-score of daily_consumption)
      - drawdown_rate         (how fast stock is falling)
    """
    feat = df.copy().sort_values(["component", "timestamp"])

    feat["stock_ratio"] = feat["days_of_stock"] / feat["safety_stock_days"].clip(lower=0.1)

    # Drawdown rate: negative delta in days_of_stock per tick
    feat["drawdown"] = feat.groupby("component")["days_of_stock"].diff().fillna(0)
    feat["drawdown_zscore"] = feat.groupby("component")["drawdown"].transform(
        lambda x: (x - x.mean()) / (x.std() + 1e-9)
    )

    return feat[[
        "component", "days_of_stock", "safety_stock_days",
        "stock_ratio", "drawdown", "drawdown_zscore",
        "stock_status", "current_stock"
    ]]


def build_supplier_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate per supplier: rolling reliability and delay trend.
    """
    feat = df.copy().sort_values(["supplier_id", "timestamp"])
    feat["rel_drop"] = feat.groupby("supplier_id")["reliability_score"].transform(
        lambda x: x - x.rolling(4, min_periods=1).mean()
    )
    feat["delay_trend"] = feat.groupby("supplier_id")["avg_delay_days"].transform(
        lambda x: x.rolling(4, min_periods=1).mean()
    )
    return feat[[
        "supplier_id", "supplier_name", "component",
        "reliability_score", "avg_delay_days",
        "rel_drop", "delay_trend", "health_status"
    ]]


# ─────────────────────────────────────────────
# ISOLATION FOREST
# ─────────────────────────────────────────────

def run_isolation_forest(feature_matrix: np.ndarray,
                         contamination: float = IF_CONTAMINATION) -> tuple[np.ndarray, np.ndarray]:
    """
    Returns (labels, scores).
    labels: -1 = anomaly, 1 = normal
    scores: lower (more negative) = more anomalous
    """
    scaler = StandardScaler()
    X = scaler.fit_transform(feature_matrix)

    clf = IsolationForest(
        n_estimators=200,
        contamination=contamination,
        random_state=42,
        max_samples="auto",
    )
    clf.fit(X)
    labels = clf.predict(X)        # -1 or 1
    scores = clf.score_samples(X)  # log-likelihood proxy, lower = more anomalous
    return labels, scores


# ─────────────────────────────────────────────
# OPTIONAL: XGBOOST DISRUPTION CLASSIFIER
# ─────────────────────────────────────────────


def train_shipment_xgb_classifier(
    feat: pd.DataFrame,
):
    """
    Train a light-weight XGBoost classifier to estimate disruption probability
    for each shipment, using the engineered features.

    Falls back to None if XGBoost is unavailable or labels are degenerate.
    """
    if XGBClassifier is None:
        print("[Detector] XGBoost not installed; skipping disruption classifier.")
        return None

    if "has_disruption" not in feat.columns:
        return None

    y = feat["has_disruption"].astype(int).values
    # Need both classes to train a classifier
    if y.sum() == 0 or y.sum() == len(y):
        print("[Detector] Not enough label variety for XGBoost; skipping.")
        return None

    X = feat[["actual_delay_days", "delay_ratio", "is_critical", "origin_risk", "cost_zscore"]].values

    clf = XGBClassifier(
        n_estimators=40,
        max_depth=3,
        learning_rate=0.1,
        subsample=0.9,
        colsample_bytree=0.9,
        objective="binary:logistic",
        eval_metric="logloss",
        random_state=42,
        n_jobs=1,
    )
    try:
        clf.fit(X, y)
        print("[Detector] XGBoost shipment classifier trained.")
        return clf
    except Exception as e:  # pragma: no cover - defensive
        print(f"[Detector] XGBoost training failed: {e}")
        return None


# ─────────────────────────────────────────────
# RULE-BASED LAYER
# ─────────────────────────────────────────────

def apply_shipment_rules(row: pd.Series) -> tuple[str, str]:
    """Returns (rule_name, severity)"""
    d = row["actual_delay_days"]
    if d > RULES["delay_critical"]:
        return "delay_critical", "critical"
    if d > RULES["delay_warning"]:
        return "delay_warning", "medium"
    return "none", "none"


def apply_inventory_rules(row: pd.Series) -> tuple[str, str]:
    d = row["days_of_stock"]
    if d < RULES["days_stock_critical"]:
        return "stock_critical", "critical"
    if d < RULES["days_stock_warning"]:
        return "stock_warning", "medium"
    return "none", "none"


def apply_supplier_rules(row: pd.Series) -> tuple[str, str]:
    r = row["reliability_score"]
    if r < RULES["reliability_critical"]:
        return "reliability_critical", "high"
    if r < RULES["reliability_warning"]:
        return "reliability_warning", "medium"
    return "none", "none"


# ─────────────────────────────────────────────
# COMPOSITE RISK SCORER
# ─────────────────────────────────────────────

def composite_risk_score(
    if_score: float,
    rule_severity: str,
    is_critical_component: bool,
    external_boost: float = 0.0,
) -> float:
    """
    Combine IF score (continuous) with rule severity (discrete)
    into a 0–100 risk score.
    """
    # Normalise IF score: typical range is [-0.7, 0.1]
    # Map to 0–100 (more negative = higher risk)
    if_normalized = np.clip((-if_score - 0.05) / 0.65, 0, 1) * 60  # max 60 pts from IF

    rule_pts = SEVERITY_SCORE.get(rule_severity, 0) * 0.4  # max 36 pts from rules

    criticality_bonus = 10 if is_critical_component else 0

    base = if_normalized + rule_pts + criticality_bonus + external_boost
    return min(100.0, round(base, 1))


# ─────────────────────────────────────────────
# RECOMMENDED ACTIONS
# ─────────────────────────────────────────────

ACTION_MAP = {
    ("shipment_delay",    "critical"): "🔴 Switch to backup supplier immediately. Expedite air freight.",
    ("shipment_delay",    "high"):     "🟠 Alert procurement. Evaluate alternate supplier lead times.",
    ("shipment_delay",    "medium"):   "🟡 Monitor closely. Pre-position safety stock if available.",
    ("inventory_drop",    "critical"): "🔴 Halt non-essential production lines. Emergency reorder now.",
    ("inventory_drop",    "medium"):   "🟡 Accelerate pending shipments. Reduce batch sizes temporarily.",
    ("supplier_degraded", "high"):     "🟠 Dual-source immediately. Run supplier audit within 48 hours.",
    ("supplier_degraded", "medium"):   "🟡 Request root-cause from supplier. Increase monitoring frequency.",
}

def get_action(alert_type: str, severity: str) -> str:
    key = (alert_type, severity)
    return ACTION_MAP.get(key, "🟢 Log and monitor. No immediate action required.")


# ─────────────────────────────────────────────
# MAIN DETECTION PIPELINE
# ─────────────────────────────────────────────

def detect_shipment_anomalies(
    tables: dict,
    external_boosts: dict[str, float],
    xgb_clf=None,
) -> list[AnomalyAlert]:
    df_raw = tables["shipments"]
    feat = build_shipment_features(df_raw)

    X = feat[["actual_delay_days", "delay_ratio", "is_critical", "origin_risk", "cost_zscore"]].values

    labels, scores = run_isolation_forest(X)

    # Optional XGBoost probabilities (0–1) → small additive boost to risk score
    xgb_probs = None
    if xgb_clf is not None:
        try:
            xgb_probs = xgb_clf.predict_proba(X)[:, 1]
        except Exception:
            xgb_probs = None

    alerts = []
    for i, (_, row) in enumerate(feat.iterrows()):
        rule, rule_sev = apply_shipment_rules(row)
        is_anomaly = labels[i] == -1
        if not is_anomaly and rule == "none":
            continue   # not flagged by either → skip

        severity = rule_sev if rule_sev != "none" else ("high" if scores[i] < -0.3 else "medium")
        ext_boost = external_boosts.get(row["component"], 0.0)

        xgb_boost = 0.0
        if xgb_probs is not None:
            # Boost between 0 and +20 pts when model is confident of disruption
            p = float(xgb_probs[i])
            xgb_boost = max(0.0, min(20.0, (p - 0.5) * 40.0))

        risk = composite_risk_score(
            scores[i],
            severity,
            bool(row["is_critical"]),
            external_boost=ext_boost + xgb_boost,
        )
        if risk < 20:
            continue   # filter noise

        alerts.append(AnomalyAlert(
            detected_at=datetime.now().isoformat(),
            component=row["component"],
            alert_type="shipment_delay",
            severity=severity,
            risk_score=risk,
            description=(
                f"Shipment {row['shipment_id']} from {row['supplier_name']}: "
                f"{row['actual_delay_days']}d delay (status: {row['status']})"
            ),
            supplier_id=row["supplier_id"],
            shipment_id=row["shipment_id"],
            isolation_score=round(float(scores[i]), 4),
            rule_triggered=rule,
            recommended_action=get_action("shipment_delay", severity),
        ))

    return alerts


def detect_inventory_anomalies(
    tables: dict,
    external_boosts: dict[str, float],
) -> list[AnomalyAlert]:
    df_raw = tables["inventory"]
    feat = build_inventory_features(df_raw)

    # Use latest snapshot per component only (most recent tick)
    latest = feat.sort_values("days_of_stock").groupby(
        feat.index // (len(feat) // 5)   # approximate: latest per component
    ).last().reset_index(drop=True)

    # Run IF on all records to learn patterns
    X_all = feat[["days_of_stock", "stock_ratio", "drawdown", "drawdown_zscore"]].values
    labels_all, scores_all = run_isolation_forest(X_all, contamination=0.10)

    alerts = []
    for i, (_, row) in enumerate(feat.iterrows()):
        rule, rule_sev = apply_inventory_rules(row)
        is_anomaly = labels_all[i] == -1
        if not is_anomaly and rule == "none":
            continue

        severity = (
            rule_sev
            if rule_sev != "none"
            else ("high" if scores_all[i] < -0.35 else "medium")
        )
        is_critical = row["component"] in ["semiconductor", "steel_sheets", "wiring_harness"]
        ext_boost = external_boosts.get(row["component"], 0.0)
        risk = composite_risk_score(
            scores_all[i],
            severity,
            is_critical,
            external_boost=ext_boost,
        )
        if risk < 25:
            continue

        alerts.append(AnomalyAlert(
            detected_at=datetime.now().isoformat(),
            component=row["component"],
            alert_type="inventory_drop",
            severity=severity,
            risk_score=risk,
            description=(
                f"{row['component']}: {row['days_of_stock']:.1f} days of stock "
                f"(safety threshold: {row['safety_stock_days']} days)"
            ),
            supplier_id=None,
            shipment_id=None,
            isolation_score=round(float(scores_all[i]), 4),
            rule_triggered=rule,
            recommended_action=get_action("inventory_drop", severity),
        ))

    # Deduplicate — keep worst record per component
    if alerts:
        df_a = pd.DataFrame([asdict(a) for a in alerts])
        df_a = df_a.loc[df_a.groupby("component")["risk_score"].idxmax()]
        alerts = [AnomalyAlert(**row) for _, row in df_a.iterrows()]

    return alerts


def detect_supplier_anomalies(
    tables: dict,
    external_boosts: dict[str, float],
) -> list[AnomalyAlert]:
    df_raw = tables["supplier_health"]
    feat = build_supplier_features(df_raw)

    X = feat[["reliability_score", "avg_delay_days", "rel_drop", "delay_trend"]].values
    labels, scores = run_isolation_forest(X, contamination=0.07)

    alerts = []
    for i, (_, row) in enumerate(feat.iterrows()):
        rule, rule_sev = apply_supplier_rules(row)
        is_anomaly = labels[i] == -1
        if not is_anomaly and rule == "none":
            continue

        severity = rule_sev if rule_sev != "none" else "medium"
        is_critical = row["component"] in ["semiconductor", "steel_sheets", "wiring_harness"]
        ext_boost = external_boosts.get(row["component"], 0.0)
        risk = composite_risk_score(
            scores[i],
            severity,
            is_critical,
            external_boost=ext_boost,
        )
        if risk < 30:
            continue

        alerts.append(AnomalyAlert(
            detected_at=datetime.now().isoformat(),
            component=row["component"],
            alert_type="supplier_degraded",
            severity=severity,
            risk_score=risk,
            description=(
                f"{row['supplier_name']} reliability dropped to "
                f"{row['reliability_score']:.0%} "
                f"(avg delay: {row['avg_delay_days']:.1f}d, status: {row['health_status']})"
            ),
            supplier_id=row["supplier_id"],
            shipment_id=None,
            isolation_score=round(float(scores[i]), 4),
            rule_triggered=rule,
            recommended_action=get_action("supplier_degraded", severity),
        ))

    # Deduplicate per supplier
    if alerts:
        df_a = pd.DataFrame([asdict(a) for a in alerts])
        df_a = df_a.loc[df_a.groupby("supplier_id")["risk_score"].idxmax()]
        alerts = [AnomalyAlert(**row) for _, row in df_a.iterrows()]

    return alerts


# ─────────────────────────────────────────────
# SAVE RESULTS
# ─────────────────────────────────────────────

def save_alerts(alerts: list[AnomalyAlert], db_path: str):
    if not alerts:
        return
    conn = sqlite3.connect(db_path)
    conn.execute("DROP TABLE IF EXISTS anomaly_alerts")
    conn.execute(
        """
        CREATE TABLE anomaly_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            detected_at TEXT,
            component TEXT,
            alert_type TEXT,
            severity TEXT,
            risk_score REAL,
            description TEXT,
            supplier_id TEXT,
            shipment_id TEXT,
            isolation_score REAL,
            rule_triggered TEXT,
            recommended_action TEXT,
            alert_status TEXT,
            closed_at TEXT
        )
        """
    )
    cur = conn.cursor()
    for a in alerts:
        d = asdict(a)
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        cur.execute(
            f"INSERT INTO anomaly_alerts ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        alert_id = cur.lastrowid
        append_blockchain_log(
            conn,
            event_type="ALERT_CREATED",
            ref_table="anomaly_alerts",
            ref_id=str(alert_id),
            payload=d,
        )
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────
# SUPPLY CHAIN MAP (Suppliers → Warehouses → Factory)
# ─────────────────────────────────────────────

def build_supply_chain_map(db_path: str = DB_PATH,
                           output_html: str = "supply_chain_map.html"):
    """
    Builds a geographic map of the network:
        Suppliers → Warehouses → Factory

    The map is saved as an interactive HTML file that judges can open
    in any browser.
    """
    conn = sqlite3.connect(db_path)
    try:
        shipments = pd.read_sql(
            "SELECT DISTINCT supplier_id, supplier_name, origin_country "
            "FROM shipments",
            conn,
        )
    except Exception as e:
        print(f"[Map] Unable to read shipments table: {e}")
        conn.close()
        return
    finally:
        conn.close()

    if shipments.empty:
        print("[Map] No shipment data available to build map.")
        return

    # Derive supplier node locations from origin_country
    supplier_nodes = []
    for _, row in shipments.iterrows():
        country = row.get("origin_country")
        coords = COUNTRY_COORDS.get(country)
        if not coords:
            continue
        lat, lon = coords
        supplier_nodes.append({
            "id": row["supplier_id"],
            "name": row["supplier_name"],
            "country": country,
            "lat": lat,
            "lon": lon,
        })

    if not supplier_nodes:
        print("[Map] No suppliers with known coordinates; map skipped.")
        return

    # Assign each supplier to a warehouse in a round-robin fashion
    wh_keys = list(WAREHOUSES.keys())
    edges_supplier_warehouse = []
    for idx, s in enumerate(supplier_nodes):
        wh_key = wh_keys[idx % len(wh_keys)]
        wh = WAREHOUSES[wh_key]
        edges_supplier_warehouse.append({
            "from_lat": s["lat"],
            "from_lon": s["lon"],
            "to_lat": wh["lat"],
            "to_lon": wh["lon"],
            "from_label": f"Supplier: {s['name']} ({s['country']})",
            "to_label": f"Warehouse: {wh_key} ({wh['city']})",
        })

    # Warehouse → Factory edges
    edges_warehouse_factory = []
    for key, wh in WAREHOUSES.items():
        edges_warehouse_factory.append({
            "from_lat": wh["lat"],
            "from_lon": wh["lon"],
            "to_lat": FACTORY["lat"],
            "to_lon": FACTORY["lon"],
            "from_label": f"Warehouse: {key} ({wh['city']})",
            "to_label": FACTORY["name"],
        })

    fig = go.Figure()

    # Supplier nodes
    fig.add_trace(go.Scattergeo(
        lat=[s["lat"] for s in supplier_nodes],
        lon=[s["lon"] for s in supplier_nodes],
        mode="markers",
        marker=dict(size=7, color="red"),
        name="Suppliers",
        text=[f"{s['name']} ({s['country']})" for s in supplier_nodes],
        hoverinfo="text",
    ))

    # Warehouse nodes
    fig.add_trace(go.Scattergeo(
        lat=[w["lat"] for w in WAREHOUSES.values()],
        lon=[w["lon"] for w in WAREHOUSES.values()],
        mode="markers",
        marker=dict(size=9, color="orange", symbol="square"),
        name="Warehouses",
        text=[f"{k} ({w['city']})" for k, w in WAREHOUSES.items()],
        hoverinfo="text",
    ))

    # Factory node
    fig.add_trace(go.Scattergeo(
        lat=[FACTORY["lat"]],
        lon=[FACTORY["lon"]],
        mode="markers",
        marker=dict(size=11, color="green", symbol="star"),
        name="Factory",
        text=[FACTORY["name"]],
        hoverinfo="text",
    ))

    # Supplier → Warehouse edges
    for e in edges_supplier_warehouse:
        fig.add_trace(go.Scattergeo(
            lat=[e["from_lat"], e["to_lat"]],
            lon=[e["from_lon"], e["to_lon"]],
            mode="lines",
            line=dict(width=1, color="rgba(255,0,0,0.6)"),
            hoverinfo="text",
            text=[f"{e['from_label']} → {e['to_label']}"],
            showlegend=False,
        ))

    # Warehouse → Factory edges
    for e in edges_warehouse_factory:
        fig.add_trace(go.Scattergeo(
            lat=[e["from_lat"], e["to_lat"]],
            lon=[e["from_lon"], e["to_lon"]],
            mode="lines",
            line=dict(width=1, color="rgba(0,128,0,0.6)"),
            hoverinfo="text",
            text=[f"{e['from_label']} → {e['to_label']}"],
            showlegend=False,
        ))

    fig.update_layout(
        title="Supply Chain Map — Suppliers → Warehouses → Factory",
        geo=dict(
            projection_type="natural earth",
            showcountries=True,
            showland=True,
            landcolor="rgb(243, 243, 243)",
            coastlinecolor="rgb(204, 204, 204)",
        ),
        margin=dict(l=0, r=0, t=50, b=0),
    )

    fig.write_html(output_html, auto_open=False)
    print(f"[Map] Supply chain map written to {output_html}")


# ─────────────────────────────────────────────
# PHASE 5: AUTONOMOUS SELF-HEALING LOOP
# ─────────────────────────────────────────────

def _decide_recovery_plan(alert_row: dict) -> tuple[str, str]:
    """
    Decide how to react to an alert.

    Returns (action_summary, shipment_status_update)
    shipment_status_update may be an empty string if no shipment update is needed.
    """
    a_type = alert_row.get("alert_type")
    sev = alert_row.get("severity")

    if a_type == "shipment_delay":
        if sev == "critical":
            return (
                "Expedite via air freight and switch to backup supplier.",
                "expedite_air",
            )
        if sev == "high":
            return (
                "Expedite shipment and reroute via faster lane.",
                "expedite",
            )
        return (
            "Monitor delay and slightly accelerate downstream production.",
            "monitor_delay",
        )

    if a_type == "inventory_drop":
        if sev == "critical":
            return (
                "Trigger emergency reorder and pause non-critical production lines.",
                "",
            )
        return (
            "Accelerate pending shipments and tighten inventory releases.",
            "",
        )

    if a_type == "supplier_degraded":
        if sev in ("high", "critical"):
            return (
                "Activate dual-sourcing and launch supplier audit.",
                "",
            )
        return (
            "Increase monitoring and request corrective action plan from supplier.",
            "",
        )

    return ("Log and monitor – no automated recovery needed.", "")


def run_self_healing_loop(db_path: str = DB_PATH):
    """
    Phase 5 autonomous loop:

        Detects alert → Decides action → Executes recovery
        → Updates shipment / records → Closes alert.
    """
    print("\n── Phase 5: Autonomous Self-Healing Loop ──")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # Recovery action log
    cur.execute("DROP TABLE IF EXISTS recovery_actions")
    cur.execute(
        """
        CREATE TABLE recovery_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_id INTEGER,
            alert_type TEXT,
            severity TEXT,
            supplier_id TEXT,
            shipment_id TEXT,
            decided_at TEXT,
            executed_at TEXT,
            status TEXT,
            action_summary TEXT
        )
        """
    )

    # Load open alerts that have auto-approved decisions
    alerts_df = pd.read_sql(
        """
        SELECT aa.* FROM anomaly_alerts aa
        JOIN decisions d ON aa.id = d.alert_id
        WHERE (aa.alert_status IS NULL OR aa.alert_status != 'closed')
        AND d.auto_execute = 1
        """,
        conn,
    )

    if alerts_df.empty:
        print("  ✅ No open alerts to heal.")
        conn.close()
        return

    now = datetime.now().isoformat()
    healed = 0

    for _, row in alerts_df.iterrows():
        alert_id = int(row["id"])
        alert_dict = row.to_dict()
        action_summary, shipment_status = _decide_recovery_plan(alert_dict)

        # Execute recovery on shipments when applicable
        executed_status = "logged"
        if shipment_status and pd.notna(row.get("shipment_id")):
            try:
                cur.execute(
                    "UPDATE shipments SET status = ? WHERE shipment_id = ?",
                    (shipment_status, row["shipment_id"]),
                )
                executed_status = f"shipment_updated:{shipment_status}"
            except Exception as e:
                executed_status = f"shipment_update_failed:{e}"

        # Log recovery action
        cur.execute(
            """
            INSERT INTO recovery_actions (
                alert_id, alert_type, severity,
                supplier_id, shipment_id,
                decided_at, executed_at, status, action_summary
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert_id,
                row["alert_type"],
                row["severity"],
                row.get("supplier_id"),
                row.get("shipment_id"),
                now,
                now,
                executed_status,
                action_summary,
            ),
        )
        recovery_id = cur.lastrowid
        append_blockchain_log(
            conn,
            event_type="RECOVERY_ACTION_EXECUTED",
            ref_table="recovery_actions",
            ref_id=str(recovery_id),
            payload={
                "alert_id": alert_id,
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "supplier_id": row.get("supplier_id"),
                "shipment_id": row.get("shipment_id"),
                "status": executed_status,
                "action_summary": action_summary,
            },
        )

        # Close the alert
        cur.execute(
            "UPDATE anomaly_alerts "
            "SET alert_status = 'closed', closed_at = ? "
            "WHERE id = ?",
            (now, alert_id),
        )
        append_blockchain_log(
            conn,
            event_type="ALERT_CLOSED",
            ref_table="anomaly_alerts",
            ref_id=str(alert_id),
            payload={
                "closed_at": now,
                "alert_type": row["alert_type"],
                "severity": row["severity"],
                "status": "closed",
            },
        )

        healed += 1
        print(
            f"  🔁 Closed alert #{alert_id} "
            f"({row['alert_type']}, {row['severity']}) → {executed_status}"
        )

    conn.commit()
    conn.close()
    print(f"  ✅ Self-healing completed for {healed} alerts.")


# ─────────────────────────────────────────────
# PRETTY PRINT
# ─────────────────────────────────────────────

def print_alerts(alerts: list[AnomalyAlert]):
    if not alerts:
        print("  ✅ No anomalies detected.")
        return

    sorted_alerts = sorted(alerts, key=lambda a: a.risk_score, reverse=True)
    for a in sorted_alerts:
        bar = "█" * int(a.risk_score / 10) + "░" * (10 - int(a.risk_score / 10))
        print(f"\n  [{a.severity.upper():8s}] Risk {a.risk_score:5.1f}/100  {bar}")
        print(f"  Component  : {a.component}")
        print(f"  Type       : {a.alert_type}")
        print(f"  Detail     : {a.description}")
        print(f"  IF Score   : {a.isolation_score}  |  Rule: {a.rule_triggered}")
        print(f"  Action     : {a.recommended_action}")


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

def run_detection(db_path: str = DB_PATH) -> list[AnomalyAlert]:
    print(f"\n{'='*60}")
    print(" SUPPLY CHAIN ANOMALY DETECTOR")
    print(f"{'='*60}")

    tables = load_data(db_path)
    external_boosts = build_external_risk_boost(tables.get("external_signals", pd.DataFrame()))
    all_alerts = []

    # Optional: train XGBoost classifier on shipments if available
    xgb_clf = None
    try:
        shp_feat = build_shipment_features(tables["shipments"])
        xgb_clf = train_shipment_xgb_classifier(shp_feat)
    except Exception as e:
        print(f"[Detector] Shipment XGBoost preparation failed: {e}")

    print("\n── Shipment Delay Detection ──")
    shp = detect_shipment_anomalies(tables, external_boosts, xgb_clf=xgb_clf)
    print(f"  Flagged: {len(shp)} shipments")
    all_alerts.extend(shp)

    print("\n── Inventory Level Detection ──")
    inv = detect_inventory_anomalies(tables, external_boosts)
    print(f"  Flagged: {len(inv)} components")
    all_alerts.extend(inv)

    print("\n── Supplier Health Detection ──")
    sup = detect_supplier_anomalies(tables, external_boosts)
    print(f"  Flagged: {len(sup)} suppliers")
    all_alerts.extend(sup)

    # Sort all by risk score descending
    all_alerts.sort(key=lambda a: a.risk_score, reverse=True)

    print(f"\n── TOP ALERTS ({len(all_alerts)} total) ──")
    print_alerts(all_alerts[:10])  # top 10

    save_alerts(all_alerts, db_path)
    print(f"\n[Detector] {len(all_alerts)} alerts saved to anomaly_alerts table.")

    # Build interactive supply chain map for judges
    try:
        build_supply_chain_map(db_path=db_path)
    except Exception as e:
        print(f"[Detector] Map generation failed: {e}")

    # Phase 5: run autonomous self-healing loop
    # try:
    #     run_self_healing_loop(db_path=db_path)
    # except Exception as e:
    #     print(f"[Detector] Self-healing loop failed: {e}")

    return all_alerts


if __name__ == "__main__":
    import os
    db = os.path.join(os.path.dirname(__file__), "supplychain.db")
    run_detection(db_path=db)
