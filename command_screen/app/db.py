import json
import os
import sqlite3
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY,
    fax_no TEXT,
    fax_type TEXT,
    title TEXT,
    summary TEXT,
    status TEXT,
    priority TEXT,
    received_at TEXT,
    updated_at TEXT,
    forwarded_at TEXT,
    has_file INTEGER NOT NULL DEFAULT 0,
    file_name TEXT,
    payload_json TEXT NOT NULL,
    synced_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_ct_status ON tickets(status);
CREATE INDEX IF NOT EXISTS ix_ct_type ON tickets(fax_type);
CREATE INDEX IF NOT EXISTS ix_ct_prio ON tickets(priority);

CREATE TABLE IF NOT EXISTS sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS reference (
    key TEXT PRIMARY KEY,
    payload_json TEXT NOT NULL,
    fetched_at TEXT
);

CREATE TABLE IF NOT EXISTS directives (
    id INTEGER PRIMARY KEY,
    station_id INTEGER,
    ticket_id INTEGER,
    message TEXT,
    actor TEXT,
    sent_at TEXT,
    delivered_at TEXT,
    payload_json TEXT
);

CREATE TABLE IF NOT EXISTS alert_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    ticket_id INTEGER,
    title TEXT,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    seen_at TEXT
);

CREATE TABLE IF NOT EXISTS command_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    request_json TEXT,
    ok INTEGER NOT NULL DEFAULT 0,
    response_json TEXT,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

DEVICE = os.environ.get("CS_DEVICE_NAME", "جهاز القيادة")


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT OR IGNORE INTO settings(key, value) VALUES ('station_url', ?)", (config.DEFAULT_STATION_URL,))


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r is not None else None


def get_setting(conn, key, default=None):
    r = one(conn, "SELECT value FROM settings WHERE key=?", (key,))
    return r["value"] if r else default


def set_setting(conn, key, value):
    conn.execute("INSERT INTO settings(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, value))


def state_get(conn, key, default=None):
    r = one(conn, "SELECT value FROM sync_state WHERE key=?", (key,))
    return r["value"] if r else default


def state_set(conn, key, value):
    conn.execute("INSERT INTO sync_state(key, value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                 (key, str(value)))
