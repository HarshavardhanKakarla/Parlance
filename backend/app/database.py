import json
import sqlite3
import threading
from datetime import datetime, timezone

from . import config

_lock = threading.Lock()

DEFAULT_POLICY = {
    "global": {
        "device_new_weight": 14,
        "device_history_bonus": 1.5,
        "retry_weight": 6,
        "typing_anomaly_weight": 6,
        "geo_mismatch_weight": 16,
        "time_anomaly_weight": 5,
        "blocked_history_weight": 9,
        "chargeback_weight": 18,
        "account_age_bonus_max": 12,
    },
    "segments": {},
    "thresholds": {
        "green": 75,
        "yellow": 40,
    },
}

# Deliberately too-strict starting policy for the "failure story" demo (spec
# section 9): retry_weight and device_new_weight are cranked up so that a
# batch of otherwise-clearly-legitimate transactions (someone fat-fingers a
# retry, or checks out on a device they haven't used in a while) incorrectly
# lands Yellow. The fix is then applied live via the conversational layer or
# the /api/policy/preset/reset endpoint.
RIGID_DEMO_POLICY = {
    "global": {
        "device_new_weight": 34,
        "device_history_bonus": 1.5,
        "retry_weight": 15,
        "typing_anomaly_weight": 6,
        "geo_mismatch_weight": 16,
        "time_anomaly_weight": 5,
        "blocked_history_weight": 9,
        "chargeback_weight": 18,
        "account_age_bonus_max": 12,
    },
    "segments": {},
    "thresholds": {
        "green": 75,
        "yellow": 40,
    },
}

MAGNITUDE_MULTIPLIERS = {
    "slight": 0.15,
    "moderate": 0.35,
    "strong": 0.65,
}


def _now():
    return datetime.now(timezone.utc).isoformat()


def get_conn():
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _lock:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                scenario TEXT,
                features_json TEXT,
                score REAL,
                band TEXT,
                contributions_json TEXT,
                explanation TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS policy (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                policy_json TEXT,
                updated_at TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                type TEXT,
                payload_json TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT,
                instruction TEXT,
                proposed_delta_json TEXT,
                confidence REAL,
                reason TEXT,
                status TEXT
            )
            """
        )
        cur.execute("SELECT id FROM policy WHERE id = 1")
        if cur.fetchone() is None:
            cur.execute(
                "INSERT INTO policy (id, policy_json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(DEFAULT_POLICY), _now()),
            )
        conn.commit()
        conn.close()


def get_policy():
    conn = get_conn()
    row = conn.execute("SELECT policy_json FROM policy WHERE id = 1").fetchone()
    conn.close()
    return json.loads(row["policy_json"])


def save_policy(policy: dict):
    conn = get_conn()
    conn.execute(
        "UPDATE policy SET policy_json = ?, updated_at = ? WHERE id = 1",
        (json.dumps(policy), _now()),
    )
    conn.commit()
    conn.close()


def add_audit_entry(entry_type: str, payload: dict):
    conn = get_conn()
    conn.execute(
        "INSERT INTO audit_log (timestamp, type, payload_json) VALUES (?, ?, ?)",
        (_now(), entry_type, json.dumps(payload)),
    )
    conn.commit()
    conn.close()


def list_audit_entries(limit: int = 200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "timestamp": r["timestamp"],
            "type": r["type"],
            "payload": json.loads(r["payload_json"]),
        }
        for r in rows
    ]


def insert_transaction(scenario, features, score, band, contributions, explanation=None):
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO transactions
            (created_at, scenario, features_json, score, band, contributions_json, explanation)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            _now(),
            scenario,
            json.dumps(features),
            score,
            band,
            json.dumps(contributions),
            explanation,
        ),
    )
    conn.commit()
    tx_id = cur.lastrowid
    conn.close()
    return tx_id


def _row_to_tx(r):
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "scenario": r["scenario"],
        "features": json.loads(r["features_json"]),
        "score": r["score"],
        "band": r["band"],
        "contributions": json.loads(r["contributions_json"]) if r["contributions_json"] else {},
        "explanation": r["explanation"],
    }


def list_transactions(limit: int = 200):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM transactions ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_row_to_tx(r) for r in rows]


def get_transaction(tx_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM transactions WHERE id = ?", (tx_id,)).fetchone()
    conn.close()
    return _row_to_tx(row) if row else None


def set_transaction_explanation(tx_id: int, explanation: str):
    conn = get_conn()
    conn.execute("UPDATE transactions SET explanation = ? WHERE id = ?", (explanation, tx_id))
    conn.commit()
    conn.close()


def rescore_transaction(tx_id: int, score, band, contributions):
    conn = get_conn()
    conn.execute(
        "UPDATE transactions SET score = ?, band = ?, contributions_json = ? WHERE id = ?",
        (score, band, json.dumps(contributions), tx_id),
    )
    conn.commit()
    conn.close()


def insert_pending_change(instruction, proposed_delta, confidence, reason):
    conn = get_conn()
    cur = conn.execute(
        """
        INSERT INTO pending_changes
            (created_at, instruction, proposed_delta_json, confidence, reason, status)
        VALUES (?, ?, ?, ?, ?, 'pending')
        """,
        (_now(), instruction, json.dumps(proposed_delta), confidence, reason),
    )
    conn.commit()
    pc_id = cur.lastrowid
    conn.close()
    return pc_id


def get_pending_change(pc_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM pending_changes WHERE id = ?", (pc_id,)).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "instruction": row["instruction"],
        "proposed_delta": json.loads(row["proposed_delta_json"]),
        "confidence": row["confidence"],
        "reason": row["reason"],
        "status": row["status"],
    }


def set_pending_change_status(pc_id: int, status: str):
    conn = get_conn()
    conn.execute("UPDATE pending_changes SET status = ? WHERE id = ?", (status, pc_id))
    conn.commit()
    conn.close()


def list_pending_changes(status: str = "pending"):
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM pending_changes WHERE status = ? ORDER BY id DESC", (status,)
    ).fetchall()
    conn.close()
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "instruction": r["instruction"],
            "proposed_delta": json.loads(r["proposed_delta_json"]),
            "confidence": r["confidence"],
            "reason": r["reason"],
            "status": r["status"],
        }
        for r in rows
    ]
