import json
import queue
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, sync


@asynccontextmanager
async def lifespan(_app):
    conn = db.connect()
    db.init_schema(conn)
    conn.commit()
    conn.close()
    sync.start()
    yield
    sync.stop()


app = FastAPI(title="شاشة القائد", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

FAX_TYPES = {"fault": "عطل", "project": "مشروع إنشاء", "coordination": "طلب تنسيق"}
STATUSES = [("new", "وارد جديد"), ("awaiting_coordination", "انتظار التنسيق / التصديق"),
            ("preparing", "قيد التجهيز"), ("in_progress", "جاري التنفيذ الميداني"), ("closed", "مغلق وموثق")]
STATUS_LABELS = dict(STATUSES)
PRIORITIES = {"critical": "حرجة", "high": "عالية", "normal": "عادية", "low": "منخفضة"}
AVAILABILITY = {"available": "متاح", "needs_approval": "يحتاج تصديق", "shortage": "عجز"}
KINDS = {"route": "مسار كابل", "splice": "وصلة", "checkpoint": "غرفة تفتيش",
         "junction": "نقطة ربط", "exchange": "عقدة / سنترال"}


def get_conn():
    conn = db.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _404(what="العنصر"):
    raise HTTPException(404, f"{what} غير موجود")


def _reference(conn, key):
    r = db.one(conn, "SELECT payload_json, fetched_at FROM reference WHERE key=?", (key,))
    if not r:
        return None, None
    return json.loads(r["payload_json"]), r["fetched_at"]


def _meta(conn):
    meta, _ = _reference(conn, "meta")
    return meta or {}


def _ticket_payload(row):
    try:
        return json.loads(row["payload_json"])
    except Exception:
        return {}


def _list_item(row):
    t = _ticket_payload(row)
    return {
        "id": row["id"], "fax_no": row["fax_no"], "fax_type": row["fax_type"], "title": row["title"],
        "status": row["status"], "priority": row["priority"], "received_at": row["received_at"],
        "updated_at": row["updated_at"], "forwarded_at": row.get("forwarded_at"),
        "type_label": FAX_TYPES.get(row["fax_type"]), "status_label": STATUS_LABELS.get(row["status"]),
        "priority_label": PRIORITIES.get(row["priority"]),
        "location_text": t.get("location_text"), "requesting_party": t.get("requesting_party"),
        "assigned_team": t.get("assigned_team"), "lat": t.get("lat"), "lon": t.get("lon"),
        "wait": t.get("wait"), "needs_status": t.get("needs_status"), "has_estimate": t.get("has_estimate"),
        "has_file": bool(row["has_file"] or t.get("has_file")), "route_name": t.get("route_name"),
        "command_seen_at": t.get("command_seen_at"),
    }


# ---------------------------------------------------------------- status / meta
@app.get("/api/health")
def health():
    return {"ok": True, "device": db.DEVICE, "time": db.now()}


@app.get("/api/status")
def status(conn=Depends(get_conn)):
    conn_state = db.state_get(conn, "connected", "0") == "1"
    return {
        "connected": conn_state or sync.STATUS["connected"],
        "station_device": sync.STATUS["station_device"],
        "station_url": sync.STATUS["station_url"] or station_url_of(conn),
        "last_ok": db.state_get(conn, "last_ok") or sync.STATUS["last_ok"],
        "last_error": db.state_get(conn, "last_error") or sync.STATUS["last_error"],
        "last_poll": sync.STATUS["last_poll"],
        "tickets": conn.execute("SELECT COUNT(*) FROM tickets").fetchone()[0],
    }


def station_url_of(conn):
    return db.get_setting(conn, "station_url", config.DEFAULT_STATION_URL)


@app.get("/api/meta")
def meta(conn=Depends(get_conn)):
    m = _meta(conn)
    return {
        "fax_types": FAX_TYPES, "statuses": STATUSES, "priorities": PRIORITIES,
        "availability": AVAILABILITY, "kinds": KINDS,
        "labels": {
            "fax_types": (m.get("fax_types") or FAX_TYPES),
            "priorities": (m.get("priorities") or PRIORITIES),
            "availability": (m.get("availability") or AVAILABILITY),
            "statuses": dict(m.get("statuses") or STATUSES),
            "settings": m.get("settings") or {},
        },
        "device": db.DEVICE,
        "station": {"url": station_url_of(conn), "connected": sync.STATUS["connected"],
                    "device": sync.STATUS["station_device"]},
    }


@app.get("/api/settings")
def get_settings(conn=Depends(get_conn)):
    return {"station_url": station_url_of(conn)}


class SettingsIn(BaseModel):
    station_url: str = Field(..., min_length=8, max_length=300)


@app.put("/api/settings")
def put_settings(body: SettingsIn, conn=Depends(get_conn)):
    url = body.station_url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "عنوان المحطة يجب أن يبدأ بـ http:// أو https://")
    db.set_setting(conn, "station_url", url)
    return {"station_url": url}


# ---------------------------------------------------------------- dashboard
@app.get("/api/dashboard")
def dashboard(conn=Depends(get_conn)):
    c = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
    faults = c("SELECT COUNT(*) FROM tickets WHERE fax_type='fault' AND status!='closed'")
    projects = c("SELECT COUNT(*) FROM tickets WHERE fax_type='project' AND status!='closed'")
    critical = c("SELECT COUNT(*) FROM tickets WHERE priority='critical' AND status!='closed'")
    overdue = 0
    for r in conn.execute("SELECT payload_json FROM tickets WHERE status='awaiting_coordination'"):
        try:
            if (json.loads(r["payload_json"]).get("wait") or {}).get("overdue"):
                overdue += 1
        except Exception:
            pass
    teams, _ = _reference(conn, "teams")
    on_mission = sum(1 for p in (teams or []) if p.get("status") == "on_mission")
    unseen = c("SELECT COUNT(*) FROM alert_events WHERE seen_at IS NULL")
    return {
        "active_faults": faults, "active_projects": projects, "overdue_coordination": overdue,
        "critical_open": critical, "teams_on_mission": on_mission,
        "unseen_alerts": unseen, "total": c("SELECT COUNT(*) FROM tickets"),
        "connected": sync.STATUS["connected"], "last_ok": db.state_get(conn, "last_ok"),
    }


# ---------------------------------------------------------------- tickets
@app.get("/api/tickets")
def list_tickets(status: Optional[str] = None, fax_type: Optional[str] = None, priority: Optional[str] = None,
                 q: Optional[str] = None, scope: str = "active", limit: int = Query(500, le=2000),
                 conn=Depends(get_conn)):
    where, params = [], []
    if scope == "active":
        where.append("status != 'closed'")
    elif scope == "closed":
        where.append("status = 'closed'")
    if status:
        where.append("status = ?"); params.append(status)
    if fax_type:
        where.append("fax_type = ?"); params.append(fax_type)
    if priority:
        where.append("priority = ?"); params.append(priority)
    sql = "SELECT * FROM tickets" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, received_at DESC"
    items = [_list_item(r) for r in db.rows(conn, sql, params)]
    if q:
        nq = q.strip()
        items = [t for t in items if nq and nq in " ".join(str(t.get(k) or "") for k in
                 ("fax_no", "title", "location_text", "requesting_party", "assigned_team"))]
    return items[:limit]


@app.get("/api/activity")
def activity(limit: int = Query(40, le=200), conn=Depends(get_conn)):
    """Merged timeline of station-side updates across all forwarded tickets."""
    items = []
    for row in db.rows(conn, "SELECT payload_json FROM tickets"):
        try:
            t = json.loads(row["payload_json"])
        except Exception:
            continue
        for u in t.get("updates") or []:
            items.append({"ticket_id": t.get("id"), "fax_no": t.get("fax_no"),
                          "title": t.get("title"), "fax_type": t.get("fax_type"),
                          "at": u.get("at"), "actor": u.get("actor"),
                          "label": u.get("new_label") or u.get("new_status"),
                          "notes": u.get("notes")})
    items.sort(key=lambda x: x.get("at") or "", reverse=True)
    return items[:limit]


@app.get("/api/tickets/{tid}")
def get_ticket(tid: int, conn=Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM tickets WHERE id=?", (tid,))
    if not row:
        _404("العملية")
    t = _ticket_payload(row)
    t["synced_at"] = row["synced_at"]
    t["file_name"] = row["file_name"]
    t["local_has_file"] = bool(row["file_name"])
    t["type_label"] = FAX_TYPES.get(t.get("fax_type"))
    t["status_label"] = STATUS_LABELS.get(t.get("status"))
    t["priority_label"] = PRIORITIES.get(t.get("priority"))
    return t


@app.get("/api/tickets/{tid}/file")
def get_file(tid: int, conn=Depends(get_conn)):
    row = db.one(conn, "SELECT file_name FROM tickets WHERE id=?", (tid,))
    if not row or not row["file_name"]:
        _404("ملف الفاكس")
    p = (config.UPLOAD_DIR / row["file_name"]).resolve()
    if config.UPLOAD_DIR.resolve() not in p.parents or not p.exists():
        _404("ملف الفاكس")
    return FileResponse(p, content_disposition_type="inline")


# ---------------------------------------------------------------- reference data (read-only mirror)
@app.get("/api/reference")
def reference(conn=Depends(get_conn)):
    routes, routes_at = _reference(conn, "routes")
    teams, teams_at = _reference(conn, "teams")
    return {"routes": routes or [], "teams": teams or [],
            "fetched_at": {"routes": routes_at, "teams": teams_at}}


@app.get("/api/map/layers")
def map_layers(conn=Depends(get_conn)):
    routes, _ = _reference(conn, "routes")
    feats = []
    for r in routes or []:
        geom = r.get("geometry")
        if not geom:
            continue
        feats.append({"type": "Feature", "geometry": geom, "properties": {
            "id": r["id"], "code": r["code"], "name": r["name"], "kind": r["kind"],
            "kind_label": KINDS.get(r["kind"]), "cable_type": r.get("cable_type"),
            "fiber_count": r.get("fiber_count"), "length_m": r.get("length_m"),
            "parties": r.get("parties"), "axis_name": r.get("axis_name"),
            "parent_route_id": r.get("parent_route_id"), "lat": r.get("lat"), "lon": r.get("lon")}})
    tickets = []
    for row in db.rows(conn, "SELECT * FROM tickets"):
        t = _ticket_payload(row)
        geom = t.get("geometry")
        if not geom:
            continue
        tickets.append({"type": "Feature", "geometry": geom, "properties": {
            "id": t["id"], "fax_no": t.get("fax_no"), "title": t.get("title"), "fax_type": t.get("fax_type"),
            "type_label": FAX_TYPES.get(t.get("fax_type")), "status": t.get("status"),
            "status_label": STATUS_LABELS.get(t.get("status")), "priority": t.get("priority"),
            "priority_label": PRIORITIES.get(t.get("priority")), "received_at": t.get("received_at"),
            "closed_at": t.get("closed_at"), "cause": t.get("cause"), "assigned_team": t.get("assigned_team"),
            "route_name": t.get("route_name"),
            "overdue": bool((t.get("wait") or {}).get("overdue"))}})
    return {"network": {"type": "FeatureCollection", "features": feats},
            "tickets": {"type": "FeatureCollection", "features": tickets}}


# ---------------------------------------------------------------- alerts
@app.get("/api/alerts")
def alerts(unseen_only: bool = False, conn=Depends(get_conn)):
    sql = "SELECT * FROM alert_events" + (" WHERE seen_at IS NULL" if unseen_only else "")
    items = db.rows(conn, sql + " ORDER BY id DESC LIMIT 100")
    for i in items:
        i["payload"] = json.loads(i.pop("payload_json"))
    return items


class AlertAckIn(BaseModel):
    ticket_id: Optional[int] = None


@app.post("/api/alerts/{aid}/ack")
def ack_alert(aid: int, body: AlertAckIn = Body(default=AlertAckIn()), conn=Depends(get_conn)):
    row = db.one(conn, "SELECT * FROM alert_events WHERE id=?", (aid,))
    if not row:
        _404("التنبيه")
    conn.execute("UPDATE alert_events SET seen_at=? WHERE id=?", (db.now(), aid))
    tid = body.ticket_id or row.get("ticket_id")
    sync.send_command("ack_alert", conn=conn, alert_key=row["dedupe_key"], ticket_id=tid)
    return {"ok": True}


# ---------------------------------------------------------------- commander commands
class NeedCmd(BaseModel):
    ticket_id: int
    need_id: int
    availability: str


@app.post("/api/commands/availability")
def cmd_availability(body: NeedCmd, conn=Depends(get_conn)):
    if body.availability not in AVAILABILITY:
        raise HTTPException(400, "حالة الإتاحة غير صالحة")
    ok, data = sync.send_command("set_need_availability", conn=conn, ticket_id=body.ticket_id,
                                 need_id=body.need_id, availability=body.availability)
    if not ok:
        raise HTTPException(502, "تعذر تنفيذ الأمر على محطة المشروعات — تأكد من الاتصال")
    return {"ok": True, "ticket": data.get("ticket")}


class PriorityCmd(BaseModel):
    ticket_id: int
    priority: str


@app.post("/api/commands/priority")
def cmd_priority(body: PriorityCmd, conn=Depends(get_conn)):
    if body.priority not in PRIORITIES:
        raise HTTPException(400, "درجة الأهمية غير صالحة")
    ok, data = sync.send_command("set_priority", conn=conn, ticket_id=body.ticket_id, priority=body.priority)
    if not ok:
        raise HTTPException(502, "تعذر تنفيذ الأمر على محطة المشروعات — تأكد من الاتصال")
    return {"ok": True, "ticket": data.get("ticket")}


class DirectiveCmd(BaseModel):
    ticket_id: Optional[int] = None
    message: str = Field(..., min_length=3, max_length=1000)


@app.post("/api/commands/directive")
def cmd_directive(body: DirectiveCmd, conn=Depends(get_conn)):
    ok, data = sync.send_command("directive", conn=conn, ticket_id=body.ticket_id, message=body.message.strip())
    if not ok:
        raise HTTPException(502, "تعذر إرسال التوجيه إلى محطة المشروعات — تأكد من الاتصال")
    return {"ok": True, "directive": data.get("directive")}


class SeenCmd(BaseModel):
    ticket_id: int


@app.post("/api/commands/seen")
def cmd_seen(body: SeenCmd, conn=Depends(get_conn)):
    ok, data = sync.send_command("seen", conn=conn, ticket_id=body.ticket_id)
    return {"ok": bool(ok)}


@app.get("/api/commands/log")
def commands_log(limit: int = Query(100, le=500), conn=Depends(get_conn)):
    items = db.rows(conn, "SELECT * FROM command_log ORDER BY id DESC LIMIT ?", (limit,))
    for i in items:
        for k in ("request_json", "response_json"):
            try:
                i[k[:-5] if k.endswith("_json") else k] = json.loads(i.pop(k) or "null")
            except Exception:
                i[k] = None
    return items


# ---------------------------------------------------------------- live events (SSE)
@app.get("/api/events")
def events(request: Request):
    q = sync.subscribe()

    async def stream():
        try:
            yield "data: {\"type\":\"hello\"}\n\n"
            last_ping = 0.0
            import asyncio, time
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = q.get_nowait()
                    yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    await asyncio.sleep(0.4)
                now = time.time()
                if now - last_ping > 15:
                    last_ping = now
                    yield ": ping\n\n"
        finally:
            sync.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------- static UI
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
