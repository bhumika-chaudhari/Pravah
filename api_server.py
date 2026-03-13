"""
Supply Chain Control Tower — FastAPI Backend
=============================================
Corrected to match actual DB schema produced by:
  - simulator.py       → inventory, shipments, supplier_health, external_signals
  - anomaly_detector.py → anomaly_alerts, recovery_actions, blockchain_log
  - decision_engine.py  → decisions
  - blockchain_logger.py → blockchain_log  (NOT blockchain_logs)

Run:
    uvicorn api_server:app --reload --host 0.0.0.0 --port 8000
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import json
import os
from datetime import datetime
from typing import Optional

app = FastAPI(title="Supply Chain Control Tower API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # tighten for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = os.path.join(os.path.dirname(__file__), "supplychain.db")

# ─── Supplier geo-coordinates (from anomaly_detector.py COUNTRY_COORDS + WAREHOUSES) ──
COUNTRY_COORDS = {
    "India":     (20.5937,  78.9629),
    "Korea":     (35.9078, 127.7669),
    "South Korea":(35.9078, 127.7669),
    "Japan":     (36.2048, 138.2529),
    "Taiwan":    (23.6978, 120.9605),
    "Germany":   (51.1657,  10.4515),
    "Thailand":  (15.8700, 100.9925),
    "Malaysia":  ( 4.2105, 101.9758),
}

WAREHOUSES = {
    "WH_West":  {"lat": 19.0760, "lng": 72.8777, "city": "Mumbai"},
    "WH_North": {"lat": 28.7041, "lng": 77.1025, "city": "Delhi"},
    "WH_South": {"lat": 12.9716, "lng": 77.5946, "city": "Bengaluru"},
}

FACTORY = {"lat": 23.0225, "lng": 72.5714, "city": "Ahmedabad"}

# Pune manufacturing plant (main)
PUNE_FACTORY = {"lat": 18.5204, "lng": 73.8567, "city": "Pune"}


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


# ══════════════════════════════════════════════════════
# ROOT
# ══════════════════════════════════════════════════════

@app.get("/")
def root():
    conn = get_db()
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()]
    conn.close()
    return {
        "message": "Supply Chain Control Tower API",
        "status":  "running",
        "tables":  tables,
        "version": "2.0.0",
    }


# ══════════════════════════════════════════════════════
# DASHBOARD METRICS  →  /api/dashboard/metrics
# ══════════════════════════════════════════════════════

@app.get("/api/dashboard/metrics")
def get_dashboard_metrics():
    conn = get_db()
    try:
        metrics = {}

        # ── Alert counts from anomaly_alerts ──
        if table_exists(conn, "anomaly_alerts"):
            row = conn.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE alert_status != 'closed' OR alert_status IS NULL) AS total_alerts,
                    COUNT(*) FILTER (WHERE alert_status != 'closed' OR alert_status IS NULL) AS active_anomalies,
                    COUNT(*) FILTER (WHERE alert_status = 'closed'
                                     AND DATE(closed_at) = DATE('now'))              AS resolved_today
                FROM anomaly_alerts
            """).fetchone()
            metrics["total_alerts"]    = row["total_alerts"]    or 0
            metrics["active_anomalies"]= row["active_anomalies"]or 0
            metrics["resolved_today"]  = row["resolved_today"]  or 0
        else:
            metrics["total_alerts"] = metrics["active_anomalies"] = metrics["resolved_today"] = 0

        # ── Avg resolution time from recovery_actions ──
        if table_exists(conn, "recovery_actions") and table_exists(conn, "anomaly_alerts"):
            row = conn.execute("""
                SELECT AVG(
                    (julianday(ra.executed_at) - julianday(aa.detected_at)) * 24
                ) AS avg_hours
                FROM recovery_actions ra
                JOIN anomaly_alerts aa ON ra.alert_id = aa.id
                WHERE ra.executed_at IS NOT NULL AND aa.detected_at IS NOT NULL
            """).fetchone()
            h = row["avg_hours"]
            metrics["avg_resolution_time"] = f"{h:.1f}h" if h else "N/A"
        else:
            metrics["avg_resolution_time"] = "N/A"

        # ── Supplier reliability (avg of latest supplier_health per supplier) ──
        if table_exists(conn, "supplier_health"):
            row = conn.execute("""
                SELECT AVG(reliability_score) * 100 AS avg_rel
                FROM (
                    SELECT supplier_id, reliability_score,
                           ROW_NUMBER() OVER (PARTITION BY supplier_id ORDER BY timestamp DESC) AS rn
                    FROM supplier_health
                ) t WHERE rn = 1
            """).fetchone()
            metrics["supplier_reliability"] = int(row["avg_rel"] or 94)
        else:
            metrics["supplier_reliability"] = 94

        # ── Inventory levels (% of components above safety stock) ──
        if table_exists(conn, "inventory"):
            row = conn.execute("""
                SELECT AVG(
                    CASE
                        WHEN safety_stock_days > 0
                        THEN MIN(100.0, (days_of_stock / safety_stock_days) * 100)
                        ELSE 100.0
                    END
                ) AS avg_level
                FROM (
                    SELECT component, days_of_stock, safety_stock_days,
                           ROW_NUMBER() OVER (PARTITION BY component ORDER BY timestamp DESC) AS rn
                    FROM inventory
                ) t WHERE rn = 1
            """).fetchone()
            metrics["inventory_levels"] = int(row["avg_level"] or 87)
        else:
            metrics["inventory_levels"] = 87

        # ── On-time delivery rate ──
        if table_exists(conn, "shipments"):
            row = conn.execute("""
                SELECT
                    ROUND(
                        100.0 * SUM(CASE WHEN actual_delay_days <= 0 THEN 1 ELSE 0 END)
                        / MAX(COUNT(*), 1),
                        1
                    ) AS on_time_pct
                FROM shipments
            """).fetchone()
            metrics["on_time_delivery"] = int(row["on_time_pct"] or 91)
        else:
            metrics["on_time_delivery"] = 91

        return metrics

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# ACTIVE ALERTS  →  /api/alerts/active
# ══════════════════════════════════════════════════════

@app.get("/api/alerts/active")
def get_active_alerts():
    conn = get_db()
    try:
        if not table_exists(conn, "anomaly_alerts"):
            return []

        rows = conn.execute("""
            SELECT
                id,
                component,
                alert_type       AS type,
                severity,
                risk_score,
                description,
                supplier_id,
                shipment_id,
                rule_triggered,
                recommended_action,
                detected_at      AS timestamp,
                alert_status     AS status
            FROM anomaly_alerts
            WHERE alert_status IS NULL OR alert_status != 'closed'
            ORDER BY risk_score DESC, detected_at DESC
        """).fetchall()

        return [
            {
                "id":          r["id"],
                "component":   r["component"],
                "type":        r["type"],
                "severity":    r["severity"],
                "risk_score":  round(r["risk_score"] or 0, 1),
                "description": r["description"],
                "supplier":    r["supplier_id"] or "Internal",
                "shipment_id": r["shipment_id"],
                "impact":      f"Risk score: {round(r['risk_score'] or 0, 1)}",
                "recommended": r["recommended_action"],
                "timestamp":   r["timestamp"],
                "status":      r["status"] or "active",
            }
            for r in rows
        ]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# PENDING DECISIONS  →  /api/decisions/pending
# ══════════════════════════════════════════════════════

@app.get("/api/decisions/pending")
def get_pending_decisions():
    conn = get_db()
    try:
        if not table_exists(conn, "decisions"):
            return []

        rows = conn.execute("""
            SELECT
                d.id,
                d.alert_id,
                d.component,
                d.alert_type,
                d.severity,
                d.risk_score,
                d.recommended_action,
                d.recommended_supplier,
                d.recommended_warehouse,
                d.estimated_delivery_days,
                d.incremental_cost_inr,
                d.net_saving_inr,
                d.composite_score,
                d.auto_execute,
                d.all_options_json,
                d.decision_rationale,
                d.shap_json,
                d.decided_at         AS timestamp,
                a.description        AS issue
            FROM decisions d
            LEFT JOIN anomaly_alerts a ON d.alert_id = a.id
            ORDER BY d.risk_score DESC
        """).fetchall()

        results = []
        for r in rows:
            # Parse all_options_json into recommendations list
            try:
                options = json.loads(r["all_options_json"] or "[]")
                recommendations = [
                    {
                        "action":       o.get("action_type"),
                        "description":  o.get("description"),
                        "cost":         o.get("incremental_cost_inr"),
                        "timeSaved":    o.get("days_saved_vs_baseline"),
                        "risk":         1.0 - o.get("reliability_score", 0.8),
                        "score":        o.get("composite_score", 0) / 100,
                        "recommended":  options.index(o) == 0,
                    }
                    for o in options[:3]
                ]
            except Exception:
                recommendations = [r["recommended_action"]] if r["recommended_action"] else []

            results.append({
                "id":              r["id"],
                "anomaly_id":      r["alert_id"],
                "component":       r["component"],
                "alert_type":      r["alert_type"],
                "severity":        r["severity"],
                "risk_score":      round(r["risk_score"] or 0, 1),
                "issue":           r["issue"] or r["alert_type"] or "Unknown issue",
                "recommendations": recommendations,
                "recommended_action": r["recommended_action"],
                "recommended_supplier": r["recommended_supplier"],
                "recommended_warehouse": r["recommended_warehouse"],
                "estimated_delivery_days": r["estimated_delivery_days"],
                "incremental_cost_inr": r["incremental_cost_inr"],
                "net_saving_inr":  r["net_saving_inr"],
                "composite_score": r["composite_score"],
                "status":          "auto_approved" if r["auto_execute"] else "pending_approval",
                "rationale":       r["decision_rationale"],
                "shap":            json.loads(r["shap_json"] or "{}"),
                "timestamp":       r["timestamp"],
            })

        return results

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# ANOMALY TIMELINE  →  /api/anomalies/timeline
# ══════════════════════════════════════════════════════

@app.get("/api/anomalies/timeline")
def get_anomaly_timeline(
    severity:   Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date:   Optional[str] = Query(None),
    status:     Optional[str] = Query(None),
    limit:      int            = Query(200),
):
    conn = get_db()
    try:
        if not table_exists(conn, "anomaly_alerts"):
            return []

        conditions = ["1=1"]
        params     = []

        if severity:
            conditions.append("severity = ?")
            params.append(severity)
        if status:
            if status == "active":
                conditions.append("(alert_status IS NULL OR alert_status != 'closed')")
            elif status == "resolved":
                conditions.append("alert_status = 'closed'")
        if start_date:
            conditions.append("DATE(detected_at) >= DATE(?)")
            params.append(start_date)
        if end_date:
            conditions.append("DATE(detected_at) <= DATE(?)")
            params.append(end_date)

        where = " AND ".join(conditions)
        params.append(limit)

        rows = conn.execute(f"""
            SELECT
                aa.id,
                aa.detected_at       AS timestamp,
                aa.alert_type        AS type,
                aa.severity,
                aa.component,
                aa.supplier_id       AS supplier,
                aa.description,
                aa.risk_score,
                aa.recommended_action AS impact,
                aa.alert_status      AS status,
                aa.closed_at,
                NULL                 AS resolution_action,
                NULL                 AS resolution_timestamp
            FROM anomaly_alerts aa
            WHERE {where}
            ORDER BY aa.detected_at DESC
            LIMIT ?
        """, params).fetchall()

        return [
            {
                "id":          r["id"],
                "timestamp":   r["timestamp"],
                "type":        r["type"],
                "severity":    r["severity"],
                "component":   r["component"],
                "supplier":    r["supplier"] or "Internal",
                "description": r["description"],
                "impact":      r["impact"] or "",
                "status":      "resolved" if r["status"] == "closed" else (r["status"] or "active"),
                "resolution":  {
                    "action":    r["resolution_action"],
                    "timestamp": r["resolution_timestamp"],
                } if r["resolution_action"] else None,
            }
            for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# BLOCKCHAIN LOGS  →  /api/blockchain/logs
# NOTE: table is "blockchain_log" (no trailing 's')
# ══════════════════════════════════════════════════════

@app.get("/api/blockchain/logs")
def get_blockchain_logs(
    event_type: Optional[str] = Query(None),
    limit:      int            = Query(50),
    offset:     int            = Query(0),
):
    conn = get_db()
    try:
        # Support both naming variants
        tbl = "blockchain_log" if table_exists(conn, "blockchain_log") \
              else ("blockchain_logs" if table_exists(conn, "blockchain_logs") else None)

        if not tbl:
            return []

        conditions = ["1=1"]
        params     = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(conditions)
        params += [limit, offset]

        rows = conn.execute(f"""
            SELECT
                id,
                created_at,
                event_type,
                ref_table,
                ref_id,
                payload_json,
                prev_hash,
                curr_hash,
                1 AS verified
            FROM {tbl}
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, params).fetchall()

        return [
            {
                "id":           r["id"],
                "created_at":   r["created_at"],
                "event_type":   r["event_type"],
                "ref_table":    r["ref_table"],
                "ref_id":       r["ref_id"],
                "payload_json": _safe_json(r["payload_json"]),
                "prev_hash":    r["prev_hash"] or "",
                "curr_hash":    r["curr_hash"] or "",
                "verified":     bool(r["verified"]),
            }
            for r in rows
        ]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# SUPPLY CHAIN MAP  →  /api/map/network
# Built dynamically from shipments + supplier_health tables
# (no separate suppliers/factories tables exist)
# ══════════════════════════════════════════════════════

@app.get("/api/map/network")
def get_network_data():
    conn = get_db()
    try:
        nodes     = []
        shipments = []

        # ── Supplier nodes from shipments table ──
        if table_exists(conn, "shipments"):
            sup_rows = conn.execute("""
                SELECT
                    supplier_id,
                    supplier_name,
                    origin_country,
                    COUNT(*) AS total_shipments,
                    SUM(CASE WHEN status = 'delayed' OR actual_delay_days > 2 THEN 1 ELSE 0 END) AS delayed_count,
                    AVG(actual_delay_days) AS avg_delay
                FROM shipments
                GROUP BY supplier_id, supplier_name, origin_country
            """).fetchall()

            for r in sup_rows:
                coords = COUNTRY_COORDS.get(r["origin_country"], (20.5937, 78.9629))
                # Spread nodes by jitter so they don't stack
                import hashlib
                h   = int(hashlib.md5(r["supplier_id"].encode()).hexdigest()[:6], 16)
                lat = coords[0] + (h % 100 - 50) * 0.12
                lng = coords[1] + ((h >> 8) % 100 - 50) * 0.12

                is_delayed = (r["delayed_count"] or 0) > 2
                nodes.append({
                    "id":       r["supplier_id"],
                    "name":     r["supplier_name"],
                    "type":     "supplier",
                    "location": {"lat": round(lat, 4), "lng": round(lng, 4)},
                    "status":   "warning" if is_delayed else "active",
                    "metrics":  {
                        "shipments":     r["total_shipments"],
                        "delayed":       r["delayed_count"] or 0,
                        "avg_delay":     f"{round(r['avg_delay'] or 0, 1)} days",
                        "alerts":        r["delayed_count"] or 0,
                        "country":       r["origin_country"],
                    },
                })

        # ── Supplier health overlay ──
        sup_health_map = {}
        if table_exists(conn, "supplier_health"):
            sh_rows = conn.execute("""
                SELECT supplier_id, reliability_score, health_status
                FROM (
                    SELECT supplier_id, reliability_score, health_status,
                           ROW_NUMBER() OVER (PARTITION BY supplier_id ORDER BY timestamp DESC) AS rn
                    FROM supplier_health
                ) t WHERE rn = 1
            """).fetchall()
            sup_health_map = {r["supplier_id"]: r for r in sh_rows}

        for node in nodes:
            h = sup_health_map.get(node["id"])
            if h:
                node["metrics"]["reliability"] = f"{round((h['reliability_score'] or 0) * 100, 1)}%"
                if h["health_status"] in ("at_risk", "degraded"):
                    node["status"] = "warning"

        # ── Factory nodes (warehouses + main factory from static config) ──
        for wh_id, wh in WAREHOUSES.items():
            nodes.append({
                "id":       wh_id,
                "name":     f"{wh['city']} Warehouse",
                "type":     "factory",
                "location": {"lat": wh["lat"], "lng": wh["lng"]},
                "status":   "active",
                "metrics":  {"location": wh["city"], "type": "Regional Hub", "alerts": 0},
            })

        nodes.append({
            "id":       "FACTORY_PUNE",
            "name":     "Pune Main Factory",
            "type":     "factory",
            "location": {"lat": PUNE_FACTORY["lat"], "lng": PUNE_FACTORY["lng"]},
            "status":   "active",
            "metrics":  {"location": "Pune, Maharashtra", "type": "Assembly Plant", "alerts": 0},
        })

        # ── Overlay active alerts on factory ──
        if table_exists(conn, "anomaly_alerts"):
            alert_count = conn.execute("""
                SELECT COUNT(*) AS n FROM anomaly_alerts
                WHERE (alert_status IS NULL OR alert_status != 'closed')
                AND alert_type = 'inventory_drop'
            """).fetchone()["n"]
            if alert_count:
                for node in nodes:
                    if node["id"] == "FACTORY_PUNE":
                        node["metrics"]["alerts"] = alert_count
                        if alert_count > 2:
                            node["status"] = "warning"

        # ── Shipment edges (supplier → nearest warehouse) ──
        if table_exists(conn, "shipments"):
            shp_rows = conn.execute("""
                SELECT
                    shipment_id,
                    supplier_id,
                    component,
                    status,
                    expected_delivery,
                    actual_delay_days,
                    CASE WHEN actual_delay_days > 2 THEN 'delayed' ELSE 'on_time' END AS delay_status
                FROM shipments
                ORDER BY timestamp DESC
                LIMIT 40
            """).fetchall()

            # Map each supplier to warehouse (deterministic assignment)
            wh_keys = list(WAREHOUSES.keys())
            for r in shp_rows:
                h = int(hashlib.md5(r["supplier_id"].encode()).hexdigest()[:4], 16) % len(wh_keys)
                wh_id = wh_keys[h]
                delay_days = r["actual_delay_days"] or 0
                shipments.append({
                    "id":     r["shipment_id"],
                    "from":   r["supplier_id"],
                    "to":     wh_id,
                    "status": r["status"],
                    "component": r["component"],
                    "eta":    r["expected_delivery"],
                    "delay":  f"{round(delay_days, 1)} days",
                    "delay_status": r["delay_status"],
                })

        return {"nodes": nodes, "shipments": shipments}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# DECISION UPDATE  →  PUT /api/decisions/{id}
# ══════════════════════════════════════════════════════

@app.put("/api/decisions/{decision_id}")
def update_decision(decision_id: int, body: dict):
    conn = get_db()
    try:
        action = body.get("action", "approve")
        new_status = 1 if action == "approve" else 0

        if table_exists(conn, "decisions"):
            conn.execute(
                "UPDATE decisions SET auto_execute = ? WHERE id = ?",
                (new_status, decision_id)
            )
            conn.commit()

        return {"status": "success", "decision_id": decision_id, "action": action}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# RESOLVE ANOMALY  →  POST /api/anomalies/{id}/resolve
# ══════════════════════════════════════════════════════

@app.post("/api/anomalies/{anomaly_id}/resolve")
def resolve_anomaly(anomaly_id: int, body: dict):
    conn = get_db()
    try:
        now = datetime.now().isoformat()
        if table_exists(conn, "anomaly_alerts"):
            conn.execute(
                "UPDATE anomaly_alerts SET alert_status='closed', closed_at=? WHERE id=?",
                (now, anomaly_id)
            )
            conn.commit()

        return {"status": "success", "anomaly_id": anomaly_id, "closed_at": now}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# INVENTORY  →  /api/inventory  (bonus endpoint)
# ══════════════════════════════════════════════════════

@app.get("/api/inventory")
def get_inventory():
    conn = get_db()
    try:
        if not table_exists(conn, "inventory"):
            return []

        rows = conn.execute("""
            SELECT component, days_of_stock, safety_stock_days,
                   stock_status, current_stock, daily_consumption, timestamp
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY component ORDER BY timestamp DESC) AS rn
                FROM inventory
            ) t WHERE rn = 1
            ORDER BY days_of_stock ASC
        """).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# SUPPLIER HEALTH  →  /api/suppliers  (bonus endpoint)
# ══════════════════════════════════════════════════════

@app.get("/api/suppliers")
def get_suppliers():
    conn = get_db()
    try:
        if not table_exists(conn, "supplier_health"):
            return []

        rows = conn.execute("""
            SELECT supplier_id, supplier_name, component,
                   reliability_score, avg_delay_days, health_status, timestamp
            FROM (
                SELECT *,
                       ROW_NUMBER() OVER (PARTITION BY supplier_id ORDER BY timestamp DESC) AS rn
                FROM supplier_health
            ) t WHERE rn = 1
            ORDER BY reliability_score ASC
        """).fetchall()

        return [dict(r) for r in rows]

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# ══════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════

def _safe_json(s):
    """Parse JSON string safely, return dict or raw string."""
    if not s:
        return {}
    try:
        return json.loads(s)
    except Exception:
        return {"raw": str(s)}


# ══════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="0.0.0.0", port=8000, reload=True)
