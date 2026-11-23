"""Dev tool: build realistic sample cable routes by routing along the extracted Cairo road network."""
import heapq
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import geo  # noqa: E402

COST = {"motorway": 1.0, "trunk": 1.0, "primary": 1.1, "secondary": 1.3, "tertiary": 1.8}
feats = json.load(open(ROOT / "static/map/cairo_roads.geojson"))["features"]
adj = defaultdict(list)
cells = defaultdict(set)
CELL = 0.0004


def add(a, b, w):
    adj[a].append((b, w))
    adj[b].append((a, w))


for f in feats:
    c = f["properties"]["c"]
    if c not in COST:
        continue
    pts = [tuple(p) for p in f["geometry"]["coordinates"]]
    for a, b in zip(pts, pts[1:]):
        add(a, b, geo.haversine(a[1], a[0], b[1], b[0]) * COST[c])
    for p in pts:
        cells[(int(p[0] / CELL), int(p[1] / CELL))].add(p)
# reconnect junctions lost by simplification
for (cx, cy), ps in list(cells.items()):
    near = set()
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            near |= cells.get((cx + dx, cy + dy), set())
    for p in ps:
        for q in near:
            if p < q:
                d = geo.haversine(p[1], p[0], q[1], q[0])
                if d < 35:
                    add(p, q, d * 1.2)
nodes = list(adj)


def nearest(lat, lon):
    return min(nodes, key=lambda p: (p[0] - lon) ** 2 + (p[1] - lat) ** 2)


def route(a, b):
    s, t = nearest(*a), nearest(*b)
    dist, prev, pq = {s: 0}, {}, [(0, s)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == t:
            break
        if d > dist[u]:
            continue
        for v, w in adj[u]:
            nd = d + w
            if nd < dist.get(v, math.inf):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    if t not in prev:
        raise SystemExit(f"no path {a} -> {b}")
    path = [t]
    while path[-1] != s:
        path.append(prev[path[-1]])
    path.reverse()
    out = [path[0]]
    for p in path[1:]:
        if geo.haversine(out[-1][1], out[-1][0], p[1], p[0]) > 25:
            out.append(p)
    if out[-1] != path[-1]:
        out.append(path[-1])
    return [[round(x, 5), round(y, 5)] for x, y in out]


ROUTES = [
    ("R-01", "مسار الأوتوستراد — المعادي / مدينة نصر", "محور الأوتوستراد", (29.9602, 31.2569), (30.0566, 31.3301), "fiber_sm_48", "شركة المياه، الحي، المرور", 2016),
    ("R-02", "مسار صلاح سالم — العباسية / مصر الجديدة", "محور صلاح سالم", (30.0726, 31.2836), (30.0910, 31.3226), "fiber_sm_24", "الحي، شركة الغاز", 2018),
    ("R-03", "مسار الدائري — المقطم / القطامية", "محور الطريق الدائري", (30.0130, 31.3000), (29.9870, 31.4050), "fiber_sm_96", "هيئة الطرق، شركة الكهرباء", 2020),
    ("R-04", "مسار 26 يوليو — الجيزة / 6 أكتوبر", "محور 26 يوليو", (30.0230, 31.2050), (29.9750, 30.9600), "fiber_sm_24", "هيئة الطرق، جهاز المدينة", 2019),
    ("R-05", "مسار نحاسي — العباسية / وسط البلد", "محور رمسيس", (30.0726, 31.2836), (30.0500, 31.2400), "copper_100", "الحي، المرور", 2009),
]
EXCHANGES = {
    (29.9602, 31.2569): ("X-MAD", "سنترال المعادي (عقدة ربط)"),
    (30.0566, 31.3301): ("X-NSR", "سنترال مدينة نصر (عقدة ربط)"),
    (30.0726, 31.2836): ("X-ABS", "عقدة العباسية الرئيسية"),
    (30.0910, 31.3226): ("X-HLP", "عقدة مصر الجديدة"),
    (30.0130, 31.3000): ("X-MOK", "عقدة المقطم"),
    (29.9870, 31.4050): ("X-QTM", "عقدة القطامية"),
    (30.0230, 31.2050): ("X-GZA", "عقدة الجيزة"),
    (29.9750, 30.9600): ("X-OCT", "عقدة 6 أكتوبر"),
    (30.0500, 31.2400): ("X-DTN", "عقدة وسط البلد"),
}
out = {"routes": [], "sites": []}
for code, name, axis, a, b, cable, parties, year in ROUTES:
    coords = route(a, b)
    g = {"type": "LineString", "coordinates": coords}
    L = geo.length_m(g)
    out["routes"].append(dict(code=code, name=name, axis_name=axis, geometry=g, cable_type=cable, parties=parties,
                              install_year=year, length_m=round(L)))
    drum = 2000 if cable.startswith("fiber") else 500
    n = 1
    for ch in range(drum, int(L) - 300, drum):
        lat, lon = geo.point_at_chainage(g, ch)
        out["sites"].append(dict(code=f"S-{code[2:]}-{n:02d}", name=f"وصلة رقم {n} — {axis} (كم {ch/1000:.1f})",
                                 kind="splice", parent=code, lat=round(lat, 5), lon=round(lon, 5)))
        n += 1
    lat, lon = geo.point_at_chainage(g, L * 0.37)
    out["sites"].append(dict(code=f"C-{code[2:]}-01", name=f"غرفة تفتيش — {axis}", kind="checkpoint", parent=code,
                             lat=round(lat, 5), lon=round(lon, 5)))
    print(code, round(L), len(coords))
for (lat, lon), (code, name) in EXCHANGES.items():
    out["sites"].append(dict(code=code, name=name, kind="exchange", parent=None, lat=lat, lon=lon))
json.dump(out, open(ROOT / "app/seed_data/routes.json", "w"), ensure_ascii=False, indent=1)
