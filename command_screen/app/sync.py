"""Sync engine: polls the Projects Station every POLL_SECONDS and mirrors forwarded faxes locally."""
import json
import queue
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config, db

_lock = threading.Lock()
_subscribers = []
_thread = None
_stop = threading.Event()

STATUS = {"connected": False, "station_device": None, "station_url": None,
          "last_ok": None, "last_error": None, "last_poll": None}


def subscribe():
    q = queue.Queue(maxsize=200)
    with _lock:
        _subscribers.append(q)
    return q


def unsubscribe(q):
    with _lock:
        if q in _subscribers:
            _subscribers.remove(q)


def publish(event):
    with _lock:
        subs = list(_subscribers)
    for q in subs:
        try:
            q.put_nowait(event)
        except queue.Full:
            pass


def _req(method, url, payload=None, timeout=6, raw=False):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (body if raw else (json.loads(body.decode("utf-8")) if body else {}))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", str(e))
        except Exception:
            detail = str(e)
        return e.code, {"detail": detail}
    except Exception as e:
        return 0, {"detail": str(e)}


def station_url(conn):
    return (db.get_setting(conn, "station_url") or config.DEFAULT_STATION_URL).rstrip("/")


def _set_conn(conn, ok, device=None, error=None):
    changed = STATUS["connected"] != ok
    STATUS.update(connected=ok, station_device=device or STATUS["station_device"],
                  last_error=error, last_poll=db.now())
    if ok:
        STATUS["last_ok"] = db.now()
    db.state_set(conn, "connected", "1" if ok else "0")
    db.state_set(conn, "last_ok", STATUS["last_ok"] or "")
    db.state_set(conn, "last_error", error or "")
    if changed:
        publish({"type": "connection", "connected": ok})


def _file_ext(head: bytes) -> str:
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8"):
        return ".jpg"
    if head[:4] in (b"GIF8",):
        return ".gif"
    if head[:2] == b"BM":
        return ".bmp"
    return ".bin"


def _maybe_file(conn, base, ticket):
    tid = ticket.get("id")
    if not tid or not ticket.get("has_file"):
        return
    existing = db.one(conn, "SELECT file_name FROM tickets WHERE id=?", (tid,))
    if existing and existing.get("file_name"):
        return
    code, data = _req("GET", f"{base}/api/tickets/{tid}/file", timeout=15, raw=True)
    if code != 200 or not isinstance(data, (bytes, bytearray)):
        return
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{tid}_orig{_file_ext(bytes(data[:8]))}"
    (config.UPLOAD_DIR / name).write_bytes(data)
    conn.execute("UPDATE tickets SET file_name=?, has_file=1 WHERE id=?", (name, tid))


def _upsert_ticket(conn, ticket):
    if not ticket or not ticket.get("id"):
        return
    t = dict(ticket)
    payload = json.dumps(t, ensure_ascii=False, default=str)
    now = db.now()
    conn.execute(
        "INSERT INTO tickets(id, fax_no, fax_type, title, summary, status, priority, received_at, updated_at,"
        " forwarded_at, has_file, payload_json, synced_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET fax_no=excluded.fax_no, fax_type=excluded.fax_type, title=excluded.title,"
        " summary=excluded.summary, status=excluded.status, priority=excluded.priority, received_at=excluded.received_at,"
        " updated_at=excluded.updated_at, forwarded_at=excluded.forwarded_at, has_file=excluded.has_file,"
        " payload_json=excluded.payload_json, synced_at=excluded.synced_at",
        (t.get("id"), t.get("fax_no"), t.get("fax_type"), t.get("title"), t.get("summary"), t.get("status"),
         t.get("priority"), t.get("received_at"), t.get("updated_at"), t.get("forwarded_at"),
         1 if t.get("has_file") else 0, payload, now))
    if not t.get("has_file"):
        conn.execute("UPDATE tickets SET has_file=0 WHERE id=? AND file_name IS NULL", (t["id"],))


def _ticket_alerts(item):
    """Return urgent alert dicts for a feed item."""
    out = []
    t = (item.get("payload") or {}).get("ticket") or {}
    tid = t.get("id")
    fid = item.get("id")
    if not tid:
        return out
    if t.get("priority") == "critical" and t.get("status") == "new":
        out.append({"kind": "critical_new", "dedupe": f"critical:{tid}", "ticket_id": tid,
                    "title": f"بلاغ حرج جديد — {t.get('fax_no')}",
                    "message": t.get("title") or "", "ticket": _brief(t)})
    det = (item.get("payload") or {}).get("ticket", {}).get("detection") or {}
    for a in det.get("alerts") or []:
        if a.get("severity") == "urgent" and a.get("type") == "repeat_fault":
            sig = (a.get("title") or "") + "|" + ",".join(str(r.get("fax_no")) for r in (a.get("related") or [])[:2])
            out.append({"kind": "repeat_fault", "dedupe": f"repeat:{tid}:{sig}", "ticket_id": tid,
                        "title": f"{a.get('title')} — {t.get('fax_no')}",
                        "message": a.get("message") or "", "related": a.get("related") or [],
                        "ticket": _brief(t)})
    return out


def _brief(t):
    return {k: t.get(k) for k in ("id", "fax_no", "fax_type", "title", "status", "priority", "received_at",
                                 "location_text", "requesting_party", "assigned_team", "cause", "resolution")}


def _cache_reference(conn, base):
    changed = False
    for key, path in (("meta", "/api/meta"), ("routes", "/api/routes"), ("teams", "/api/teams")):
        code, data = _req("GET", base + path, timeout=8)
        if code != 200:
            continue
        payload = json.dumps(data, ensure_ascii=False, default=str)
        old = db.one(conn, "SELECT payload_json FROM reference WHERE key=?", (key,))
        if not old or old["payload_json"] != payload:
            conn.execute("INSERT INTO reference(key, payload_json, fetched_at) VALUES (?,?,?)"
                         " ON CONFLICT(key) DO UPDATE SET payload_json=excluded.payload_json, fetched_at=excluded.fetched_at",
                         (key, payload, db.now()))
            changed = True
    return changed


def poll_once():
    """One sync cycle. Returns list of SSE events."""
    events = []
    conn = db.connect()
    try:
        base = station_url(conn)
        STATUS["station_url"] = base
        last_id = int(db.state_get(conn, "feed_id", "0") or 0)
        dir_id = int(db.state_get(conn, "directive_id", "0") or 0)

        code, health = _req("GET", base + "/api/health", timeout=4)
        if code != 200:
            _set_conn(conn, False, error=(health or {}).get("detail") or f"HTTP {code}")
            conn.commit()
            return events
        device = health.get("device")
        _set_conn(conn, True, device=device)

        code, items = _req("GET", f"{base}/api/command/feed?since_id={last_id}&limit=200", timeout=8)
        if code != 200:
            _set_conn(conn, False, error=(items or {}).get("detail") or f"HTTP {code}")
            conn.commit()
            return events
        max_id = last_id
        ticket_events = []
        for it in items if isinstance(items, list) else []:
            max_id = max(max_id, it.get("id") or 0)
            payload = it.get("payload") or {}
            ticket = payload.get("ticket") or {}
            _upsert_ticket(conn, ticket)
            _maybe_file(conn, base, ticket)
            for a in _ticket_alerts(it):
                cur = conn.execute(
                    "INSERT OR IGNORE INTO alert_events(dedupe_key, kind, ticket_id, title, payload_json, created_at)"
                    " VALUES (?,?,?,?,?,?)",
                    (a["dedupe"], a["kind"], a.get("ticket_id"), a.get("title"),
                     json.dumps(a, ensure_ascii=False, default=str), db.now()))
                if cur.rowcount and not any(e["type"] == "alert" and e["alert"].get("dedupe") == a["dedupe"] for e in events):
                    row = db.one(conn, "SELECT id FROM alert_events WHERE dedupe_key=?", (a["dedupe"],))
                    events.append({"type": "alert", "alert": {**a, "id": row["id"] if row else None}})
            ticket_events.append(ticket.get("id"))
            code2, _ = _req("POST", f"{base}/api/command/ack/{it.get('id')}", timeout=4)
        if max_id != last_id:
            db.state_set(conn, "feed_id", str(max_id))
        for tid in dict.fromkeys(ticket_events):
            events.append({"type": "ticket", "id": tid})

        code, dirs = _req("GET", f"{base}/api/command/directives?since_id={dir_id}&limit=200", timeout=6)
        if code == 200 and isinstance(dirs, list):
            dmax = dir_id
            for d in dirs:
                dmax = max(dmax, d.get("id") or 0)
                conn.execute(
                    "INSERT INTO directives(id, station_id, ticket_id, message, actor, sent_at, delivered_at, payload_json)"
                    " VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                    (d.get("id"), d.get("id"), d.get("ticket_id"), d.get("message"), d.get("actor"),
                     d.get("at"), db.now(), json.dumps(d, ensure_ascii=False)))
                events.append({"type": "directive", "directive": d})
            if dmax != dir_id:
                db.state_set(conn, "directive_id", str(dmax))

        if _cache_reference(conn, base):
            events.append({"type": "reference"})
        conn.commit()
    except Exception as e:
        _set_conn(conn, False, error=str(e))
        try:
            conn.commit()
        except Exception:
            pass
    finally:
        conn.close()
    return events


def send_command(action, conn=None, **fields):
    """Send a commander command to the station. Returns (ok, result_or_error)."""
    own = conn is None
    conn = conn or db.connect()
    try:
        base = station_url(conn)
        payload = {"action": action, "device": db.DEVICE, **fields}
        code, data = _req("POST", base + "/api/command/inbox", payload=payload, timeout=8)
        ok = code == 200 and isinstance(data, dict) and data.get("ok", True)
        conn.execute(
            "INSERT INTO command_log(action, request_json, ok, response_json, at) VALUES (?,?,?,?,?)",
            (action, json.dumps(payload, ensure_ascii=False), 1 if ok else 0,
             json.dumps(data, ensure_ascii=False, default=str)[:8000], db.now()))
        conn.commit()
        if ok and isinstance(data, dict):
            ticket = data.get("ticket")
            if ticket:
                _upsert_ticket(conn, ticket)
                if action != "seen":
                    publish({"type": "ticket", "id": ticket.get("id")})
            if data.get("directive"):
                publish({"type": "directive", "directive": data["directive"]})
        return ok, data
    finally:
        if own:
            conn.close()


def _loop():
    while not _stop.is_set():
        try:
            for ev in poll_once():
                publish(ev)
        except Exception:
            pass
        _stop.wait(config.POLL_SECONDS)


def start():
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, daemon=True, name="command-sync")
    _thread.start()


def stop():
    _stop.set()
