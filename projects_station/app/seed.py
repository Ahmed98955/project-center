"""Reference data and prototype (simulation) data. All names and incidents are fictional."""
import json
import random
import shutil
from datetime import datetime, timedelta

from . import config, db, defaults, estimation, geo
from .textnorm import normalize

ACTOR = "النظام (بيانات تجريبية)"


def _ts(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat(sep=" ")


def seed_reference(conn):
    t = db.now()
    for i, (k, v, label, unit, grp) in enumerate(defaults.SETTINGS):
        conn.execute(
            "INSERT OR IGNORE INTO settings(key, value, label, unit, grp, sort) VALUES (?,?,?,?,?,?)",
            (k, json.dumps(v, ensure_ascii=False), label, unit, grp, i),
        )
    for code, name, cat, unit, avail, guide, safety in defaults.CATALOG:
        conn.execute(
            "INSERT OR IGNORE INTO equipment_catalog(code, name, category, unit, default_availability, guide, safety,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (code, name, cat, unit, avail, guide, safety, t, t),
        )
    if not conn.execute("SELECT 1 FROM places LIMIT 1").fetchone():
        places = json.load(open(config.SEED_DIR / "places.json", encoding="utf-8"))
        conn.executemany(
            "INSERT INTO places(name, name_norm, name_en, kind, lat, lon, source) VALUES (?,?,?,?,?,?, 'osm')",
            [(p["name"], normalize(p["name"]) + " " + normalize(p.get("name_en", "")), p.get("name_en"), p["kind"], p["lat"], p["lon"]) for p in places],
        )


def seed_routes(conn):
    data = json.load(open(config.SEED_DIR / "routes.json", encoding="utf-8"))
    t = db.now()
    ids = {}
    for r in data["routes"]:
        g = r["geometry"]
        lat, lon = geo.representative_point(g)
        fibers = int(r["cable_type"].rsplit("_", 1)[1]) if r["cable_type"].startswith("fiber") else None
        ids[r["code"]] = db.insert(conn, "routes_sites", dict(
            code=r["code"], name=r["name"], kind="route", axis_name=r["axis_name"], geometry_json=json.dumps(g),
            lat=lat, lon=lon, cable_type=r["cable_type"], fiber_count=fibers, length_m=r["length_m"], parties=r["parties"],
            install_year=r["install_year"], notes=None, created_at=t, updated_at=t), ACTOR, audit=False)
    for s in data["sites"]:
        g = {"type": "Point", "coordinates": [s["lon"], s["lat"]]}
        db.insert(conn, "routes_sites", dict(
            code=s["code"], name=s["name"], kind=s["kind"], axis_name=None, parent_route_id=ids.get(s["parent"]),
            geometry_json=json.dumps(g), lat=s["lat"], lon=s["lon"], created_at=t, updated_at=t), ACTOR, audit=False)
    return ids


TEAMS = [
    ("نقيب/ محمد عبد الرحمن", "نقيب", "قائد مفرزة — ألياف ضوئية", "المفرزة الأولى", 1, "on_mission"),
    ("رقيب أول/ سعيد فتحي", "رقيب أول", "فني لحام ألياف", "المفرزة الأولى", 0, "on_mission"),
    ("عريف/ أحمد سامي", "عريف", "فني مد كوابل", "المفرزة الأولى", 0, "on_mission"),
    ("نقيب/ كريم حسن", "نقيب", "قائد مفرزة — إنشاءات", "المفرزة الثانية", 1, "on_mission"),
    ("رقيب/ محمود عادل", "رقيب", "سائق معدات حفر", "المفرزة الثانية", 0, "on_mission"),
    ("ملازم أول/ عمر خالد", "ملازم أول", "قائد مفرزة — أعطال طارئة", "المفرزة الثالثة", 1, "available"),
    ("رقيب/ إبراهيم ناصر", "رقيب", "فني لحام ألياف", "المفرزة الثالثة", 0, "available"),
    ("عريف/ يوسف رمضان", "عريف", "فني نحاس", "المفرزة الثالثة", 0, "available"),
    ("مساعد/ طارق شوقي", "مساعد", "فني قياسات OTDR", "طاقم القياس", 1, "available"),
    ("عريف/ حسام علي", "عريف", "فني قياسات", "طاقم القياس", 0, "off_duty"),
]

# route, chainage_m, days_ago, cause, resolution, title
HISTORY_FAULTS = [
    ("R-01", 7380, 610, "حفر جهة خارجية (شركة المياه) دون تنسيق", "استبدال قطعة 60 م ولحام جلبتين، وإبلاغ شركة المياه رسميًا", "قطع كابل الأوتوستراد أمام محطة المياه"),
    ("R-01", 7420, 360, "قطع بمعدات رصف أثناء أعمال تطوير الطريق", "استبدال قطعة 45 م ووضع علامات تحذير على المسار", "قطع كابل الأوتوستراد — أعمال رصف"),
    ("R-01", 7470, 150, "حفر جهة خارجية (شركة المياه) — تكرار", "استبدال قطعة 50 م وطلب تحويل المسار داخل ماسورة HDPE", "قطع كابل الأوتوستراد — تكرار"),
    ("R-02", 2480, 460, "حفر شركة الغاز لتوصيل خط فرعي", "لحام جلبتين وإعادة دفن الكابل على عمق 1 م", "قطع كابل صلاح سالم — أعمال غاز"),
    ("R-03", 9050, 280, "حريق مخلفات أسفل الكوبري", "استبدال 80 م كابل ونقل المسار داخل ماسورة معدنية", "تلف كابل الدائري بسبب حريق"),
    ("R-04", 15100, 540, "سرقة جزء من الكابل", "استبدال 120 م وتركيب غطاء خرساني على الغرفة", "سرقة كابل 26 يوليو"),
    ("R-05", 3020, 690, "رطوبة وتآكل الوصلة النحاسية", "إعادة عمل الوصلة وحقن جيل عازل", "ضعف خدمة على المسار النحاسي"),
    ("R-03", 4200, 95, "تآكل جلبة اللحام ودخول مياه", "استبدال الجلبة وإعادة لحام 96 شعرة", "ارتفاع الفقد على مسار الدائري"),
]


def _point(route_geom, ch):
    lat, lon = geo.point_at_chainage(route_geom, ch)
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}


def _ticket(conn, now, fax_no, fax_type, title, summary, required, location_text, party, priority, status, route_id,
            geom, received_ago_h, status_ago_h, terrain=None, team=None, cause=None, resolution=None, forwarded=False,
            file=None, history=None):
    rec = now - timedelta(hours=received_ago_h)
    st = now - timedelta(hours=status_ago_h)
    lat = lon = None
    if geom:
        lat, lon = geo.representative_point(geom)
    data = dict(
        fax_no=fax_no, fax_type=fax_type, title=title, summary=summary, required_action=required,
        location_text=location_text, requesting_party=party, priority=priority, status=status, route_id=route_id,
        geometry_json=json.dumps(geom) if geom else None, lat=lat, lon=lon, terrain=terrain, assigned_team=team,
        cause=cause, resolution=resolution, received_at=_ts(rec), status_changed_at=_ts(st),
        closed_at=_ts(st) if status == "closed" else None, forwarded_to_command=1 if forwarded else 0,
        forwarded_at=_ts(st) if forwarded else None, created_at=_ts(rec), updated_at=_ts(st),
    )
    tid = db.insert(conn, "faxes_tickets", data, ACTOR, audit=False)
    path = history or _default_path(status)
    times = [rec + (st - rec) * i / max(1, len(path) - 1) for i in range(len(path))]
    prev = None
    for s, t in zip(path, times):
        conn.execute(
            "INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
            (tid, prev, s, _ts(t), "استلام الفاكس" if prev is None else None, ACTOR),
        )
        prev = s
    if file:
        src = config.SEED_DIR / "faxes" / file
        if src.exists():
            config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
            dst = config.UPLOAD_DIR / f"{tid}_{file}"
            shutil.copyfile(src, dst)
            conn.execute("UPDATE faxes_tickets SET original_file=?, original_filename=? WHERE id=?", (dst.name, file, tid))
    return tid


def _default_path(status):
    order = ["new", "preparing", "in_progress", "closed"]
    if status == "awaiting_coordination":
        return ["new", "awaiting_coordination"]
    return order[: order.index(status) + 1]


def _save_estimate(conn, tid, inputs, geom):
    settings = db.get_settings(conn)
    catalog = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM equipment_catalog")}
    pt = geo.representative_point(geom) if geom else None
    r = estimation.compute(inputs, settings, catalog, pt)
    t = db.now()
    db.insert(conn, "estimates_project", dict(
        ticket_id=tid, measured_length_m=r["measured_length_m"], length_source=r["length_source"], cable_type=r["cable_type"],
        fiber_count=r["fiber_count"], task_nature=r["task_nature"], terrain=r["terrain"], reserve_pct=r["reserve_pct"],
        total_cable_m=r["total_cable_m"], splice_closures=r["splice_closures"], fusion_splices=r["fusion_splices"],
        connection_points=r["connection_points"], media_converters=r["media_converters"],
        equipment_json=json.dumps(r["equipment"], ensure_ascii=False), travel_hours=r["travel_hours"],
        laying_hours=r["laying_hours"], splicing_hours=r["splicing_hours"], testing_hours=r["testing_hours"],
        difficulty_factor=r["difficulty_factor"], estimated_hours=r["estimated_hours"], estimated_days=r["estimated_days"],
        manual_overrides_json="{}", notes=None, computed_at=t, updated_at=t), ACTOR, audit=False)
    return r


def _needs_from(conn, tid, equipment, availability_override=None):
    t = db.now()
    for e in equipment:
        avail = (availability_override or {}).get(e["code"], e["availability"])
        db.insert(conn, "ticket_needs", dict(
            ticket_id=tid, item_name=e["name"], category=e["category"], quantity=e["quantity"], unit=e["unit"],
            availability=avail, notes=e["reason"], created_at=t, updated_at=t), ACTOR, audit=False)


def seed_demo(conn):
    route_ids = seed_routes(conn)
    routes = {r["code"]: dict(r) for r in conn.execute("SELECT * FROM routes_sites WHERE kind='route'")}
    g = {c: json.loads(r["geometry_json"]) for c, r in routes.items()}
    now = datetime.now()
    t = db.now()
    for name, rank, spec, team, leader, status in TEAMS:
        db.insert(conn, "teams_personnel", dict(name=name, rank=rank, specialty=spec, team_name=team, is_leader=leader,
                                                status=status, phone=None, created_at=t, updated_at=t), ACTOR, audit=False)

    for i, (rc, ch, ago, cause, res, title) in enumerate(HISTORY_FAULTS, 1):
        geom = _point(g[rc], ch)
        _ticket(conn, now, f"ف/أرشيف/{100 + i}", "fault", title, f"{title} — تم الإصلاح", "إصلاح العطل وإعادة الخدمة",
                routes[rc]["axis_name"], "غرفة عمليات الاتصالات", "high", "closed", route_ids[rc], geom,
                ago * 24, ago * 24 - 20, terrain="asphalt", team="المفرزة الثالثة", cause=cause, resolution=res, forwarded=True)
    # a closed project in history
    geom = {"type": "LineString", "coordinates": g["R-02"]["coordinates"][:12]}
    _ticket(conn, now, "ف/أرشيف/120", "project", "إنشاء وصلة ألياف لمبنى إداري — العباسية",
            "تم مد 2.1 كم ألياف 24 شعرة وتركيب نقطتي ربط", "مد خط ألياف جديد", "العباسية", "قيادة المنطقة", "normal",
            "closed", route_ids["R-02"], geom, 300 * 24, 280 * 24, terrain="urban", team="المفرزة الثانية",
            resolution="تم التنفيذ والاستلام بقياسات OTDR مطابقة", forwarded=True)

    # ---- active prototype faxes ----
    f1_geom = _point(g["R-01"], 7450)
    _ticket(conn, now, "ف/2026/0412", "fault", "قطع كابل ألياف — الأوتوستراد أمام محطة المياه",
            "انقطاع كامل للخدمة على مسار الأوتوستراد بعد أعمال حفر لجهة خارجية",
            "إصلاح فوري وإعادة الخدمة خلال 6 ساعات", "طريق الأوتوستراد — أمام محطة مياه المعادي",
            "غرفة عمليات الاتصالات", "critical", "new", None, None, 2, 2, file="fax_0412.png")
    _ticket(conn, now, "ف/2026/0413", "fault", "قطع كابل — صلاح سالم بسبب أعمال شركة الغاز",
            "تلف كابل ألياف 24 شعرة أثناء حفر شركة الغاز بجوار نفق العباسية",
            "إصلاح العطل ومخاطبة شركة الغاز", "شارع صلاح سالم — بجوار نفق العباسية", "قيادة قطاع الاتصالات", "high",
            "new", None, None, 5, 5, file="fax_0413.png")
    _ticket(conn, now, "ف/2026/0414", "project", "إنشاء خط ألياف جديد — عقدة مدينة نصر إلى مبنى القيادة الجديد",
            "مطلوب مد خط ألياف 24 شعرة من عقدة مدينة نصر إلى مبنى القيادة الجديد بالتجمع",
            "حصر الاحتياجات والزمن التقديري خلال 48 ساعة", "مدينة نصر ← التجمع الخامس", "قيادة المنطقة المركزية", "normal",
            "new", None, None, 20, 20, file="fax_0414.png")
    f4_geom = _point(g["R-01"], 10900)
    _ticket(conn, now, "ف/2026/0398", "coordination", "طلب تنسيق — حفر شركة المياه بجوار مسار الأوتوستراد",
            "شركة المياه تطلب تحديد مسار الكابل قبل حفر خط رئيسي بطول 400 م", "إرسال مندوب لتحديد المسار والرد كتابيًا",
            "طريق الأوتوستراد — قطاع البساتين", "شركة مياه الشرب بالقاهرة", "high", "awaiting_coordination",
            route_ids["R-01"], f4_geom, 80, 75, terrain="asphalt", file="fax_0398.png")
    f5_geom = {"type": "LineString", "coordinates": g["R-03"]["coordinates"][-8:]}
    f5 = _ticket(conn, now, "ف/2026/0389", "project", "إضافة نقطة ربط جديدة — عقدة القطامية",
                 "تركيب نقطة ربط وتحويل لخدمة موقع جديد مجاور لعقدة القطامية", "تجهيز الخامات والمعدات وبدء التنفيذ",
                 "عقدة القطامية — الطريق الدائري", "قيادة المنطقة المركزية", "normal", "preparing", route_ids["R-03"], f5_geom,
                 140, 30, terrain="urban", team="المفرزة الثانية", forwarded=True)
    r5 = _save_estimate(conn, f5, {"task_nature": "cable_laying", "terrain": "urban", "cable_type": "fiber_sm_24",
                                   "measured_length_m": geo.length_m(f5_geom), "connection_points": 2}, f5_geom)
    _needs_from(conn, f5, r5["equipment"], {"media_converter": "shortage", "otdr": "available"})
    f6_geom = _point(g["R-01"], 9300)
    f6 = _ticket(conn, now, "ف/2026/0405", "fault", "ارتفاع الفقد وانقطاع متقطع — الأوتوستراد قطاع دار السلام",
                 "قياس OTDR يوضح حدث عند الكيلو 9.3 من عقدة المعادي", "تحديد موقع التلف وإصلاحه",
                 "الأوتوستراد — قطاع دار السلام", "غرفة عمليات الاتصالات", "high", "in_progress", route_ids["R-01"], f6_geom,
                 26, 4, terrain="asphalt", team="المفرزة الأولى", forwarded=True)
    r6 = _save_estimate(conn, f6, {"task_nature": "fault_repair", "terrain": "asphalt", "cable_type": "fiber_sm_48"}, f6_geom)
    _needs_from(conn, f6, r6["equipment"], {"otdr": "available"})
    f7_geom = _point(g["R-02"], 3900)
    _ticket(conn, now, "ف/2026/0410", "coordination", "تصريح حفر — حي مصر الجديدة",
            "طلب تصريح من الحي لحفر 30 م لإصلاح غرفة تفتيش", "متابعة إصدار التصريح", "مصر الجديدة — شارع صلاح سالم",
            "حي مصر الجديدة", "normal", "awaiting_coordination", route_ids["R-02"], f7_geom, 12, 10, terrain="urban")
    _ticket(conn, now, "ف/2026/0415", "fault", "ارتفاع الفقد على الوصلة S-04-07 — محور 26 يوليو",
            "قياسات دورية توضح زيادة الفقد 1.8 dB عند الوصلة السابعة", "قياس وإعادة لحام الوصلة إذا لزم",
            "محور 26 يوليو — قرب الوصلة السابعة", "طاقم القياس", "low", "new", None, None, 1, 1)


SIM_TEMPLATES = [
    ("fault", "قطع كابل — {place}", "انقطاع خدمة على المسار المار بمنطقة {place} بعد أعمال حفر", "إصلاح فوري وإعادة الخدمة", "critical"),
    ("fault", "ضعف إشارة — {place}", "ارتفاع الفقد على الوصلات القريبة من {place}", "قياس OTDR وتحديد موقع الحدث", "normal"),
    ("project", "مد خط ألياف جديد — {place}", "مطلوب إنشاء خط ألياف لخدمة موقع جديد في {place}", "حصر الاحتياجات والزمن التقديري", "normal"),
    ("coordination", "طلب تنسيق أعمال — {place}", "جهة خارجية تطلب تحديد مسارات الكوابل قبل أعمال حفر في {place}", "إرسال مندوب والرد كتابيًا", "high"),
]
SIM_PARTIES = ["غرفة عمليات الاتصالات", "شركة مياه الشرب بالقاهرة", "شركة الغاز الطبيعي", "هيئة الطرق والكباري", "قيادة المنطقة المركزية"]
SIM_PLACES = ["المعادي", "مدينة نصر", "مصر الجديدة", "المقطم", "حلوان", "الهرم", "شبرا", "عين شمس", "التجمع الخامس", "الزمالك"]


def simulate_fax(conn, actor):
    ftype, title, summary, req, prio = random.choice(SIM_TEMPLATES)
    place = random.choice(SIM_PLACES)
    year = datetime.now().year
    last = conn.execute("SELECT COUNT(*) FROM faxes_tickets WHERE fax_no LIKE ?", (f"ف/{year}/%",)).fetchone()[0]
    n = 500 + last
    while conn.execute("SELECT 1 FROM faxes_tickets WHERE fax_no=?", (f"ف/{year}/{n:04d}",)).fetchone():
        n += 1
    t = db.now()
    tid = db.insert(conn, "faxes_tickets", dict(
        fax_no=f"ف/{year}/{n:04d}", fax_type=ftype, title=title.format(place=place), summary=summary.format(place=place),
        required_action=req, location_text=place, requesting_party=random.choice(SIM_PARTIES), priority=prio, status="new",
        received_at=t, status_changed_at=t, created_at=t, updated_at=t), actor)
    conn.execute("INSERT INTO updates_ticket(ticket_id, old_status, new_status, at, notes, actor) VALUES (?,?,?,?,?,?)",
                 (tid, None, "new", t, "استلام فاكس (محاكاة)", actor))
    return tid


def ensure_database(reset=False):
    if reset:
        for p in (config.DB_PATH, config.DB_PATH.with_suffix(".db-wal"), config.DB_PATH.with_suffix(".db-shm")):
            if p.exists():
                p.unlink()
        if config.UPLOAD_DIR.exists():
            shutil.rmtree(config.UPLOAD_DIR)
    fresh = not config.DB_PATH.exists()
    with db.transaction() as conn:
        db.init_schema(conn)
        seed_reference(conn)
        if fresh or not conn.execute("SELECT 1 FROM routes_sites LIMIT 1").fetchone():
            seed_demo(conn)
