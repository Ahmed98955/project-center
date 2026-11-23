from app import estimation, geo
from app.defaults import CATALOG, SETTINGS

S = {k: v for k, v, *_ in SETTINGS}
CAT = {c[0]: {"code": c[0], "name": c[1], "category": c[2], "unit": c[3], "default_availability": c[4]} for c in CATALOG}


def by_fax(client, no):
    return next(t for t in client.get("/api/tickets?scope=all").json() if t["fax_no"] == no)


def route(client, code):
    return next(r for r in client.get("/api/routes?kind=route").json() if r["code"] == code)


# ---------- geo
def test_haversine_and_length():
    assert abs(geo.haversine(30.0, 31.0, 30.0, 31.01) - 963) < 5
    line = {"type": "LineString", "coordinates": [[31.0, 30.0], [31.01, 30.0], [31.01, 30.01]]}
    assert abs(geo.length_m(line) - (963 + 1112)) < 10
    assert geo.distance_m({"type": "Point", "coordinates": [31.005, 30.0]}, line) < 1


def test_chainage():
    line = {"type": "LineString", "coordinates": [[31.0, 30.0], [31.02, 30.0]]}
    ch, off = geo.chainage_m(line, {"type": "Point", "coordinates": [31.01, 30.0005]})
    assert abs(ch - 963) < 5 and abs(off - 55) < 5


# ---------- estimation
def test_cable_laying_estimate():
    r = estimation.compute({"task_nature": "cable_laying", "terrain": "open", "cable_type": "fiber_sm_24",
                            "measured_length_m": 5000, "reserve_pct": 10, "connection_points": 2}, S, CAT)
    assert r["total_cable_m"] == 5500
    assert r["splice_closures"] == 2          # ceil(5500/2000) - 1
    assert r["fusion_splices"] == (2 + 2) * 24
    assert r["media_converters"] == 2 * 2 + 1
    codes = {e["code"] for e in r["equipment"]}
    assert {"fiber_sm_24", "splice_closure", "fusion_splicer", "otdr", "trencher", "media_converter"} <= codes


def test_reserve_is_clamped_and_terrain_factor():
    a = estimation.compute({"task_nature": "cable_laying", "terrain": "open", "measured_length_m": 1000, "reserve_pct": 50}, S, CAT)
    assert a["reserve_pct"] == 15 and a["total_cable_m"] == 1150
    b = estimation.compute({"task_nature": "cable_laying", "terrain": "asphalt", "measured_length_m": 1000}, S, CAT)
    o = estimation.compute({"task_nature": "cable_laying", "terrain": "open", "measured_length_m": 1000}, S, CAT)
    assert abs(b["estimated_hours"] / o["estimated_hours"] - 1.6) < 0.02


def test_fault_repair_and_overrides():
    r = estimation.compute({"task_nature": "fault_repair", "cable_type": "fiber_sm_48", "overrides": {"total_cable_m": 120}}, S, CAT)
    assert r["splice_closures"] == 2 and r["fusion_splices"] == 96
    assert r["total_cable_m"] == 120 and r["manual_overrides"] == {"total_cable_m": 120}


def test_invalid_inputs():
    import pytest
    with pytest.raises(ValueError):
        estimation.compute({"task_nature": "x"}, S, CAT)
    with pytest.raises(ValueError):
        estimation.compute({"task_nature": "cable_laying", "measured_length_m": -5}, S, CAT)


# ---------- API: detection, workflow, forwarding, audit
def test_repeat_fault_detection_on_known_point(client):
    t = by_fax(client, "ف/2026/0412")
    r1 = route(client, "R-01")
    lat, lon = geo.point_at_chainage(r1["geometry"], 7450)
    res = client.put(f"/api/tickets/{t['id']}/location", json={"geometry": {"type": "Point", "coordinates": [lon, lat]}, "terrain": "asphalt"}).json()
    types = [a["type"] for a in res["detection"]["alerts"]]
    assert types[0] == "repeat_fault"
    assert {"route_match", "nearby_team", "coordination_delay"} <= set(types)
    rep = res["detection"]["alerts"][0]
    assert len(rep["related"]) == 3 and "شركة المياه" in rep["message"]
    assert res["route_id"] == r1["id"]           # auto-linked to the route
    assert res["terrain"] == "asphalt"


def test_no_alerts_far_away(client):
    t = by_fax(client, "ف/2026/0414")
    res = client.put(f"/api/tickets/{t['id']}/location", json={"geometry": {"type": "Point", "coordinates": [30.5, 29.0]}}).json()
    assert res["detection"]["alerts"] == []


def test_invalid_geometry_rejected(client):
    t = by_fax(client, "ف/2026/0414")
    r = client.put(f"/api/tickets/{t['id']}/location", json={"geometry": {"type": "Polygon", "coordinates": []}})
    assert r.status_code == 400


def test_state_machine(client):
    t = by_fax(client, "ف/2026/0413")
    assert client.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress"}).status_code == 400
    assert client.post(f"/api/tickets/{t['id']}/status", json={"status": "preparing"}).status_code == 200
    r = client.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress"})
    assert r.status_code == 400 and "المفرزة" in r.json()["detail"]
    client.put(f"/api/tickets/{t['id']}/location", json={"geometry": {"type": "Point", "coordinates": [31.3, 30.07]}})
    assert client.post(f"/api/tickets/{t['id']}/status", json={"status": "in_progress", "assigned_team": "المفرزة الثالثة"}).status_code == 200
    teams = client.get("/api/teams").json()
    assert all(p["status"] == "on_mission" for p in teams if p["team_name"] == "المفرزة الثالثة")
    r = client.post(f"/api/tickets/{t['id']}/status", json={"status": "closed", "resolution": "تم"})
    assert r.status_code == 400 and "سبب" in r.json()["detail"]
    r = client.post(f"/api/tickets/{t['id']}/status", json={"status": "closed", "resolution": "لحام جلبتين", "cause": "حفر شركة الغاز"})
    assert r.status_code == 200 and r.json()["closed_at"]
    assert [u["new_status"] for u in r.json()["updates"]][-3:] == ["preparing", "in_progress", "closed"]
    teams = client.get("/api/teams").json()
    assert all(p["status"] == "available" for p in teams if p["team_name"] == "المفرزة الثالثة")


def test_overdue_coordination_flag(client):
    t = by_fax(client, "ف/2026/0398")
    assert t["wait"]["overdue"] is True
    assert any(a["type"] == "coordination_delay" for a in client.get("/api/alerts").json())


def test_estimate_needs_and_forward(client):
    t = by_fax(client, "ف/2026/0414")
    assert client.post(f"/api/tickets/{t['id']}/forward").status_code == 400   # no location yet
    line = {"type": "LineString", "coordinates": [[31.33, 30.056], [31.40, 30.03], [31.45, 30.02]]}
    client.put(f"/api/tickets/{t['id']}/location", json={"geometry": line, "terrain": "urban"})
    r = client.put(f"/api/tickets/{t['id']}/estimate", json={"connection_points": 2, "generate_needs": True}).json()
    est = r["estimate"]
    assert est["task_nature"] == "cable_laying" and est["measured_length_m"] > 10000
    assert r["needs"] and r["needs_status"] in ("needs_approval", "shortage", "available")
    nid = r["needs"][0]["id"]
    r = client.put(f"/api/needs/{nid}", json={"availability": "shortage"}).json()
    assert r["needs_status"] == "shortage"
    r = client.post(f"/api/tickets/{t['id']}/forward").json()
    assert r["forwarded_to_command"] == 1
    feed = client.get("/api/command/feed").json()
    assert feed[-1]["ticket_id"] == t["id"] and feed[-1]["payload"]["ticket"]["estimate"]
    assert client.delete(f"/api/tickets/{t['id']}").status_code == 400      # forwarded => cannot delete


def test_create_upload_and_audit(client):
    r = client.post("/api/tickets", json={"fax_no": "ف/2026/9999", "fax_type": "fault", "title": "اختبار عطل", "summary": "ملخص اختبار", "priority": "high"})
    assert r.status_code == 200
    tid = r.json()["id"]
    assert client.post("/api/tickets", json={"fax_no": "ف/2026/9999", "fax_type": "fault", "title": "مكرر", "summary": "مكرر"}).status_code == 409
    up = client.post(f"/api/tickets/{tid}/file", files={"file": ("fax.pdf", b"%PDF-1.4 test", "application/pdf")})
    assert up.status_code == 200 and up.json()["has_file"]
    assert client.get(f"/api/tickets/{tid}/file").content.startswith(b"%PDF")
    assert client.post(f"/api/tickets/{tid}/file", files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 400
    client.put(f"/api/tickets/{tid}", json={"priority": "critical"})
    audit = client.get("/api/audit?table=faxes_tickets").json()["items"]
    upd = next(a for a in audit if a["record_id"] == tid and a["action"] == "UPDATE" and "priority" in (a["new_value"] or ""))
    assert '"critical"' in upd["new_value"] and '"high"' in upd["old_value"] and upd["device"]


def test_search_places_and_network(client):
    labels = [x["label"] for x in client.get("/api/search", params={"q": "المعادى"}).json()]
    assert any("المعادي" in l for l in labels)          # normalization ى/ي
    assert client.get("/api/search", params={"q": "R-03"}).json()[0]["type"] == "network"


def test_settings_validation_and_effect(client):
    assert client.put("/api/settings", json={"repeat_radius_m": -1}).status_code == 400
    assert client.put("/api/settings", json={"nope": 1}).status_code == 400
    assert client.put("/api/settings", json={"reserve_pct_default": 15}).status_code == 200
    t = by_fax(client, "ف/2026/0412")
    r = client.post(f"/api/tickets/{t['id']}/estimate/preview", json={}).json()
    assert r["reserve_pct"] == 15


def test_command_inbox_and_update_push(client):
    t = by_fax(client, "ف/2026/0414")
    line = {"type": "LineString", "coordinates": [[31.33, 30.056], [31.40, 30.03], [31.45, 30.02]]}
    client.put(f"/api/tickets/{t['id']}/location", json={"geometry": line, "terrain": "urban"})
    client.put(f"/api/tickets/{t['id']}/estimate", json={"connection_points": 2, "generate_needs": True})
    client.post(f"/api/tickets/{t['id']}/forward")
    feed_len = len(client.get("/api/command/feed").json())
    # commander: approve a need -> station applies + pushes update to feed
    det = client.get(f"/api/tickets/{t['id']}").json()
    nid = det["needs"][0]["id"]
    r = client.post("/api/command/inbox", json={"action": "set_need_availability", "need_id": nid,
                                                "availability": "available", "device": "TEST-DEVICE"})
    assert r.status_code == 200
    assert next(n for n in r.json()["ticket"]["needs"] if n["id"] == nid)["availability"] == "available"
    assert len(client.get("/api/command/feed").json()) > feed_len          # update pushed to commander
    # commander: change priority
    r = client.post("/api/command/inbox", json={"action": "set_priority", "ticket_id": t["id"],
                                                "priority": "high", "device": "TEST-DEVICE"})
    assert r.status_code == 200 and r.json()["ticket"]["priority"] == "high"
    # commander: directive -> stored, fax marked read, logged in timeline
    r = client.post("/api/command/inbox", json={"action": "directive", "ticket_id": t["id"],
                                                "message": "تابع التنفيذ أولًا", "device": "TEST-DEVICE"})
    assert r.status_code == 200
    det = client.get(f"/api/tickets/{t['id']}").json()
    assert det["command_seen_at"] and any("توجيه من القيادة" in (u["notes"] or "") for u in det["updates"])
    dirs = client.get("/api/command/directives").json()
    assert dirs and "تابع التنفيذ" in dirs[-1]["message"] and "TEST-DEVICE" in dirs[-1]["actor"]
    # invalid inputs rejected
    assert client.post("/api/command/inbox", json={"action": "set_priority", "ticket_id": t["id"],
                                                   "priority": "bogus"}).status_code == 400
    assert client.post("/api/command/inbox", json={"action": "nope"}).status_code == 400
    # audit log records commands under the commander device name
    audit = client.get("/api/audit", params={"q": "TEST-DEVICE"}).json()
    assert audit["total"] >= 3


def test_simulate_and_dashboard(client):
    before = client.get("/api/dashboard").json()["by_status"]["new"]
    t = client.post("/api/simulate/fax").json()
    assert t["status"] == "new"
    assert client.get("/api/dashboard").json()["by_status"]["new"] == before + 1
    layers = client.get("/api/map/layers").json()
    assert len(layers["network"]["features"]) > 20 and layers["tickets"]["features"]
