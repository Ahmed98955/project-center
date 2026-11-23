"""End-to-end tests: station -> command screen sync, alerts, and commander commands."""
import ps_app.geo  # noqa: F401  (loaded via conftest alias)

from app import db, sync


def _station_ticket(station, fax_no):
    items = station.get("/api/tickets", params={"scope": "all", "limit": 500}).json()
    return next(t for t in items if t["fax_no"] == fax_no)


def _point_on_route(station, code, chainage_m):
    import ps_app.geo as geo
    routes = station.get("/api/routes", params={"kind": "route"}).json()
    r = next(x for x in routes if x["code"] == code)
    lat, lon = geo.point_at_chainage(r["geometry"], chainage_m)
    return {"type": "Point", "coordinates": [round(lon, 6), round(lat, 6)]}


def _feed_count(station):
    return len(station.get("/api/command/feed", params={"limit": 500}).json())


def _wait_feed(station, min_count, tries=30):
    """The station commits after responding; wait until the outbox grows."""
    import time
    for _ in range(tries):
        if _feed_count(station) >= min_count:
            return True
        time.sleep(0.1)
    return False


def _wait_ticket(station, tid, pred, tries=40):
    """Station commits after responding; poll until the change is visible."""
    import time
    t = {}
    for _ in range(tries):
        t = station.get(f"/api/tickets/{tid}").json()
        if pred(t):
            return t
        time.sleep(0.1)
    return t


def _wait_feed_seen(station, text, tries=30):
    import time
    for _ in range(tries):
        dirs = station.get("/api/command/directives").json()
        if any(text in (d.get("message") or "") for d in dirs):
            return dirs
        time.sleep(0.1)
    return []


def _forward_project(station):
    """Prepare and forward fax 0414 (project) — returns station ticket id."""
    t = _station_ticket(station, "ف/2026/0414")
    before = _feed_count(station)
    line = {"type": "LineString", "coordinates": [[31.33, 30.056], [31.40, 30.03], [31.45, 30.02]]}
    station.put(f"/api/tickets/{t['id']}/location", json={"geometry": line, "terrain": "urban"})
    _wait_ticket(station, t["id"], lambda x: bool(x.get("geometry")))
    r = station.put(f"/api/tickets/{t['id']}/estimate", json={"connection_points": 2, "generate_needs": True})
    assert r.status_code == 200
    _wait_ticket(station, t["id"], lambda x: bool(x.get("has_estimate")))
    r = station.post(f"/api/tickets/{t['id']}/forward")
    assert r.status_code == 200, r.text
    assert _wait_feed(station, before + 1)
    return t["id"]


def test_sync_receives_forwarded_fax(client, station):
    tid = _forward_project(station)
    sync.poll_once()
    t = client.get(f"/api/tickets/{tid}")
    assert t.status_code == 200
    body = t.json()
    assert body["fax_no"] == "ف/2026/0414" and body["fax_type"] == "project"
    assert body["estimate"] and body["needs"]
    # original fax image downloaded
    assert body["local_has_file"]
    f = client.get(f"/api/tickets/{tid}/file")
    assert f.status_code == 200 and f.content[:4] == b"\x89PNG"
    # dashboard counts
    d = client.get("/api/dashboard").json()
    assert d["active_projects"] >= 1 and d["total"] >= 1
    # status endpoint reports connected
    st = client.get("/api/status").json()
    assert st["connected"] and st["station_device"]


def test_urgent_alerts_and_ack(client, station):
    # forward the critical fault at the known repeat-fault location
    t = _station_ticket(station, "ف/2026/0412")
    before = _feed_count(station)
    geom = _point_on_route(station, "R-01", 7450)
    station.put(f"/api/tickets/{t['id']}/location", json={"geometry": geom, "terrain": "asphalt"})
    _wait_ticket(station, t["id"], lambda x: bool(x.get("geometry")))
    r = station.post(f"/api/tickets/{t['id']}/forward")
    assert r.status_code == 200
    assert _wait_feed(station, before + 1)
    sync.poll_once()
    alerts = client.get("/api/alerts").json()
    kinds = {a["kind"] for a in alerts}
    assert "critical_new" in kinds and "repeat_fault" in kinds
    rep = next(a for a in alerts if a["kind"] == "repeat_fault")
    assert rep["payload"]["related"]  # last repair date / cause / actions present
    # acknowledge -> also recorded on the station side
    aid = rep["id"]
    r = client.post(f"/api/alerts/{aid}/ack", json={"ticket_id": t["id"]})
    assert r.status_code == 200
    conn = db.connect()
    ack = db.one(conn, "SELECT seen_at FROM alert_events WHERE id=?", (aid,))
    assert ack["seen_at"]
    conn.close()
    # verify station recorded the ack under the commander device name
    audit = station.get("/api/audit", params={"table": "command_alert_acks"}).json()
    assert audit["items"] and "القائد" in (audit["items"][0]["actor"] or "")


def test_commander_commands_roundtrip(client, station):
    tid = _forward_project(station)
    sync.poll_once()
    detail = client.get(f"/api/tickets/{tid}").json()
    needs = detail["needs"]
    assert needs
    nid = needs[0]["id"]
    # 1) approve a need item -> station updates + pushes back
    r = client.post("/api/commands/availability",
                    json={"ticket_id": tid, "need_id": nid, "availability": "available"})
    assert r.status_code == 200
    st = _wait_ticket(station, tid, lambda x: any(n["id"] == nid and n["availability"] == "available" for n in x.get("needs", [])))
    assert st["needs"]
    # command appears in station audit log under commander name
    audit = station.get("/api/audit", params={"q": "القائد"}).json()
    assert audit["total"] >= 1
    # local copy refreshed from the returned ticket
    local = client.get(f"/api/tickets/{tid}").json()
    assert next(x for x in local["needs"] if x["id"] == nid)["availability"] == "available"
    # 2) change priority
    r = client.post("/api/commands/priority", json={"ticket_id": tid, "priority": "high"})
    assert r.status_code == 200
    st = _wait_ticket(station, tid, lambda x: x.get("priority") == "high")
    assert st["priority"] == "high"
    # 3) directive -> popup data on station + fax marked read + timeline entry
    r = client.post("/api/commands/directive",
                    json={"ticket_id": tid, "message": "أولوية قصوى — التنفيذ خلال 48 ساعة"})
    assert r.status_code == 200
    dirs = _wait_feed_seen(station, "أولوية قصوى")
    assert dirs
    st = _wait_ticket(station, tid, lambda x: bool(x.get("command_seen_at")))
    assert st["command_seen_at"] and any("توجيه من القيادة" in (u["notes"] or "") for u in st["updates"])
    # 4) mark seen
    r = client.post("/api/commands/seen", json={"ticket_id": tid})
    assert r.status_code == 200


def test_reference_and_map_layers(client, station):
    sync.poll_once()
    ref = client.get("/api/reference").json()
    assert ref["routes"] and ref["teams"]
    layers = client.get("/api/map/layers").json()
    assert layers["network"]["features"]


def test_station_offline_shows_disconnected(client):
    conn = db.connect()
    db.set_setting(conn, "station_url", "http://127.0.0.1:9")  # unreachable
    conn.commit()
    conn.close()
    sync.poll_once()
    st = client.get("/api/status").json()
    assert not st["connected"]
    # old data still served
    assert client.get("/api/dashboard").status_code == 200
