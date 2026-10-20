from __future__ import annotations

import json
import sqlite3
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS transcripts (asset_id TEXT PRIMARY KEY, payload TEXT NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL, label TEXT NOT NULL, snapshot TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
"""

def initialize(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA); conn.commit()

def save_transcript(conn: sqlite3.Connection, asset_id: str, payload: dict[str, Any]) -> None:
    conn.execute("INSERT OR REPLACE INTO transcripts(asset_id,payload,updated_at) VALUES(?,?,CURRENT_TIMESTAMP)", (asset_id, json.dumps(payload, ensure_ascii=False))); conn.commit()

def get_transcript(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT payload FROM transcripts WHERE asset_id=?", (asset_id,)).fetchone()
    return json.loads(row[0]) if row else None

def add_snapshot(conn: sqlite3.Connection, project_id: str, label: str, snapshot: dict[str, Any]) -> int:
    cursor = conn.execute("INSERT INTO history(project_id,label,snapshot) VALUES(?,?,?)", (project_id, label, json.dumps(snapshot, ensure_ascii=False, sort_keys=True))); conn.commit(); return int(cursor.lastrowid)

def list_snapshots(conn: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    return [{"id": row[0], "label": row[1], "snapshot": json.loads(row[2]), "created_at": row[3]} for row in conn.execute("SELECT id,label,snapshot,created_at FROM history WHERE project_id=? ORDER BY id DESC", (project_id,))]
