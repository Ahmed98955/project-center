import json
import math

EARTH_R = 6371008.8


def haversine(lat1, lon1, lat2, lon2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def parse(geom):
    if geom is None or geom == "":
        return None
    if isinstance(geom, str):
        geom = json.loads(geom)
    if geom.get("type") == "Feature":
        geom = geom.get("geometry")
    return geom


def validate(geom) -> dict:
    g = parse(geom)
    if not g or g.get("type") not in ("Point", "LineString", "MultiLineString"):
        raise ValueError("نوع الشكل الجغرافي غير مدعوم (نقطة أو خط فقط)")
    for lon, lat in _all_coords(g):
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("إحداثيات غير صالحة")
    if g["type"] == "LineString" and len(g["coordinates"]) < 2:
        raise ValueError("الخط يجب أن يحتوي على نقطتين على الأقل")
    return g


def _all_coords(g):
    t = g["type"]
    if t == "Point":
        return [g["coordinates"][:2]]
    if t == "LineString":
        return [c[:2] for c in g["coordinates"]]
    if t == "MultiLineString":
        return [c[:2] for line in g["coordinates"] for c in line]
    return []


def _lines(g):
    """Return list of polylines as [(lat, lon), ...]; a point is a one-vertex line."""
    t = g["type"]
    if t == "Point":
        lon, lat = g["coordinates"][:2]
        return [[(lat, lon)]]
    if t == "LineString":
        return [[(c[1], c[0]) for c in g["coordinates"]]]
    if t == "MultiLineString":
        return [[(c[1], c[0]) for c in line] for line in g["coordinates"]]
    return []


def length_m(geom) -> float:
    g = parse(geom)
    if not g:
        return 0.0
    total = 0.0
    for line in _lines(g):
        for (a, b), (c, d) in zip(line, line[1:]):
            total += haversine(a, b, c, d)
    return total


def representative_point(geom):
    """Point for a geometry: the point itself, or the midpoint along a line."""
    g = parse(geom)
    if not g:
        return None
    lines = _lines(g)
    if g["type"] == "Point":
        return lines[0][0]
    half = length_m(g) / 2
    acc = 0.0
    for line in lines:
        for (a, b), (c, d) in zip(line, line[1:]):
            seg = haversine(a, b, c, d)
            if acc + seg >= half and seg > 0:
                f = (half - acc) / seg
                return (a + (c - a) * f, b + (d - b) * f)
            acc += seg
    return lines[0][0]


class _Proj:
    def __init__(self, lat0):
        self.kx = math.radians(1) * EARTH_R * math.cos(math.radians(lat0))
        self.ky = math.radians(1) * EARTH_R

    def __call__(self, p):
        return (p[1] * self.kx, p[0] * self.ky)


def _pt_seg(p, a, b):
    (x, y), (x1, y1), (x2, y2) = p, a, b
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x - x1, y - y1), 0.0
    t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - (x1 + t * dx), y - (y1 + t * dy)), t


def _seg_intersect(a, b, c, d):
    def orient(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    return (o1 * o2 < 0) and (o3 * o4 < 0)


def distance_m(geom_a, geom_b) -> float:
    ga, gb = parse(geom_a), parse(geom_b)
    if not ga or not gb:
        return float("inf")
    la, lb = _lines(ga), _lines(gb)
    lat0 = la[0][0][0]
    proj = _Proj(lat0)
    pa = [[proj(p) for p in line] for line in la]
    pb = [[proj(p) for p in line] for line in lb]
    best = float("inf")
    for A in pa:
        for B in pb:
            segs_a = list(zip(A, A[1:])) or [(A[0], A[0])]
            segs_b = list(zip(B, B[1:])) or [(B[0], B[0])]
            for s1 in segs_a:
                for s2 in segs_b:
                    if s1[0] != s1[1] and s2[0] != s2[1] and _seg_intersect(*s1, *s2):
                        return 0.0
                    for p, s in ((s1[0], s2), (s1[1], s2), (s2[0], s1), (s2[1], s1)):
                        d, _ = _pt_seg(p, *s)
                        if d < best:
                            best = d
    return best


def chainage_m(route_geom, point_geom):
    """Distance along the route to the projection of the point, and the offset from the route."""
    gr, gp = parse(route_geom), parse(point_geom)
    if not gr or not gp:
        return None, None
    lat, lon = representative_point(gp)
    proj = _Proj(lat)
    p = proj((lat, lon))
    best = (float("inf"), 0.0)
    acc = 0.0
    for line in _lines(gr):
        for a, b in zip(line, line[1:]):
            seg_len = haversine(a[0], a[1], b[0], b[1])
            d, t = _pt_seg(p, proj(a), proj(b))
            if d < best[0]:
                best = (d, acc + t * seg_len)
            acc += seg_len
    return best[1], best[0]


def point_at_chainage(geom, dist_m):
    """(lat, lon) at a distance along a line from its start."""
    g = parse(geom)
    lines = _lines(g)
    acc = 0.0
    for line in lines:
        for (a, b), (c, d) in zip(line, line[1:]):
            seg = haversine(a, b, c, d)
            if acc + seg >= dist_m and seg > 0:
                f = (dist_m - acc) / seg
                return (a + (c - a) * f, b + (d - b) * f)
            acc += seg
    return lines[-1][-1]
