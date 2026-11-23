import json
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import unquote

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import config, db, detection, estimation, geo, seed, workflow
from .textnorm import normalize
from .workflow import FAX_TYPES, PRIORITIES, STATUS_LABELS

@asynccontextmanager
async def lifespan(_app):
    seed.ensure_database()
    yield


app = FastAPI(title="محطة قسم المشروعات", docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

AVAILABILITY = {"available": "متاح", "needs_approval": "يحتاج تصديق", "shortage": "عجز"}
KINDS = {"route": "مسار كابل", "splice": "وصلة", "checkpoint": "غرفة تفتيش", "junction": "نقطة ربط", "exchange": "عقدة / سنترال"}
TEAM_STATUS = {"available": "متاح", "on_mission": "في مأمورية بالموقع", "off_duty": "خارج الخدمة"}


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


def actor(request: Request) -> str:
    return unquote(request.headers.get("X-Operator", "")) or "مشغل المشروعات"


@app.exception_handler(workflow.TransitionError)
def _transition_err(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(ValueError)
def _value_err(_, exc):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


def _404(what="العنصر"):
    raise HTTPException(404, f"{what} غير موجود")


def _catalog(conn):
    return {r["code"]: dict(r) for r in conn.execute("SELECT * FROM equipment_catalog")}


# ---------------------------------------------------------------- meta / settings
@app.get("/api/meta")
def meta(conn=Depends(get_conn)):
    s = db.get_settings(conn)
    cables = db.rows(conn, "SELECT code, name FROM equipment_catalog WHERE category='cable' ORDER BY id")
    return {
        "statuses": workflow.STATUSES,
        "transitions": workflow.TRANSITIONS,
        "fax_types": FAX_TYPES,
        "priorities": PRIORITIES,
        "task_natures": estimation.TASK_NATURES,
        "terrains": estimation.TERRAINS,
        "availability": AVAILABILITY,
        "kinds": KINDS,
        "team_status": TEAM_STATUS,
        "cable_types": cables,
        "settings": s,
        "device": db.DEVICE,
    }


@app.get("/api/settings")
def list_settings(conn=Depends(get_conn)):
    out = db.rows(conn, "SELECT * FROM settings ORDER BY sort")
    for r in out:
        r["value"] = json.loads(r["value"])
    return out


@app.put("/api/settings")
def update_settings(values: dict = Body(...), conn=Depends(get_conn), who: str = Depends(actor)):
    current = {r["key"]: r for r in db.rows(conn, "SELECT * FROM settings")}
    for k, v in values.items():
        if k not in current:
            raise HTTPException(400, f"إعداد غير معروف: {k}")
        old = json.loads(current[k]["value"])
        if isinstance(old, (int, float)) and not isinstance(old, bool):
            try:
                v = float(v)
            except (TypeError, ValueError):
                raise HTTPException(400, f"قيمة غير صالحة للإعداد «{current[k]['label']}»")
            if v < 0:
                raise HTTPException(400, f"قيمة سالبة غير مسموحة للإعداد «{current[k]['label']}»")
            v = int(v) if float(v).is_integer() and isinstance(old, int) else v
        if v != old:
            conn.execute("UPDATE settings SET value=? WHERE key=?", (json.dumps(v, ensure_ascii=False), k))
            db._audit(conn, "UPDATE", "settings", None, {k: old}, {k: v}, who)
    s = db.get_settings(conn)
    if float(s["reserve_pct_min"]) > float(s["reserve_pct_max"]):
        raise HTTPException(400, "أقل نسبة احتياطي يجب ألا تتجاوز أعلى نسبة")
    return list_settings(conn)


# ---------------------------------------------------------------- tickets
def _enrich(conn, t: dict, settings=None) -> dict:
    settings = settings or db.get_settings(conn)
    t["type_label"] = FAX_TYPES.get(t["fax_type"])
    t["status_label"] = STATUS_LABELS.get(t["status"])
    t["priority_label"] = PRIORITIES.get(t["priority"])
    t["geometry"] = json.loads(t["geometry_json"]) if t.get("geometry_json") else None
    t["wait"] = workflow.wait_info(t, float(settings["coordination_max_hours"]))
    t["allowed_next"] = workflow.allowed_next(t["status"])
    needs = conn.execute("SELECT availability, COUNT(*) c FROM ticket_needs WHERE ticket_id=? GROUP BY availability", (t["id"],)).fetchall()
    counts = {r["availability"]: r["c"] for r in needs}
    t["needs_counts"] = counts
    t["needs_status"] = "shortage" if counts.get("shortage") else "needs_approval" if counts.get("needs_approval") else "available" if counts else None
    t["has_estimate"] = bool(conn.execute("SELECT 1 FROM estimates_project WHERE ticket_id=?", (t["id"],)).fetchone())
    t["has_file"] = bool(t.get("original_file"))
    if t.get("route_id"):
        r = db.one(conn, "SELECT code, name FROM routes_sites WHERE id=?", (t["route_id"],))
        t["route_code"], t["route_name"] = (r["code"], r["name"]) if r else (None, None)
    else:
        t["route_code"] = t["route_name"] = None
    t.pop("geometry_json", None)
    return t


class TicketIn(BaseModel):
    fax_no: str = Field(..., min_length=1, max_length=60)
    fax_type: str
    title: str = Field(..., min_length=3, max_length=300)
    summary: str = Field(..., min_length=3, max_length=2000)
    required_action: Optional[str] = Field(None, max_length=500)
    location_text: Optional[str] = Field(None, max_length=300)
    requesting_party: Optional[str] = Field(None, max_length=200)
    responsible_party: Optional[str] = Field(None, max_length=200)
    priority: str = "normal"
    received_at: Optional[str] = None


class TicketPatch(BaseModel):
    fax_no: Optional[str] = Field(None, min_length=1, max_length=60)
    fax_type: Optional[str] = None
    title: Optional[str] = Field(None, min_length=3, max_length=300)
    summary: Optional[str] = Field(None, min_length=3, max_length=2000)
    required_action: Optional[str] = Field(None, max_length=500)
    location_text: Optional[str] = Field(None, max_length=300)
    requesting_party: Optional[str] = Field(None, max_length=200)
    responsible_party: Optional[str] = Field(None, max_length=200)
    priority: Optional[str] = None
    route_id: Optional[int] = None
    terrain: Optional[str] = None
    assigned_team: Optional[str] = None
    cause: Optional[str] = None
    resolution: Optional[str] = None


def _validate_ticket_fields(d: dict):
    if "fax_type" in d and d["fax_type"] not in FAX_TYPES:
        raise HTTPException(400, "نوع الفاكس غير صالح")
    if "priority" in d and d["priority"] not in PRIORITIES:
        raise HTTPException(400, "درجة الأهمية غير صالحة")
    if d.get("terrain") and d["terrain"] not in estimation.TERRAINS:
        raise HTTPException(400, "نوع الأرض غير صالح")
    if d.get("received_at"):
        try:
            d["received_at"] = datetime.fromisoformat(d["received_at"].replace("T", " ")).replace(microsecond=0).isoformat(sep=" ")
        except ValueError:
            raise HTTPException(400, "تاريخ الورود غير صالح")


@app.get("/api/tickets")
def list_tickets(
    status: Optional[str] = None,
    fax_type: Optional[str] = None,
    priority: Optional[str] = None,
    route_id: Optional[int] = None,
    q: Optional[str] = None,
    scope: str = "active",
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = Query(500, le=2000),
    conn=Depends(get_conn),
):
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
    if route_id:
        where.append("route_id = ?"); params.append(route_id)
    if date_from:
        where.append("received_at >= ?"); params.append(date_from)
    if date_to:
        where.append("received_at <= ?"); params.append(date_to + " 23:59:59")
    sql = "SELECT * FROM faxes_tickets" + (" WHERE " + " AND ".join(where) if where else "")
    sql += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, received_at DESC"
    items = db.rows(conn, sql, params)
    if q:
        nq = normalize(q)
        items = [t for t in items if nq in normalize(" ".join(str(t.get(k) or "") for k in (
            "fax_no", "title", "summary", "location_text", "requesting_party", "cause", "resolution", "assigned_team")))]
    s = db.get_settings(conn)
    return [_enrich(conn, t, s) for t in items[:limit]]


@app.post("/api/tickets")
def create_ticket(body: TicketIn, conn=Depends(get_conn), who: str = Depends(actor)):
    d = body.model_dump()
    _validate_ticket_fields(d)
    d["fax_no"] = d["fax_no"].strip()
    if conn.execute("SELECT 1 FROM faxes_tickets WHERE fax_no=?", (d["fax_no"],)).fetchone():
        raise HTTPException(409, "رقم الفاكس مسجل من قبل")
    t = db.now()
    d.update(received_at=d.get("received_at") or t, status="new", status_changed_at=t, created_at=t, updated_at=t)
    tid = db.insert(conn, "faxes_tickets", d, who)
    conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                 (tid, None, "new", t, "استلام الفاكس", who))
    return get_ticket(tid, conn)


def _ticket_or_404(conn, tid):
    t = db.one(conn, "SELECT * FROM faxes_tickets WHERE id=?", (tid,))
    if not t:
        _404("الفاكس")
    return t


@app.get("/api/tickets/{tid}")
def get_ticket(tid: int, conn=Depends(get_conn)):
    t = _enrich(conn, _ticket_or_404(conn, tid))
    t["updates"] = db.rows(conn, "SELECT * FROM updates_ticket WHERE ticket_id=? ORDER BY at, id", (tid,))
    for u in t["updates"]:
        u["old_label"] = STATUS_LABELS.get(u["old_status"]) if u["old_status"] else None
        u["new_label"] = STATUS_LABELS.get(u["new_status"])
    est = db.one(conn, "SELECT * FROM estimates_project WHERE ticket_id=?", (tid,))
    if est:
        est["equipment"] = json.loads(est.pop("equipment_json") or "[]")
        est["manual_overrides"] = json.loads(est.pop("manual_overrides_json") or "{}")
    t["estimate"] = est
    t["needs"] = db.rows(conn, "SELECT * FROM ticket_needs WHERE ticket_id=? ORDER BY id", (tid,))
    return t


@app.put("/api/tickets/{tid}")
def patch_ticket(tid: int, body: TicketPatch, conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    d = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
    _validate_ticket_fields(d)
    if "fax_no" in d and d["fax_no"] != t["fax_no"] and conn.execute("SELECT 1 FROM faxes_tickets WHERE fax_no=?", (d["fax_no"],)).fetchone():
        raise HTTPException(409, "رقم الفاكس مسجل من قبل")
    if d.get("route_id") and not conn.execute("SELECT 1 FROM routes_sites WHERE id=? AND kind='route'", (d["route_id"],)).fetchone():
        raise HTTPException(400, "المسار غير موجود")
    d["updated_at"] = db.now()
    db.update(conn, "faxes_tickets", tid, d, who)
    _push_if_forwarded(conn, tid)
    return get_ticket(tid, conn)


@app.delete("/api/tickets/{tid}")
def delete_ticket(tid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    if t["forwarded_to_command"]:
        raise HTTPException(400, "لا يمكن حذف فاكس تم تمريره إلى القيادة — يمكن إغلاقه فقط")
    db.delete(conn, "faxes_tickets", tid, who)
    if t.get("original_file"):
        p = config.UPLOAD_DIR / t["original_file"]
        if p.exists():
            p.unlink()
    return {"ok": True}


class LocationIn(BaseModel):
    geometry: dict
    terrain: Optional[str] = None
    route_id: Optional[int] = None


@app.put("/api/tickets/{tid}/location")
def set_location(tid: int, body: LocationIn, conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    g = geo.validate(body.geometry)
    s = db.get_settings(conn)
    det = detection.run(conn, g, s, ticket_id=tid, fax_type=t["fax_type"])
    upd = {"geometry_json": json.dumps(g), "lat": det["lat"], "lon": det["lon"], "updated_at": db.now()}
    if body.terrain:
        if body.terrain not in estimation.TERRAINS:
            raise HTTPException(400, "نوع الأرض غير صالح")
        upd["terrain"] = body.terrain
    if body.route_id is not None:
        upd["route_id"] = body.route_id or None
    elif det["suggested_route_id"] and not t.get("route_id"):
        upd["route_id"] = det["suggested_route_id"]
    db.update(conn, "faxes_tickets", tid, upd, who)
    _push_if_forwarded(conn, tid)
    out = get_ticket(tid, conn)
    out["detection"] = det
    out["length_m"] = round(geo.length_m(g), 1)
    return out


@app.delete("/api/tickets/{tid}/location")
def clear_location(tid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    _ticket_or_404(conn, tid)
    db.update(conn, "faxes_tickets", tid, {"geometry_json": None, "lat": None, "lon": None, "updated_at": db.now()}, who)
    _push_if_forwarded(conn, tid)
    return get_ticket(tid, conn)


@app.get("/api/tickets/{tid}/detect")
def detect_ticket(tid: int, conn=Depends(get_conn)):
    t = _ticket_or_404(conn, tid)
    if not t.get("geometry_json"):
        return {"alerts": [], "suggested_route_id": None}
    return detection.run(conn, t["geometry_json"], db.get_settings(conn), ticket_id=tid, fax_type=t["fax_type"])


@app.post("/api/detect")
def detect_any(payload: dict = Body(...), conn=Depends(get_conn)):
    return detection.run(conn, payload.get("geometry"), db.get_settings(conn), ticket_id=payload.get("ticket_id"),
                         fax_type=payload.get("fax_type"))


class StatusIn(BaseModel):
    status: str
    notes: Optional[str] = Field(None, max_length=1000)
    assigned_team: Optional[str] = None
    cause: Optional[str] = None
    resolution: Optional[str] = None


@app.post("/api/tickets/{tid}/status")
def change_status(tid: int, body: StatusIn, conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    payload = body.model_dump()
    workflow.check_transition(t, body.status, payload)
    now = db.now()
    upd = {"status": body.status, "status_changed_at": now, "updated_at": now}
    for k in ("assigned_team", "cause", "resolution"):
        if payload.get(k):
            upd[k] = payload[k].strip()
    if body.status == "closed":
        upd["closed_at"] = now
    db.update(conn, "faxes_tickets", tid, upd, who)
    team = upd.get("assigned_team") or t.get("assigned_team")
    if team and body.status == "in_progress":
        conn.execute("UPDATE teams_personnel SET status='on_mission', current_ticket_id=?, updated_at=? WHERE team_name=?", (tid, now, team))
    if team and body.status == "closed":
        conn.execute("UPDATE teams_personnel SET status='available', current_ticket_id=NULL, updated_at=? WHERE team_name=? AND current_ticket_id=?", (now, team, tid))
    conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                 (tid, t["status"], body.status, now, body.notes, who))
    if t["forwarded_to_command"]:
        _push_outbox(conn, tid, "status")
    return get_ticket(tid, conn)


@app.post("/api/tickets/{tid}/notes")
def add_note(tid: int, payload: dict = Body(...), conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    note = (payload.get("notes") or "").strip()
    if not note:
        raise HTTPException(400, "الملاحظة فارغة")
    conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                 (tid, t["status"], t["status"], db.now(), note[:1000], who))
    return get_ticket(tid, conn)


# ---------------------------------------------------------------- original fax file
_SAFE = re.compile(r"[^\w.\-]+", re.UNICODE)


@app.post("/api/tickets/{tid}/file")
async def upload_file(tid: int, file: UploadFile = File(...), conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in config.ALLOWED_UPLOAD_EXT:
        raise HTTPException(400, "نوع الملف غير مدعوم (PDF أو صورة فقط)")
    data = await file.read(config.MAX_UPLOAD_BYTES + 1)
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(400, "حجم الملف أكبر من 25 ميجابايت")
    if not data:
        raise HTTPException(400, "الملف فارغ")
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{tid}_{datetime.now():%Y%m%d%H%M%S}{ext}"
    (config.UPLOAD_DIR / name).write_bytes(data)
    if t.get("original_file") and (config.UPLOAD_DIR / t["original_file"]).exists():
        (config.UPLOAD_DIR / t["original_file"]).unlink()
    db.update(conn, "faxes_tickets", tid, {"original_file": name, "original_filename": _SAFE.sub("_", file.filename or name),
                                           "updated_at": db.now()}, who)
    _push_if_forwarded(conn, tid)
    return get_ticket(tid, conn)


@app.post("/api/files/extract-text")
async def extract_text(file: UploadFile = File(None), ticket_id: Optional[int] = Form(None),
                       conn=Depends(get_conn)):
    """Extract readable text from an attached fax PDF (text-based PDFs only)."""
    data, filename = None, ""
    if ticket_id:
        t = _ticket_or_404(conn, ticket_id)
        if not t.get("original_file"):
            raise HTTPException(404, "لا يوجد ملف مرفق بهذه العملية")
        p = config.UPLOAD_DIR / t["original_file"]
        if not p.exists():
            raise HTTPException(404, "ملف الفاكس غير موجود على القرص")
        data, filename = p.read_bytes(), t.get("original_filename") or p.name
    else:
        if file is None:
            raise HTTPException(400, "أرفق ملفًا أو حدد رقم العملية")
        data = await file.read(config.MAX_UPLOAD_BYTES + 1)
        filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            texts, total = [], 0
            for page in reader.pages[:10]:
                txt = page.extract_text() or ""
                texts.append(txt)
                total += len(txt)
                if total > 8000:
                    break
            text = "\n".join(texts).strip()
            return {"ok": True, "kind": "pdf", "pages": len(reader.pages),
                    "chars": len(text), "text": text[:8000]}
        except ImportError:
            return {"ok": False, "kind": "pdf",
                    "message": "مكتبة استخراج النص (pypdf) غير مثبتة — أعد تشغيل برنامج التثبيت"}
        except Exception as e:
            return {"ok": False, "kind": "pdf",
                    "message": f"تعذر استخراج النص — غالبًا الملف صورة ممسوحة ضوئيًا بدون طبقة نصية ({e})"}
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif", ".webp"}:
        return {"ok": False, "kind": "image",
                "message": "ملف صورة — لا يمكن استخراج النص برمجيًا بدون محرك OCR. أرفقه واستكمل الإدخال اليدوي."}
    raise HTTPException(400, "نوع الملف غير مدعوم")


@app.get("/api/tickets/{tid}/file")
def get_file(tid: int, conn=Depends(get_conn)):
    t = _ticket_or_404(conn, tid)
    if not t.get("original_file"):
        _404("ملف الفاكس")
    p = (config.UPLOAD_DIR / t["original_file"]).resolve()
    if config.UPLOAD_DIR.resolve() not in p.parents or not p.exists():
        _404("ملف الفاكس")
    return FileResponse(p, filename=t.get("original_filename") or p.name, content_disposition_type="inline")


# ---------------------------------------------------------------- estimation
def _estimate_inputs(conn, t, payload):
    inputs = dict(payload)
    g = t.get("geometry_json")
    if inputs.get("measured_length_m") in (None, "") and g:
        inputs["measured_length_m"] = round(geo.length_m(g), 1)
        inputs["length_source"] = "map"
    elif inputs.get("measured_length_m") not in (None, ""):
        inputs.setdefault("length_source", "manual")
    inputs.setdefault("terrain", t.get("terrain") or "open")
    if not inputs.get("cable_type") and t.get("route_id"):
        r = db.one(conn, "SELECT cable_type FROM routes_sites WHERE id=?", (t["route_id"],))
        if r and r["cable_type"]:
            inputs["cable_type"] = r["cable_type"]
    if not inputs.get("task_nature"):
        inputs["task_nature"] = {"fault": "fault_repair", "project": "cable_laying"}.get(t["fax_type"], "measurement")
    pt = geo.representative_point(g) if g else None
    return inputs, pt


@app.post("/api/tickets/{tid}/estimate/preview")
def preview_estimate(tid: int, payload: dict = Body(default={}), conn=Depends(get_conn)):
    t = _ticket_or_404(conn, tid)
    inputs, pt = _estimate_inputs(conn, t, payload)
    return estimation.compute(inputs, db.get_settings(conn), _catalog(conn), pt)


@app.put("/api/tickets/{tid}/estimate")
def save_estimate(tid: int, payload: dict = Body(default={}), conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    inputs, pt = _estimate_inputs(conn, t, payload)
    r = estimation.compute(inputs, db.get_settings(conn), _catalog(conn), pt)
    now = db.now()
    data = dict(
        measured_length_m=r["measured_length_m"], length_source=r["length_source"], cable_type=r["cable_type"],
        fiber_count=r["fiber_count"], task_nature=r["task_nature"], terrain=r["terrain"], reserve_pct=r["reserve_pct"],
        total_cable_m=r["total_cable_m"], splice_closures=r["splice_closures"], fusion_splices=r["fusion_splices"],
        connection_points=r["connection_points"], media_converters=r["media_converters"],
        equipment_json=json.dumps(r["equipment"], ensure_ascii=False), travel_hours=r["travel_hours"],
        laying_hours=r["laying_hours"], splicing_hours=r["splicing_hours"], testing_hours=r["testing_hours"],
        difficulty_factor=r["difficulty_factor"], estimated_hours=r["estimated_hours"], estimated_days=r["estimated_days"],
        manual_overrides_json=json.dumps(r["manual_overrides"], ensure_ascii=False), notes=payload.get("notes"), updated_at=now,
    )
    existing = db.one(conn, "SELECT id FROM estimates_project WHERE ticket_id=?", (tid,))
    if existing:
        db.update(conn, "estimates_project", existing["id"], data, who)
    else:
        db.insert(conn, "estimates_project", {**data, "ticket_id": tid, "computed_at": now}, who)
    if r["terrain"] != t.get("terrain"):
        db.update(conn, "faxes_tickets", tid, {"terrain": r["terrain"], "updated_at": now}, who)
    if payload.get("generate_needs"):
        _generate_needs(conn, tid, r["equipment"], who)
    _push_if_forwarded(conn, tid, "estimate")
    out = get_ticket(tid, conn)
    out["estimate_result"] = r
    return out


# ---------------------------------------------------------------- needs
def _generate_needs(conn, tid, equipment, who):
    for n in db.rows(conn, "SELECT id FROM ticket_needs WHERE ticket_id=?", (tid,)):
        db.delete(conn, "ticket_needs", n["id"], who)
    now = db.now()
    for e in equipment:
        db.insert(conn, "ticket_needs", dict(ticket_id=tid, item_name=e["name"], category=e["category"], quantity=e["quantity"],
                                             unit=e["unit"], availability=e["availability"], notes=e["reason"],
                                             created_at=now, updated_at=now), who)


@app.post("/api/tickets/{tid}/needs/generate")
def generate_needs(tid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    _ticket_or_404(conn, tid)
    est = db.one(conn, "SELECT equipment_json FROM estimates_project WHERE ticket_id=?", (tid,))
    if not est:
        raise HTTPException(400, "احسب التقدير الفني أولًا")
    _generate_needs(conn, tid, json.loads(est["equipment_json"] or "[]"), who)
    _push_if_forwarded(conn, tid, "needs")
    return get_ticket(tid, conn)


class NeedIn(BaseModel):
    item_name: Optional[str] = Field(None, min_length=1, max_length=200)
    category: Optional[str] = None
    quantity: Optional[float] = Field(None, ge=0)
    unit: Optional[str] = None
    availability: Optional[str] = None
    notes: Optional[str] = None


def _check_need(d):
    if d.get("availability") and d["availability"] not in AVAILABILITY:
        raise HTTPException(400, "حالة الإتاحة غير صالحة")


@app.post("/api/tickets/{tid}/needs")
def add_need(tid: int, body: NeedIn, conn=Depends(get_conn), who: str = Depends(actor)):
    _ticket_or_404(conn, tid)
    d = body.model_dump()
    if not d.get("item_name"):
        raise HTTPException(400, "اسم البند مطلوب")
    _check_need(d)
    now = db.now()
    d.update(ticket_id=tid, quantity=d.get("quantity") or 1, availability=d.get("availability") or "needs_approval",
             created_at=now, updated_at=now)
    db.insert(conn, "ticket_needs", d, who)
    _push_if_forwarded(conn, tid, "needs")
    return get_ticket(tid, conn)


@app.put("/api/needs/{nid}")
def update_need(nid: int, body: NeedIn, conn=Depends(get_conn), who: str = Depends(actor)):
    n = db.one(conn, "SELECT * FROM ticket_needs WHERE id=?", (nid,))
    if not n:
        _404("البند")
    d = body.model_dump(exclude_unset=True)
    _check_need(d)
    d["updated_at"] = db.now()
    db.update(conn, "ticket_needs", nid, d, who)
    _push_if_forwarded(conn, n["ticket_id"], "needs")
    return get_ticket(n["ticket_id"], conn)


@app.delete("/api/needs/{nid}")
def delete_need(nid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    n = db.one(conn, "SELECT * FROM ticket_needs WHERE id=?", (nid,))
    if not n:
        _404("البند")
    db.delete(conn, "ticket_needs", nid, who)
    _push_if_forwarded(conn, n["ticket_id"], "needs")
    return get_ticket(n["ticket_id"], conn)


# ---------------------------------------------------------------- forward to command (part 2 consumes this)
def _push_outbox(conn, tid, reason):
    snap = get_ticket(tid, conn)
    snap["detection"] = detect_ticket(tid, conn) if snap.get("geometry") else {"alerts": []}
    conn.execute("INSERT INTO command_outbox(ticket_id, payload_json, created_at) VALUES (?,?,?)",
                 (tid, json.dumps({"reason": reason, "ticket": snap}, ensure_ascii=False, default=str), db.now()))


def _push_if_forwarded(conn, tid, reason="update"):
    t = db.one(conn, "SELECT forwarded_to_command FROM faxes_tickets WHERE id=?", (tid,))
    if t and t["forwarded_to_command"]:
        _push_outbox(conn, tid, reason)


@app.post("/api/tickets/{tid}/forward")
def forward(tid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    t = _ticket_or_404(conn, tid)
    missing = []
    if not t.get("geometry_json"):
        missing.append("تحديد الموقع على الخريطة")
    if not (t.get("summary") or "").strip():
        missing.append("الملخص التنفيذي")
    if missing:
        raise HTTPException(400, "لا يمكن التمرير قبل: " + "، ".join(missing))
    now = db.now()
    db.update(conn, "faxes_tickets", tid, {"forwarded_to_command": 1, "forwarded_at": now, "updated_at": now}, who)
    conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                 (tid, t["status"], t["status"], now, "حفظ وتمرير إلى القيادة", who))
    _push_outbox(conn, tid, "forward")
    return get_ticket(tid, conn)


@app.get("/api/command/feed")
def command_feed(since_id: int = 0, limit: int = Query(100, le=500), conn=Depends(get_conn)):
    items = db.rows(conn, "SELECT * FROM command_outbox WHERE id > ? ORDER BY id LIMIT ?", (since_id, limit))
    for i in items:
        i["payload"] = json.loads(i.pop("payload_json"))
    return items


@app.post("/api/command/ack/{oid}")
def command_ack(oid: int, conn=Depends(get_conn)):
    conn.execute("UPDATE command_outbox SET delivered_at=? WHERE id=? AND delivered_at IS NULL", (db.now(), oid))
    return {"ok": True}


# ---------------------------------------------------------------- commander commands (consumed by part 2)
class CommandIn(BaseModel):
    action: str
    ticket_id: Optional[int] = None
    need_id: Optional[int] = None
    availability: Optional[str] = None
    priority: Optional[str] = None
    message: Optional[str] = None
    alert_key: Optional[str] = None
    device: Optional[str] = Field(None, max_length=120)


def _command_actor(body: CommandIn) -> str:
    return "شاشة القائد" + (f" ({body.device})" if body.device else "")


@app.post("/api/command/inbox")
def command_inbox(body: CommandIn, conn=Depends(get_conn)):
    who = _command_actor(body)
    if body.action == "set_need_availability":
        n = db.one(conn, "SELECT * FROM ticket_needs WHERE id=?", (body.need_id,)) if body.need_id else None
        if not n:
            _404("البند")
        if body.availability not in AVAILABILITY:
            raise HTTPException(400, "حالة الإتاحة غير صالحة")
        db.update(conn, "ticket_needs", n["id"], {"availability": body.availability, "updated_at": db.now()}, who)
        _push_if_forwarded(conn, n["ticket_id"], "command")
        return {"ok": True, "ticket": get_ticket(n["ticket_id"], conn)}
    if body.action == "set_priority":
        if not body.ticket_id:
            raise HTTPException(400, "رقم الفاكس مطلوب")
        t = _ticket_or_404(conn, body.ticket_id)
        if body.priority not in PRIORITIES:
            raise HTTPException(400, "درجة الأهمية غير صالحة")
        db.update(conn, "faxes_tickets", t["id"], {"priority": body.priority, "updated_at": db.now()}, who)
        _push_if_forwarded(conn, t["id"], "command")
        return {"ok": True, "ticket": get_ticket(t["id"], conn)}
    if body.action == "directive":
        msg = (body.message or "").strip()
        if len(msg) < 3:
            raise HTTPException(400, "نص التوجيه مطلوب")
        t = _ticket_or_404(conn, body.ticket_id) if body.ticket_id else None
        now = db.now()
        did = db.insert(conn, "command_directives",
                        dict(ticket_id=body.ticket_id, message=msg[:1000], actor=who, at=now, delivered_at=None), who)
        if t:
            db.update(conn, "faxes_tickets", t["id"],
                      {"command_seen_at": now, "command_seen_by": who, "updated_at": now}, who)
            conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                         (t["id"], t["status"], t["status"], now, f"توجيه من القيادة: {msg[:300]}", who))
            _push_if_forwarded(conn, t["id"], "directive")
        d = db.one(conn, "SELECT * FROM command_directives WHERE id=?", (did,))
        return {"ok": True, "directive": d}
    if body.action == "ack_alert":
        key = (body.alert_key or "").strip()
        if not key:
            raise HTTPException(400, "مفتاح التنبيه مطلوب")
        db.insert(conn, "command_alert_acks",
                  dict(alert_key=key[:200], ticket_id=body.ticket_id, actor=who, at=db.now()), who)
        return {"ok": True}
    if body.action == "seen":
        if not body.ticket_id:
            raise HTTPException(400, "رقم الفاكس مطلوب")
        t = _ticket_or_404(conn, body.ticket_id)
        now = db.now()
        db.update(conn, "faxes_tickets", t["id"],
                  {"command_seen_at": now, "command_seen_by": who, "updated_at": now}, who)
        return {"ok": True, "ticket": get_ticket(t["id"], conn)}
    raise HTTPException(400, "أمر قيادة غير معروف")


@app.get("/api/command/directives")
def command_directives(since_id: int = 0, limit: int = Query(100, le=500), conn=Depends(get_conn)):
    items = db.rows(conn, "SELECT * FROM command_directives WHERE id > ? ORDER BY id LIMIT ?", (since_id, limit))
    if items:
        conn.execute("UPDATE command_directives SET delivered_at=? WHERE id > ? AND delivered_at IS NULL",
                     (db.now(), since_id))
    return items


# ---------------------------------------------------------------- dashboard & alerts
def _global_alerts(conn, s):
    alerts = []
    max_h = float(s["coordination_max_hours"])
    for t in db.rows(conn, "SELECT * FROM faxes_tickets WHERE status='awaiting_coordination'"):
        w = workflow.wait_info(t, max_h)
        if w["overdue"]:
            alerts.append({"severity": "warning", "type": "coordination_delay", "ticket_id": t["id"],
                           "title": f"تأخر رد التنسيق — {t['fax_no']}",
                           "message": f"{t.get('requesting_party') or ''}: في الانتظار منذ {w['hours_in_status']:.0f} ساعة (الحد {max_h:.0f} ساعة)"})
    for t in db.rows(conn, "SELECT * FROM faxes_tickets WHERE status='new' AND priority='critical'"):
        alerts.append({"severity": "urgent", "type": "critical_new", "ticket_id": t["id"], "title": f"فاكس حرج لم يُعالج — {t['fax_no']}",
                       "message": t["title"]})
    for t in db.rows(conn, "SELECT * FROM faxes_tickets WHERE status!='closed' AND fax_type='fault' AND geometry_json IS NOT NULL"):
        det = detection.run(conn, t["geometry_json"], s, ticket_id=t["id"], fax_type="fault")
        for a in det["alerts"]:
            if a["type"] == "repeat_fault":
                alerts.append({"severity": "urgent", "type": "repeat_fault", "ticket_id": t["id"],
                               "title": f"{a['title']} — {t['fax_no']}", "message": a["message"]})
    for n in db.rows(conn, "SELECT t.id, t.fax_no, COUNT(*) c FROM ticket_needs n JOIN faxes_tickets t ON t.id=n.ticket_id"
                           " WHERE n.availability='shortage' AND t.status!='closed' GROUP BY t.id"):
        alerts.append({"severity": "warning", "type": "shortage", "ticket_id": n["id"], "title": f"عجز في الاحتياجات — {n['fax_no']}",
                       "message": f"{n['c']} بند في حالة عجز"})
    order = {"urgent": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: order[a["severity"]])
    return alerts


@app.get("/api/alerts")
def alerts(conn=Depends(get_conn)):
    return _global_alerts(conn, db.get_settings(conn))


@app.get("/api/dashboard")
def dashboard(conn=Depends(get_conn)):
    s = db.get_settings(conn)
    c = lambda sql, p=(): conn.execute(sql, p).fetchone()[0]  # noqa: E731
    month = datetime.now().strftime("%Y-%m")
    by_status = {k: c("SELECT COUNT(*) FROM faxes_tickets WHERE status=?", (k,)) for k, _ in workflow.STATUSES}
    by_type = {k: c("SELECT COUNT(*) FROM faxes_tickets WHERE status!='closed' AND fax_type=?", (k,)) for k in FAX_TYPES}
    al = _global_alerts(conn, s)
    teams = db.rows(conn, "SELECT team_name, CASE WHEN SUM(status='on_mission') > 0 THEN 'on_mission' WHEN SUM(status='available') > 0"
                          " THEN 'available' ELSE 'off_duty' END status, COUNT(*) members FROM teams_personnel GROUP BY team_name")
    return {
        "by_status": by_status,
        "by_type": by_type,
        "critical_open": c("SELECT COUNT(*) FROM faxes_tickets WHERE status!='closed' AND priority='critical'"),
        "overdue": sum(1 for a in al if a["type"] == "coordination_delay"),
        "closed_this_month": c("SELECT COUNT(*) FROM faxes_tickets WHERE status='closed' AND closed_at LIKE ?", (month + "%",)),
        "not_forwarded": c("SELECT COUNT(*) FROM faxes_tickets WHERE status!='closed' AND forwarded_to_command=0"),
        "routes": c("SELECT COUNT(*) FROM routes_sites WHERE kind='route'"),
        "routes_km": round((c("SELECT COALESCE(SUM(length_m),0) FROM routes_sites WHERE kind='route'") or 0) / 1000, 1),
        "teams": teams,
        "alerts": al,
        "recent_updates": db.rows(conn, "SELECT u.*, t.fax_no, t.title FROM updates_ticket u JOIN faxes_tickets t ON t.id=u.ticket_id"
                                        " ORDER BY u.at DESC, u.id DESC LIMIT 12"),
    }


# ---------------------------------------------------------------- map data
@app.get("/api/map/layers")
def map_layers(conn=Depends(get_conn)):
    feats = []
    for r in db.rows(conn, "SELECT * FROM routes_sites"):
        feats.append({"type": "Feature", "geometry": json.loads(r.pop("geometry_json")),
                      "properties": {**r, "layer": "route" if r["kind"] == "route" else "site", "kind_label": KINDS.get(r["kind"])}})
    s = db.get_settings(conn)
    tickets = []
    for t in db.rows(conn, "SELECT * FROM faxes_tickets WHERE geometry_json IS NOT NULL"):
        g = json.loads(t["geometry_json"])
        tickets.append({"type": "Feature", "geometry": g, "properties": {
            "id": t["id"], "fax_no": t["fax_no"], "title": t["title"], "fax_type": t["fax_type"], "type_label": FAX_TYPES[t["fax_type"]],
            "status": t["status"], "status_label": STATUS_LABELS[t["status"]], "priority": t["priority"],
            "priority_label": PRIORITIES[t["priority"]], "received_at": t["received_at"], "closed_at": t["closed_at"],
            "cause": t["cause"], "assigned_team": t["assigned_team"],
            "overdue": workflow.wait_info(t, float(s["coordination_max_hours"]))["overdue"]}})
    return {"network": {"type": "FeatureCollection", "features": feats},
            "tickets": {"type": "FeatureCollection", "features": tickets}}


@app.get("/api/search")
def search(q: str = Query(..., min_length=1), limit: int = Query(15, le=50), conn=Depends(get_conn)):
    nq = normalize(q)
    out = []
    for r in db.rows(conn, "SELECT id, code, name, kind, lat, lon FROM routes_sites"):
        if nq in normalize(r["code"] + " " + r["name"]):
            out.append({"type": "network", "label": f"{r['code']} — {r['name']}", "kind": KINDS[r["kind"]], "lat": r["lat"], "lon": r["lon"], "id": r["id"]})
    for t in db.rows(conn, "SELECT id, fax_no, title, lat, lon FROM faxes_tickets WHERE lat IS NOT NULL"):
        if nq in normalize(t["fax_no"] + " " + t["title"]):
            out.append({"type": "ticket", "label": f"{t['fax_no']} — {t['title']}", "kind": "فاكس", "lat": t["lat"], "lon": t["lon"], "id": t["id"]})
    rank_sql = ("SELECT name, kind, lat, lon FROM places WHERE name_norm LIKE ? ORDER BY CASE WHEN name_norm LIKE ? THEN 0 ELSE 1 END,"
                " CASE kind WHEN 'city' THEN 0 WHEN 'town' THEN 1 WHEN 'suburb' THEN 2 ELSE 3 END, length(name) LIMIT ?")
    for p in db.rows(conn, rank_sql, (f"%{nq}%", f"{nq}%", limit)):
        out.append({"type": "place", "label": p["name"], "kind": p["kind"], "lat": p["lat"], "lon": p["lon"]})
    return out[:limit]


@app.get("/api/history/near")
def history_near(lat: float, lon: float, radius: float = 300, conn=Depends(get_conn)):
    pt = {"type": "Point", "coordinates": [lon, lat]}
    out = []
    for t in db.rows(conn, "SELECT * FROM faxes_tickets WHERE geometry_json IS NOT NULL"):
        d = geo.distance_m(pt, t["geometry_json"])
        if d <= radius:
            t = _enrich(conn, t)
            t["distance_m"] = round(d)
            out.append(t)
    out.sort(key=lambda x: x["received_at"], reverse=True)
    return out


# ---------------------------------------------------------------- routes / sites (reference data)
class SiteIn(BaseModel):
    code: Optional[str] = Field(None, min_length=1, max_length=40)
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    kind: Optional[str] = None
    axis_name: Optional[str] = None
    parent_route_id: Optional[int] = None
    geometry: Optional[dict] = None
    cable_type: Optional[str] = None
    fiber_count: Optional[int] = None
    parties: Optional[str] = None
    install_year: Optional[int] = None
    notes: Optional[str] = None


def _site_data(d):
    if d.get("kind") and d["kind"] not in KINDS:
        raise HTTPException(400, "نوع العنصر غير صالح")
    if "geometry" in d:
        g = geo.validate(d.pop("geometry"))
        d["geometry_json"] = json.dumps(g)
        d["lat"], d["lon"] = geo.representative_point(g)
        d["length_m"] = round(geo.length_m(g)) if g["type"] != "Point" else None
    return d


@app.get("/api/routes")
def list_routes(kind: Optional[str] = None, conn=Depends(get_conn)):
    sql = "SELECT r.*, p.code parent_code FROM routes_sites r LEFT JOIN routes_sites p ON p.id=r.parent_route_id"
    params = ()
    if kind:
        sql += " WHERE r.kind=?"; params = (kind,)
    items = db.rows(conn, sql + " ORDER BY r.kind != 'route', r.code", params)
    for r in items:
        r["geometry"] = json.loads(r.pop("geometry_json"))
        r["kind_label"] = KINDS.get(r["kind"])
        r["faults"] = conn.execute("SELECT COUNT(*) FROM faxes_tickets WHERE route_id=? AND fax_type='fault'", (r["id"],)).fetchone()[0]
    return items


@app.post("/api/routes")
def create_route(body: SiteIn, conn=Depends(get_conn), who: str = Depends(actor)):
    d = body.model_dump()
    if not (d.get("code") and d.get("name") and d.get("kind") and d.get("geometry")):
        raise HTTPException(400, "الكود والاسم والنوع والموقع مطلوبة")
    if conn.execute("SELECT 1 FROM routes_sites WHERE code=?", (d["code"],)).fetchone():
        raise HTTPException(409, "الكود مستخدم من قبل")
    d = _site_data(d)
    if d["kind"] == "route" and json.loads(d["geometry_json"])["type"] == "Point":
        raise HTTPException(400, "المسار يجب أن يكون خطًا")
    now = db.now()
    d.update(created_at=now, updated_at=now)
    rid = db.insert(conn, "routes_sites", d, who)
    return db.one(conn, "SELECT * FROM routes_sites WHERE id=?", (rid,))


@app.put("/api/routes/{rid}")
def update_route(rid: int, body: SiteIn, conn=Depends(get_conn), who: str = Depends(actor)):
    if not db.one(conn, "SELECT id FROM routes_sites WHERE id=?", (rid,)):
        _404("العنصر")
    d = _site_data(body.model_dump(exclude_unset=True))
    if d.get("code") and conn.execute("SELECT 1 FROM routes_sites WHERE code=? AND id!=?", (d["code"], rid)).fetchone():
        raise HTTPException(409, "الكود مستخدم من قبل")
    d["updated_at"] = db.now()
    return db.update(conn, "routes_sites", rid, d, who)


@app.delete("/api/routes/{rid}")
def delete_route(rid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    if not db.one(conn, "SELECT id FROM routes_sites WHERE id=?", (rid,)):
        _404("العنصر")
    if conn.execute("SELECT 1 FROM faxes_tickets WHERE route_id=?", (rid,)).fetchone():
        raise HTTPException(400, "لا يمكن حذف مسار مرتبط بفاكسات في السجل")
    db.delete(conn, "routes_sites", rid, who)
    return {"ok": True}


# ---------------------------------------------------------------- teams
class TeamIn(BaseModel):
    name: Optional[str] = Field(None, min_length=2, max_length=120)
    rank: Optional[str] = None
    specialty: Optional[str] = None
    team_name: Optional[str] = None
    is_leader: Optional[int] = None
    status: Optional[str] = None
    phone: Optional[str] = None
    notes: Optional[str] = None


@app.get("/api/teams")
def list_teams(conn=Depends(get_conn)):
    items = db.rows(conn, "SELECT p.*, t.fax_no current_fax FROM teams_personnel p LEFT JOIN faxes_tickets t ON t.id=p.current_ticket_id"
                          " ORDER BY p.team_name, p.is_leader DESC, p.id")
    for i in items:
        i["status_label"] = TEAM_STATUS.get(i["status"])
    return items


@app.post("/api/teams")
def add_member(body: TeamIn, conn=Depends(get_conn), who: str = Depends(actor)):
    d = body.model_dump()
    if not d.get("name"):
        raise HTTPException(400, "الاسم مطلوب")
    if d.get("status") and d["status"] not in TEAM_STATUS:
        raise HTTPException(400, "الحالة غير صالحة")
    now = db.now()
    d.update(status=d.get("status") or "available", is_leader=d.get("is_leader") or 0, created_at=now, updated_at=now)
    db.insert(conn, "teams_personnel", d, who)
    return list_teams(conn)


@app.put("/api/teams/{mid}")
def update_member(mid: int, body: TeamIn, conn=Depends(get_conn), who: str = Depends(actor)):
    if not db.one(conn, "SELECT id FROM teams_personnel WHERE id=?", (mid,)):
        _404("الفرد")
    d = body.model_dump(exclude_unset=True)
    if d.get("status") and d["status"] not in TEAM_STATUS:
        raise HTTPException(400, "الحالة غير صالحة")
    d["updated_at"] = db.now()
    db.update(conn, "teams_personnel", mid, d, who)
    return list_teams(conn)


@app.delete("/api/teams/{mid}")
def delete_member(mid: int, conn=Depends(get_conn), who: str = Depends(actor)):
    if not db.one(conn, "SELECT id FROM teams_personnel WHERE id=?", (mid,)):
        _404("الفرد")
    db.delete(conn, "teams_personnel", mid, who)
    return list_teams(conn)


# ---------------------------------------------------------------- equipment catalog
class EquipIn(BaseModel):
    code: Optional[str] = Field(None, min_length=2, max_length=40)
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    category: Optional[str] = None
    unit: Optional[str] = None
    default_availability: Optional[str] = None
    guide: Optional[str] = None
    safety: Optional[str] = None


@app.get("/api/equipment")
def list_equipment(conn=Depends(get_conn)):
    return db.rows(conn, "SELECT * FROM equipment_catalog ORDER BY CASE category WHEN 'cable' THEN 0 WHEN 'material' THEN 1 WHEN 'device' THEN 2 ELSE 3 END, id")


@app.post("/api/equipment")
def add_equipment(body: EquipIn, conn=Depends(get_conn), who: str = Depends(actor)):
    d = body.model_dump()
    if not (d.get("code") and d.get("name") and d.get("category") in ("cable", "material", "device", "tool")):
        raise HTTPException(400, "الكود والاسم والفئة مطلوبة")
    if conn.execute("SELECT 1 FROM equipment_catalog WHERE code=?", (d["code"],)).fetchone():
        raise HTTPException(409, "الكود مستخدم من قبل")
    if d.get("default_availability") and d["default_availability"] not in AVAILABILITY:
        raise HTTPException(400, "حالة الإتاحة غير صالحة")
    now = db.now()
    d.update(default_availability=d.get("default_availability") or "available", created_at=now, updated_at=now)
    db.insert(conn, "equipment_catalog", d, who)
    return list_equipment(conn)


@app.put("/api/equipment/{eid}")
def update_equipment(eid: int, body: EquipIn, conn=Depends(get_conn), who: str = Depends(actor)):
    if not db.one(conn, "SELECT id FROM equipment_catalog WHERE id=?", (eid,)):
        _404("المعدة")
    d = body.model_dump(exclude_unset=True)
    d.pop("code", None)
    if d.get("default_availability") and d["default_availability"] not in AVAILABILITY:
        raise HTTPException(400, "حالة الإتاحة غير صالحة")
    d["updated_at"] = db.now()
    db.update(conn, "equipment_catalog", eid, d, who)
    return list_equipment(conn)


# ---------------------------------------------------------------- audit
@app.get("/api/audit")
def audit(table: Optional[str] = None, action: Optional[str] = None, q: Optional[str] = None,
          limit: int = Query(200, le=1000), offset: int = 0, conn=Depends(get_conn)):
    where, params = [], []
    if table:
        where.append("table_name=?"); params.append(table)
    if action:
        where.append("action=?"); params.append(action)
    if q:
        where.append("(old_value LIKE ? OR new_value LIKE ? OR actor LIKE ?)"); params += [f"%{q}%"] * 3
    sql = "SELECT * FROM logs_audit" + (" WHERE " + " AND ".join(where) if where else "")
    total = conn.execute(sql.replace("SELECT *", "SELECT COUNT(*)"), params).fetchone()[0]
    items = db.rows(conn, sql + " ORDER BY id DESC LIMIT ? OFFSET ?", (*params, limit, offset))
    return {"total": total, "items": items}


# ---------------------------------------------------------------- simulation helpers
@app.post("/api/simulate/fax")
def simulate(conn=Depends(get_conn), who: str = Depends(actor)):
    tid = seed.simulate_fax(conn, who)
    return get_ticket(tid, conn)


@app.post("/api/admin/reset-demo")
def reset_demo(payload: dict = Body(...)):
    if payload.get("confirm") != "RESET":
        raise HTTPException(400, "تأكيد غير صحيح")
    seed.ensure_database(reset=True)
    return {"ok": True}


@app.get("/api/health")
def health():
    return {"ok": True, "device": db.DEVICE, "time": db.now()}


# ---------------------------------------------------------------- static UI
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.get("/")
def index():
    return FileResponse(config.STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})
