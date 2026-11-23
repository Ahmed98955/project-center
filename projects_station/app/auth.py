"""Local IAM: users, PBKDF2 password hashing, cookie sessions, permission gate.

Everything is offline — stdlib only. Sessions live in SQLite, passwords are
stored as pbkdf2_hmac-sha256 hashes (salt:hash hex). Permissions are granted
per user as a JSON list; when empty they are derived from the role preset.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from datetime import datetime

from fastapi import Depends, HTTPException, Request

from . import db

SESSION_TTL = 12 * 3600          # 12 hours
PBKDF2_ITERATIONS = 120_000
COOKIE_NAME = "ps_session"
MAX_FAILS = 8                    # per username+ip window
FAIL_WINDOW = 300                # seconds

# ---------------------------------------------------------------- passwords
def hash_password(pw: str, salt: bytes = None) -> str:
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt.hex() + ":" + dk.hex()


def verify_password(pw: str, stored: str) -> bool:
    try:
        salt_hex, dk_hex = stored.split(":", 1)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ITERATIONS)
    return hmac.compare_digest(dk.hex(), dk_hex)


# ---------------------------------------------------------------- permission catalog
# key -> Arabic label (order matters for the admin UI)
PERMISSIONS = {
    "dash.view": "عرض لوحة المتابعة والمؤشرات",
    "tickets.view": "عرض الفاكسات والملفات المرفقة",
    "tickets.create": "تسجيل فاكس جديد",
    "tickets.edit": "تعديل بيانات الفاكس",
    "tickets.delete": "حذف فاكس",
    "tickets.status": "تغيير حالة الفاكس",
    "tickets.forward": "حفظ وتمرير إلى القيادة",
    "files.upload": "رفع الملف الأصلي",
    "files.extract": "استخراج نص الفاكس",
    "estimate.edit": "التقدير الفني",
    "needs.edit": "إدارة بنود الاحتياجات",
    "location.edit": "تحديد موقع العطل على الخريطة",
    "notes.add": "إضافة ملاحظات",
    "detect.run": "تشغيل التحليل والكشف عن الأعطال",
    "map.view": "عرض الخريطة العامة",
    "history.view": "عرض السجل التاريخي",
    "alerts.view": "عرض التنبيهات",
    "routes.manage": "إدارة المسارات والوصلات",
    "teams.manage": "إدارة الأطقم والمفارز",
    "equipment.manage": "إدارة المعدات والإرشادات",
    "settings.edit": "تعديل الإعدادات",
    "audit.view": "عرض سجل التدقيق",
    "command.sync": "مزامنة القيادة (feed / ack / inbox)",
    "admin.users": "لوحة إدارة الحسابات والصلاحيات",
}

ALL_PERMS = list(PERMISSIONS.keys())

ROLE_PRESETS = {
    "admin": ALL_PERMS,
    "operator": [p for p in ALL_PERMS if not p.startswith("admin.") and p != "settings.edit"],
    "supervisor": [
        "dash.view", "tickets.view", "tickets.status", "tickets.forward",
        "files.upload", "files.extract", "estimate.edit", "needs.edit",
        "location.edit", "notes.add", "detect.run", "map.view", "history.view",
        "alerts.view", "audit.view",
    ],
    "viewer": [p for p in ALL_PERMS if p.endswith(".view") and p != "audit.view"],
    "sync": ["command.sync", "tickets.view", "dash.view", "routes.manage", "teams.manage"],
}
ROLE_LABELS = {
    "admin": "مدير النظام",
    "operator": "مشغّل",
    "supervisor": "مشرف",
    "viewer": "مطّلع (عرض فقط)",
    "sync": "حساب مزامنة آلي (للقيادة)",
}

# path rules: (methods, regex, permission). First match wins.
# Concrete request paths like /api/tickets/12/location are matched against these.
PATH_RULES = [
    (("POST",), r"^/api/auth/", None),                      # handled separately
    (("GET",), r"^/api/health$", None),                     # public
    (("GET",), r"^/api/meta$", "dash.view"),
    (("GET",), r"^/api/settings$", "settings.edit"),
    (("PUT",), r"^/api/settings$", "settings.edit"),
    (("GET",), r"^/api/dashboard$", "dash.view"),
    (("GET",), r"^/api/alerts$", "alerts.view"),
    (("GET",), r"^/api/map/layers$", "map.view"),
    (("GET",), r"^/api/search$", "tickets.view"),
    (("GET",), r"^/api/history/near$", "history.view"),
    (("GET",), r"^/api/audit$", "audit.view"),
    (("GET",), r"^/api/command/directives$", "tickets.view"),
    (("GET",), r"^/api/command/feed$", "command.sync"),
    (("POST",), r"^/api/command/ack/", "command.sync"),
    (("POST",), r"^/api/command/inbox$", "command.sync"),
    # tickets
    (("GET",), r"^/api/tickets$", "tickets.view"),
    (("POST",), r"^/api/tickets$", "tickets.create"),
    (("GET",), r"^/api/tickets/\d+$", "tickets.view"),
    (("PUT",), r"^/api/tickets/\d+$", "tickets.edit"),
    (("DELETE",), r"^/api/tickets/\d+$", "tickets.delete"),
    (("PUT",), r"^/api/tickets/\d+/location$", "location.edit"),
    (("DELETE",), r"^/api/tickets/\d+/location$", "location.edit"),
    (("GET",), r"^/api/tickets/\d+/detect$", "detect.run"),
    (("POST",), r"^/api/detect$", "detect.run"),
    (("POST",), r"^/api/tickets/\d+/status$", "tickets.status"),
    (("POST",), r"^/api/tickets/\d+/notes$", "notes.add"),
    (("POST",), r"^/api/tickets/\d+/file$", "files.upload"),
    (("GET",), r"^/api/tickets/\d+/file$", "tickets.view"),
    (("POST",), r"^/api/files/extract-text$", "files.extract"),
    (("POST",), r"^/api/tickets/\d+/estimate/preview$", "estimate.edit"),
    (("PUT",), r"^/api/tickets/\d+/estimate$", "estimate.edit"),
    (("POST",), r"^/api/tickets/\d+/needs/generate$", "needs.edit"),
    (("POST",), r"^/api/tickets/\d+/needs$", "needs.edit"),
    (("PUT",), r"^/api/needs/\d+$", "needs.edit"),
    (("DELETE",), r"^/api/needs/\d+$", "needs.edit"),
    (("POST",), r"^/api/tickets/\d+/forward$", "tickets.forward"),
    (("POST",), r"^/api/simulate/fax$", "tickets.create"),
    # reference data
    (("GET",), r"^/api/routes$", "routes.manage"),
    (("POST",), r"^/api/routes$", "routes.manage"),
    (("PUT",), r"^/api/routes/\d+$", "routes.manage"),
    (("DELETE",), r"^/api/routes/\d+$", "routes.manage"),
    (("GET",), r"^/api/teams$", "teams.manage"),
    (("POST",), r"^/api/teams$", "teams.manage"),
    (("PUT",), r"^/api/teams/\d+$", "teams.manage"),
    (("DELETE",), r"^/api/teams/\d+$", "teams.manage"),
    (("GET",), r"^/api/equipment$", "equipment.manage"),
    (("POST",), r"^/api/equipment$", "equipment.manage"),
    (("PUT",), r"^/api/equipment/\d+$", "equipment.manage"),
    # admin
    (("GET", "POST", "PUT", "DELETE"), r"^/api/admin/", "admin.users"),
    (("POST",), r"^/api/admin/reset-demo$", "admin.users"),
]

# in-memory brute-force guard: key -> (fails, window_start)
_failures = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _throttled(key: str) -> bool:
    fails, start = _failures.get(key, (0, 0))
    if time.time() - start > FAIL_WINDOW:
        return False
    return fails >= MAX_FAILS


def _record_fail(key: str):
    fails, start = _failures.get(key, (0, 0))
    if time.time() - start > FAIL_WINDOW:
        fails, start = 0, time.time()
    _failures[key] = (fails + 1, start)


# ---------------------------------------------------------------- users / sessions
def effective_permissions(user: dict) -> list:
    try:
        perms = json.loads(user.get("permissions") or "[]")
    except (TypeError, ValueError):
        perms = []
    if perms:
        return [p for p in perms if p in PERMISSIONS]
    return list(ROLE_PRESETS.get(user.get("role") or "", []))


def public_user(row) -> dict:
    u = db.row_to_dict(row)
    u.pop("password_hash", None)
    u["permissions"] = effective_permissions(u)
    u["role_label"] = ROLE_LABELS.get(u.get("role"), u.get("role"))
    return u


def get_user_by_username(conn, username: str):
    return db.one(conn, "SELECT * FROM users WHERE username=?", (username.strip(),))


def create_session(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    conn.execute("INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                 (token, user_id, now, now + SESSION_TTL))
    return token


def session_user(conn, token: str):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token=? AND s.expires_at>? AND u.active=1", (token, time.time())).fetchone()
    return db.row_to_dict(row) if row else None


def destroy_session(conn, token: str):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def current_user(request: Request):
    """Dependency: returns the logged-in user dict or raises 401."""
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(401, "يجب تسجيل الدخول أولًا")
    return user


def require_perm(perm: str):
    def _dep(request: Request):
        user = getattr(request.state, "user", None)
        if not user:
            raise HTTPException(401, "يجب تسجيل الدخول أولًا")
        if perm not in effective_permissions(user):
            raise HTTPException(403, "لا تملك صلاحية هذا الإجراء")
        return user
    return _dep


# ---------------------------------------------------------------- auth gate (ASGI middleware)
PUBLIC_EXACT = {"/api/health"}
PUBLIC_PREFIX = ("/api/auth/login", "/api/auth/logout")


class AuthGate:
    """Pure-ASGI middleware: guards /api/* except public endpoints."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIX):
            return await self.app(scope, receive, send)

        from starlette.requests import Request
        request = Request(scope)
        token = request.cookies.get(COOKIE_NAME, "")
        conn = db.connect()
        try:
            user = session_user(conn, token)
        finally:
            conn.close()
        if not user:
            resp = JSONResponse401()
            return await resp(scope, receive, send)

        method = scope.get("method", "GET")
        perm = self._perm_for(method, path)
        user["_perms"] = effective_permissions(user)
        if perm and perm not in user["_perms"]:
            resp = JSONResponse403()
            return await resp(scope, receive, send)

        # stash user on request.state (backed by scope["state"])
        scope.setdefault("state", {})["user"] = user
        return await self.app(scope, receive, send)

    @staticmethod
    def _perm_for(method: str, path: str):
        for methods, pattern, perm in PATH_RULES:
            if method in methods and re.search(pattern, path):
                return perm
        return None  # authenticated is enough


def JSONResponse401():
    from starlette.responses import JSONResponse
    return JSONResponse({"detail": "يجب تسجيل الدخول أولًا"}, status_code=401)


def JSONResponse403():
    from starlette.responses import JSONResponse
    return JSONResponse({"detail": "لا تملك صلاحية هذا الإجراء"}, status_code=403)


# ---------------------------------------------------------------- seeding
def seed_users(conn):
    """Create the built-in accounts if the users table is empty."""
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    t = db.now()
    seeds = [
        # (username, display, password, role, explicit_perms)
        ("admin", "مدير النظام", "Admin@2026", "admin", None),
        ("operator.w", "وائل حمدي", "Wael@2026", "operator", None),
        ("operator.k", "كريم فؤاد", "Karim@2026", "operator", None),
        ("operator.o", "عمر نبيل", "Omar@2026", "operator", None),
        ("sync", "مزامنة شاشة القيادة", "Sync@2026", "sync", None),
    ]
    for username, display, pw, role, perms in seeds:
        conn.execute(
            "INSERT INTO users(username, display_name, password_hash, role, permissions, active, created_at)"
            " VALUES (?,?,?,?,?,1,?)",
            (username, display, hash_password(pw), role,
             json.dumps(perms, ensure_ascii=False) if perms else None, t))
