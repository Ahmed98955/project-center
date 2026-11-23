"""Smart detection engine: checks history and running operations around a location."""
from datetime import datetime, timedelta

from . import geo
from .workflow import FAX_TYPES, STATUS_LABELS, wait_info


def _fmt_km(m):
    return f"{m:,.0f} م" if m < 1000 else f"{m / 1000:.1f} كم"


def _cable_name(conn, code):
    if not code:
        return "غير محدد"
    r = conn.execute("SELECT name FROM equipment_catalog WHERE code=?", (code,)).fetchone()
    return r["name"] if r else code


def _bbox_candidates(conn, lat, lon, radius_m, where="", params=()):
    dlat = radius_m / 111_000 + 0.02
    dlon = radius_m / 96_000 + 0.02
    sql = (
        "SELECT * FROM faxes_tickets WHERE geometry_json IS NOT NULL AND lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?"
        + (" AND " + where if where else "")
    )
    return [dict(r) for r in conn.execute(sql, (lat - dlat, lat + dlat, lon - dlon, lon + dlon, *params))]


def nearest_route(conn, geom, max_m):
    best = None
    for r in conn.execute("SELECT * FROM routes_sites WHERE kind='route'"):
        d = geo.distance_m(geom, r["geometry_json"])
        if d <= max_m and (best is None or d < best[1]):
            best = (dict(r), d)
    return best


def nearest_site(conn, geom, max_m):
    best = None
    for r in conn.execute("SELECT * FROM routes_sites WHERE kind!='route'"):
        d = geo.distance_m(geom, r["geometry_json"])
        if d <= max_m and (best is None or d < best[1]):
            best = (dict(r), d)
    return best


def run(conn, geometry, settings: dict, ticket_id=None, fax_type=None) -> dict:
    g = geo.validate(geometry)
    lat, lon = geo.representative_point(g)
    alerts = []
    suggested_route_id = None

    nr = nearest_route(conn, g, float(settings["route_snap_m"]))
    if nr:
        route, d = nr
        suggested_route_id = route["id"]
        ch, _ = geo.chainage_m(route["geometry_json"], g)
        alerts.append(
            {
                "type": "route_match",
                "severity": "info",
                "title": f"الموقع على المسار {route['code']}",
                "message": f"{route['name']} — عند الكيلو {ch / 1000:.2f} من بداية المسار (يبعد {_fmt_km(d)})."
                f" نوع الكابل القائم: {_cable_name(conn, route.get('cable_type'))}. الجهات المشتركة: {route.get('parties') or '—'}",
                "route_id": route["id"],
            }
        )
    ns = nearest_site(conn, g, float(settings["site_snap_m"]))
    if ns:
        site, d = ns
        alerts.append(
            {
                "type": "site_near",
                "severity": "info",
                "title": f"أقرب نقطة قائمة: {site['code']}",
                "message": f"{site['name']} على بعد {_fmt_km(d)}.",
                "site_id": site["id"],
            }
        )

    # repeated faults at the same point
    radius = float(settings["repeat_radius_m"])
    since = (datetime.now() - timedelta(days=int(settings["repeat_window_days"]))).isoformat(sep=" ")
    prior = []
    for t in _bbox_candidates(conn, lat, lon, radius, "fax_type='fault' AND received_at >= ?", (since,)):
        if t["id"] == ticket_id:
            continue
        d = geo.distance_m(g, t["geometry_json"])
        if d <= radius:
            prior.append((t, d))
    if prior:
        prior.sort(key=lambda x: x[0]["received_at"], reverse=True)
        closed = [p for p in prior if p[0]["status"] == "closed"]
        last = (closed or prior)[0][0]
        when = (last.get("closed_at") or last["received_at"])[:10]
        alerts.append(
            {
                "type": "repeat_fault",
                "severity": "urgent",
                "title": f"عطل متكرر — {len(prior)} {'عطل سابق' if len(prior) == 1 else 'أعطال سابقة'} في نطاق {_fmt_km(radius)}",
                "message": f"آخر إصلاح: {when} (فاكس {last['fax_no']}). السبب: {last.get('cause') or 'غير مسجل'}."
                f" الإجراءات المتخذة: {last.get('resolution') or 'غير مسجلة'}.",
                "related": [
                    {
                        "id": t["id"],
                        "fax_no": t["fax_no"],
                        "date": (t.get("closed_at") or t["received_at"])[:10],
                        "cause": t.get("cause"),
                        "resolution": t.get("resolution"),
                        "status": STATUS_LABELS.get(t["status"], t["status"]),
                        "distance_m": round(d),
                    }
                    for t, d in prior
                ],
            }
        )

    # duplicate open ticket at same place
    dup_r = float(settings["duplicate_radius_m"])
    for t in _bbox_candidates(conn, lat, lon, dup_r, "status != 'closed'"):
        if t["id"] == ticket_id or (fax_type and t["fax_type"] != fax_type):
            continue
        d = geo.distance_m(g, t["geometry_json"])
        if d <= dup_r:
            alerts.append(
                {
                    "type": "duplicate",
                    "severity": "warning",
                    "title": "بلاغ مفتوح لنفس الموقع",
                    "message": f"الفاكس {t['fax_no']} ({FAX_TYPES[t['fax_type']]}) مفتوح على بعد {_fmt_km(d)} — تحقق من عدم تكرار الفاكس.",
                    "related": [{"id": t["id"], "fax_no": t["fax_no"]}],
                }
            )

    # nearby working teams
    team_r = float(settings["nearby_team_radius_m"])
    for t in _bbox_candidates(conn, lat, lon, team_r, "status IN ('preparing','in_progress') AND assigned_team IS NOT NULL"):
        if t["id"] == ticket_id:
            continue
        d = geo.distance_m(g, t["geometry_json"])
        if d <= team_r:
            alerts.append(
                {
                    "type": "nearby_team",
                    "severity": "warning",
                    "title": f"مفرزة عمل قريبة: {t['assigned_team']}",
                    "message": f"تعمل على الفاكس {t['fax_no']} ({STATUS_LABELS[t['status']]}) على بعد {_fmt_km(d)} — يمكن الاستفادة من معداتها أو ضم المهمة لها.",
                    "related": [{"id": t["id"], "fax_no": t["fax_no"]}],
                }
            )

    # delayed coordination in the area / same route
    max_h = float(settings["coordination_max_hours"])
    for t in _bbox_candidates(conn, lat, lon, team_r, "status='awaiting_coordination'"):
        if t["id"] == ticket_id:
            continue
        w = wait_info(t, max_h)
        d = geo.distance_m(g, t["geometry_json"])
        same_route = suggested_route_id and t.get("route_id") == suggested_route_id
        if w["overdue"] and (d <= team_r or same_route):
            alerts.append(
                {
                    "type": "coordination_delay",
                    "severity": "warning",
                    "title": f"تأخر رد جهة التنسيق: {t.get('requesting_party') or t.get('responsible_party') or '—'}",
                    "message": f"الفاكس {t['fax_no']} في انتظار التنسيق منذ {w['hours_in_status']:.0f} ساعة (الحد {max_h:.0f}) على بعد {_fmt_km(d)}.",
                    "related": [{"id": t["id"], "fax_no": t["fax_no"]}],
                }
            )

    order = {"urgent": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: order[a["severity"]])
    return {"lat": lat, "lon": lon, "suggested_route_id": suggested_route_id, "alerts": alerts}
