import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS routes_sites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('route','splice','checkpoint','junction','exchange')),
    axis_name TEXT,
    parent_route_id INTEGER REFERENCES routes_sites(id) ON DELETE SET NULL,
    geometry_json TEXT NOT NULL,
    lat REAL, lon REAL,
    cable_type TEXT,
    fiber_count INTEGER,
    length_m REAL,
    parties TEXT,
    install_year INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teams_personnel (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    rank TEXT,
    specialty TEXT,
    team_name TEXT,
    is_leader INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'available' CHECK (status IN ('available','on_mission','off_duty')),
    phone TEXT,
    current_ticket_id INTEGER REFERENCES faxes_tickets(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS faxes_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fax_no TEXT NOT NULL UNIQUE,
    fax_type TEXT NOT NULL CHECK (fax_type IN ('fault','project','coordination')),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    required_action TEXT,
    location_text TEXT,
    requesting_party TEXT,
    responsible_party TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('critical','high','normal','low')),
    status TEXT NOT NULL DEFAULT 'new',
    route_id INTEGER REFERENCES routes_sites(id) ON DELETE SET NULL,
    geometry_json TEXT,
    lat REAL, lon REAL,
    terrain TEXT,
    assigned_team TEXT,
    cause TEXT,
    resolution TEXT,
    original_file TEXT,
    original_filename TEXT,
    received_at TEXT NOT NULL,
    status_changed_at TEXT NOT NULL,
    closed_at TEXT,
    forwarded_to_command INTEGER NOT NULL DEFAULT 0,
    forwarded_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tickets_status ON faxes_tickets(status);
CREATE INDEX IF NOT EXISTS ix_tickets_type ON faxes_tickets(fax_type);
CREATE INDEX IF NOT EXISTS ix_tickets_latlon ON faxes_tickets(lat, lon);

CREATE TABLE IF NOT EXISTS updates_ticket (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES faxes_tickets(id) ON DELETE CASCADE,
    old_status TEXT,
    new_status TEXT NOT NULL,
    at TEXT NOT NULL,
    notes TEXT,
    actor TEXT
);
CREATE INDEX IF NOT EXISTS ix_updates_ticket ON updates_ticket(ticket_id);

CREATE TABLE IF NOT EXISTS estimates_project (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL UNIQUE REFERENCES faxes_tickets(id) ON DELETE CASCADE,
    measured_length_m REAL,
    length_source TEXT,
    cable_type TEXT,
    fiber_count INTEGER,
    task_nature TEXT,
    terrain TEXT,
    reserve_pct REAL,
    total_cable_m REAL,
    splice_closures INTEGER,
    fusion_splices INTEGER,
    connection_points INTEGER,
    media_converters INTEGER,
    equipment_json TEXT,
    travel_hours REAL,
    laying_hours REAL,
    splicing_hours REAL,
    testing_hours REAL,
    difficulty_factor REAL,
    estimated_hours REAL,
    estimated_days REAL,
    manual_overrides_json TEXT,
    notes TEXT,
    computed_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ticket_needs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES faxes_tickets(id) ON DELETE CASCADE,
    item_name TEXT NOT NULL,
    category TEXT,
    quantity REAL NOT NULL DEFAULT 1,
    unit TEXT,
    availability TEXT NOT NULL DEFAULT 'needs_approval' CHECK (availability IN ('available','needs_approval','shortage')),
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_needs_ticket ON ticket_needs(ticket_id);

CREATE TABLE IF NOT EXISTS equipment_catalog (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('cable','material','device','tool')),
    unit TEXT,
    default_availability TEXT NOT NULL DEFAULT 'available',
    guide TEXT,
    safety TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS places (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    name_norm TEXT NOT NULL,
    name_en TEXT,
    kind TEXT,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    source TEXT NOT NULL DEFAULT 'osm'
);
CREATE INDEX IF NOT EXISTS ix_places_norm ON places(name_norm);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    label TEXT,
    unit TEXT,
    grp TEXT,
    sort INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS command_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER NOT NULL REFERENCES faxes_tickets(id) ON DELETE CASCADE,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS command_directives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticket_id INTEGER REFERENCES faxes_tickets(id) ON DELETE SET NULL,
    message TEXT NOT NULL,
    actor TEXT NOT NULL,
    at TEXT NOT NULL,
    delivered_at TEXT
);

CREATE TABLE IF NOT EXISTS command_alert_acks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_key TEXT NOT NULL,
    ticket_id INTEGER,
    actor TEXT NOT NULL,
    at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS logs_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    table_name TEXT NOT NULL,
    record_id INTEGER,
    old_value TEXT,
    new_value TEXT,
    device TEXT,
    actor TEXT,
    at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_table ON logs_audit(table_name, record_id);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'operator',
    permissions TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
"""

DEVICE = os.environ.get("PS_DEVICE_NAME", "محطة قسم المشروعات")


def now() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


def connect() -> sqlite3.Connection:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(faxes_tickets)")}
    if "command_seen_at" not in cols:
        conn.execute("ALTER TABLE faxes_tickets ADD COLUMN command_seen_at TEXT")
        conn.execute("ALTER TABLE faxes_tickets ADD COLUMN command_seen_by TEXT")


def row_to_dict(row):
    return dict(row) if row is not None else None


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(conn, sql, params=()):
    return row_to_dict(conn.execute(sql, params).fetchone())


def _audit(conn, action, table, record_id, old, new, actor):
    conn.execute(
        "INSERT INTO logs_audit(action, table_name, record_id, old_value, new_value, device, actor, at)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (
            action,
            table,
            record_id,
            json.dumps(old, ensure_ascii=False) if old is not None else None,
            json.dumps(new, ensure_ascii=False) if new is not None else None,
            DEVICE,
            actor,
            now(),
        ),
    )


def insert(conn, table, data: dict, actor: str, audit: bool = True) -> int:
    cols = list(data.keys())
    cur = conn.execute(
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({','.join('?' for _ in cols)})",
        [data[c] for c in cols],
    )
    rid = cur.lastrowid
    if audit:
        _audit(conn, "INSERT", table, rid, None, data, actor)
    return rid


def update(conn, table, rid: int, data: dict, actor: str) -> dict:
    old = one(conn, f"SELECT * FROM {table} WHERE id=?", (rid,))
    if old is None:
        raise KeyError(rid)
    changed = {k: v for k, v in data.items() if old.get(k) != v}
    if not changed:
        return old
    sets = ", ".join(f"{k}=?" for k in changed)
    conn.execute(f"UPDATE {table} SET {sets} WHERE id=?", [*changed.values(), rid])
    audit_keys = [k for k in changed if k != "updated_at"]
    if audit_keys:
        _audit(conn, "UPDATE", table, rid, {k: old.get(k) for k in audit_keys}, {k: changed[k] for k in audit_keys}, actor)
    return one(conn, f"SELECT * FROM {table} WHERE id=?", (rid,))


def delete(conn, table, rid: int, actor: str) -> None:
    old = one(conn, f"SELECT * FROM {table} WHERE id=?", (rid,))
    if old is None:
        raise KeyError(rid)
    conn.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
    _audit(conn, "DELETE", table, rid, old, None, actor)


def get_settings(conn) -> dict:
    out = {}
    for r in conn.execute("SELECT key, value FROM settings"):
        v = r["value"]
        try:
            out[r["key"]] = json.loads(v)
        except (ValueError, TypeError):
            out[r["key"]] = v
    return out
