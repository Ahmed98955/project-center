"""Local IAM for the Commander Screen — mirrors the station's design.
Offline only: PBKDF2 password hashing + SQLite sessions + cookie auth."""
import hashlib
import hmac
import json
import os
import re
import secrets
import time

from fastapi import HTTPException, Request

from . import db

SESSION_TTL = 12 * 3600
PBKDF2_ITERATIONS = 120_000
COOKIE_NAME = "cs_session"
MAX_FAILS = 8
FAIL_WINDOW = 300


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


PERMISSIONS = {
    "dash.view": "عرض لوحة المؤشرات وحالة الاتصال",
    "tickets.view": "عرض العمليات والفاكسات الممررة وملفاتها",
    "map.view": "عرض الخريطة العملياتية",
    "ops.view": "عرض سجل العمليات",
    "activity.view": "عرض آخر المستجدات",
    "reference.view": "عرض البيانات المرجعية",
    "alerts.view": "عرض التنبيهات",
    "alerts.ack": "تأكيد الاطلاع على التنبيه",
    "commands.availability": "تصديق بنود الاحتياجات",
    "commands.priority": "تغيير أولوية العملية",
    "commands.directive": "إرسال توجيه مكتوب",
    "commands.seen": "تأكيد الاطلاع على بلاغ",
    "commands.log": "عرض سجل الأوامر الصادرة",
    "settings.edit": "تعديل إعدادات المزامنة",
    "admin.users": "لوحة إدارة الحسابات والصلاحيات",
}

ALL_PERMS = list(PERMISSIONS.keys())

ROLE_PRESETS = {
    "admin": ALL_PERMS,
    "commander": [p for p in ALL_PERMS if p != "admin.users"],
    "viewer": [p for p in ALL_PERMS if p.endswith(".view")],
}
ROLE_LABELS = {
    "admin": "مدير النظام",
    "commander": "قائد",
    "viewer": "مطّلع (عرض فقط)",
}

PATH_RULES = [
    (("GET",), r"^/api/health$", None),
    (("GET",), r"^/api/meta$", "dash.view"),
    (("GET",), r"^/api/dashboard$", "dash.view"),
    (("GET",), r"^/api/tickets$", "tickets.view"),
    (("GET",), r"^/api/tickets/\d+$", "tickets.view"),
    (("GET",), r"^/api/tickets/\d+/file$", "tickets.view"),
    (("GET",), r"^/api/activity$", "activity.view"),
    (("GET",), r"^/api/reference$", "reference.view"),
    (("GET",), r"^/api/map/layers$", "map.view"),
    (("GET",), r"^/api/alerts$", "alerts.view"),
    (("POST",), r"^/api/alerts/\d+/ack$", "alerts.ack"),
    (("POST",), r"^/api/commands/availability$", "commands.availability"),
    (("POST",), r"^/api/commands/priority$", "commands.priority"),
    (("POST",), r"^/api/commands/directive$", "commands.directive"),
    (("POST",), r"^/api/commands/seen$", "commands.seen"),
    (("GET",), r"^/api/commands/log$", "commands.log"),
    (("GET",), r"^/api/events$", "tickets.view"),
    (("PUT",), r"^/api/settings$", "settings.edit"),
    (("GET", "POST", "PUT", "DELETE"), r"^/api/admin/", "admin.users"),
]

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


PUBLIC_EXACT = {"/api/health"}
PUBLIC_PREFIX = ("/api/auth/login", "/api/auth/logout")


class AuthGate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIX):
            return await self.app(scope, receive, send)

        from starlette.requests import Request
        from starlette.responses import JSONResponse
        request = Request(scope)
        token = request.cookies.get(COOKIE_NAME, "")
        conn = db.connect()
        try:
            user = session_user(conn, token)
        finally:
            conn.close()
        if not user:
            return await JSONResponse({"detail": "يجب تسجيل الدخول أولًا"}, status_code=401)(scope, receive, send)

        method = scope.get("method", "GET")
        perm = self._perm_for(method, path)
        user["_perms"] = effective_permissions(user)
        if perm and perm not in user["_perms"]:
            return await JSONResponse({"detail": "لا تملك صلاحية هذا الإجراء"}, status_code=403)(scope, receive, send)

        scope.setdefault("state", {})["user"] = user
        return await self.app(scope, receive, send)

    @staticmethod
    def _perm_for(method: str, path: str):
        for methods, pattern, perm in PATH_RULES:
            if method in methods and re.search(pattern, path):
                return perm
        return None


def seed_users(conn):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        return
    t = db.now()
    seeds = [
        ("admin", "مدير النظام", "Admin@2026", "admin", None),
        ("commander.h", "قائد الفرقة — م. هشام فاروق", "Hisham@2026", "commander", None),
        ("viewer.n", "مطّلع — نادر سمير", "Nader@2026", "viewer", None),
    ]
    for username, display, pw, role, perms in seeds:
        conn.execute(
            "INSERT INTO users(username, display_name, password_hash, role, permissions, active, created_at)"
            " VALUES (?,?,?,?,?,1,?)",
            (username, display, hash_password(pw), role,
             json.dumps(perms, ensure_ascii=False) if perms else None, t))
