from __future__ import annotations

import json
import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable, List

from .models import EventRecord, SessionSummary


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    thread_name TEXT,
    cwd TEXT,
    started_at TEXT,
    updated_at TEXT,
    event_count INTEGER NOT NULL DEFAULT 0,
    function_calls INTEGER NOT NULL DEFAULT 0,
    tool_errors INTEGER NOT NULL DEFAULT 0,
    tokens_input INTEGER NOT NULL DEFAULT 0,
    tokens_output INTEGER NOT NULL DEFAULT 0,
    last_message TEXT,
    raw_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL,
    turn_id TEXT,
    event_type TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    raw_type TEXT NOT NULL,
    message TEXT,
    data_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    report_date TEXT PRIMARY KEY,
    generated_at TEXT NOT NULL,
    path TEXT NOT NULL,
    metrics_json TEXT NOT NULL
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _ensure_event_key_schema(conn)
    conn.commit()
    return conn


def _ensure_event_key_schema(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)").fetchall()}
    if "event_key" not in columns:
        conn.execute("ALTER TABLE events ADD COLUMN event_key TEXT")
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(events)").fetchall()}
    if "events_event_key_idx" not in indexes:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS events_event_key_idx ON events(event_key)")


def upsert_sessions(conn: sqlite3.Connection, summaries: Iterable[SessionSummary]) -> None:
    rows = [
        (
            s.session_id,
            s.thread_name,
            s.cwd,
            s.started_at,
            s.updated_at,
            s.event_count,
            s.function_calls,
            s.tool_errors,
            s.tokens_input,
            s.tokens_output,
            s.last_message,
            json.dumps(s.raw, ensure_ascii=False, sort_keys=True),
        )
        for s in summaries
    ]
    conn.executemany(
        """
        INSERT INTO sessions (
            session_id, thread_name, cwd, started_at, updated_at,
            event_count, function_calls, tool_errors,
            tokens_input, tokens_output, last_message, raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(session_id) DO UPDATE SET
            thread_name=excluded.thread_name,
            cwd=excluded.cwd,
            started_at=excluded.started_at,
            updated_at=excluded.updated_at,
            event_count=excluded.event_count,
            function_calls=excluded.function_calls,
            tool_errors=excluded.tool_errors,
            tokens_input=excluded.tokens_input,
            tokens_output=excluded.tokens_output,
            last_message=excluded.last_message,
            raw_json=excluded.raw_json
        """,
        rows,
    )
    conn.commit()


def insert_events(conn: sqlite3.Connection, events: Iterable[EventRecord]) -> int:
    rows = [
        (
            _event_key(e),
            e.session_id,
            e.turn_id,
            e.event_type,
            e.timestamp,
            e.raw_type,
            e.message,
            json.dumps(e.data, ensure_ascii=False, sort_keys=True),
        )
        for e in events
    ]
    inserted = 0
    for row in rows:
        try:
            before = conn.total_changes
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO events (
                    event_key, session_id, turn_id, event_type, timestamp, raw_type, message, data_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                row,
            )
            _ = cursor
            inserted += conn.total_changes - before
        except sqlite3.Error:
            continue
    conn.commit()
    return inserted


def _event_key(event: EventRecord) -> str:
    payload = json.dumps(
        {
            "session_id": event.session_id,
            "turn_id": event.turn_id or "",
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "raw_type": event.raw_type,
            "message": event.message or "",
            "data": event.data,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def store_report(conn: sqlite3.Connection, report_date: str, generated_at: str, path: str, metrics: dict) -> None:
    conn.execute(
        """
        INSERT INTO reports (report_date, generated_at, path, metrics_json)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(report_date) DO UPDATE SET
            generated_at=excluded.generated_at,
            path=excluded.path,
            metrics_json=excluded.metrics_json
        """,
        (report_date, generated_at, path, json.dumps(metrics, ensure_ascii=False, sort_keys=True)),
    )
    conn.commit()


def fetch_sessions(conn: sqlite3.Connection, since: str | None = None) -> List[sqlite3.Row]:
    if since:
        cur = conn.execute(
            "SELECT * FROM sessions WHERE COALESCE(updated_at, started_at) >= ? ORDER BY COALESCE(updated_at, started_at) DESC, session_id DESC",
            (since,),
        )
    else:
        cur = conn.execute(
            "SELECT * FROM sessions ORDER BY COALESCE(updated_at, started_at) DESC, session_id DESC"
        )
    return list(cur.fetchall())
