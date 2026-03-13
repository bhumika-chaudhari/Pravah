import hashlib
import json
from datetime import datetime
from typing import Any, Dict, Optional


def _ensure_table(conn) -> None:
    """
    Create a simple append-only blockchain-style log table if it does not exist.

    Each record stores a hash chain over all previous entries to make
    tampering evident during audit.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS blockchain_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            event_type TEXT,
            ref_table TEXT,
            ref_id TEXT,
            payload_json TEXT,
            prev_hash TEXT,
            curr_hash TEXT
        )
        """
    )


def append_blockchain_log(
    conn,
    event_type: str,
    ref_table: str,
    ref_id: Optional[str],
    payload: Dict[str, Any],
) -> None:
    """
    Append an audit entry to the blockchain-style log.

    - conn: open sqlite3 connection (caller is responsible for committing)
    - event_type: high-level label, e.g. "ALERT_CREATED", "DECISION_SAVED"
    - ref_table/ref_id: point back to the source record
    - payload: arbitrary dict with contextual data
    """
    _ensure_table(conn)

    # Get previous hash in the chain (if any)
    cur = conn.cursor()
    cur.execute(
        "SELECT curr_hash FROM blockchain_log ORDER BY id DESC LIMIT 1"
    )
    row = cur.fetchone()
    prev_hash = row[0] if row else ""

    created_at = datetime.now().isoformat()
    payload_json = json.dumps(payload, sort_keys=True, default=str)

    # Build deterministic string to hash
    to_hash = f"{created_at}|{event_type}|{ref_table}|{ref_id}|{payload_json}|{prev_hash}"
    curr_hash = hashlib.sha256(to_hash.encode("utf-8")).hexdigest()

    cur.execute(
        """
        INSERT INTO blockchain_log (
            created_at, event_type, ref_table, ref_id,
            payload_json, prev_hash, curr_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (created_at, event_type, ref_table, str(ref_id) if ref_id is not None else None,
         payload_json, prev_hash, curr_hash),
    )

