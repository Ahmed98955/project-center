from datetime import datetime
from typing import Optional

STATUSES = [
    ("new", "وارد جديد"),
    ("awaiting_coordination", "انتظار التنسيق / التصديق"),
    ("preparing", "قيد التجهيز"),
    ("in_progress", "جاري التنفيذ الميداني"),
    ("closed", "مغلق وموثق"),
]
STATUS_LABELS = dict(STATUSES)

TRANSITIONS = {
    "new": ["awaiting_coordination", "preparing"],
    "awaiting_coordination": ["preparing", "new"],
    "preparing": ["in_progress", "awaiting_coordination"],
    "in_progress": ["closed", "preparing"],
    "closed": [],
}

FAX_TYPES = {"fault": "عطل", "project": "مشروع إنشاء", "coordination": "طلب تنسيق"}
PRIORITIES = {"critical": "حرجة", "high": "عالية", "normal": "عادية", "low": "منخفضة"}


class TransitionError(ValueError):
    pass


def allowed_next(status: str):
    return TRANSITIONS.get(status, [])


def check_transition(ticket: dict, new_status: str, payload: dict) -> None:
    old = ticket["status"]
    if new_status not in STATUS_LABELS:
        raise TransitionError("حالة غير معروفة")
    if new_status not in allowed_next(old):
        raise TransitionError(
            f"لا يمكن الانتقال من «{STATUS_LABELS.get(old, old)}» إلى «{STATUS_LABELS[new_status]}»"
        )
    if new_status == "in_progress":
        team = payload.get("assigned_team") or ticket.get("assigned_team")
        if not team:
            raise TransitionError("يجب تحديد المفرزة المكلفة قبل بدء التنفيذ الميداني")
        if not (ticket.get("geometry_json") or payload.get("geometry_json")):
            raise TransitionError("يجب تحديد الموقع على الخريطة قبل بدء التنفيذ الميداني")
    if new_status == "closed":
        resolution = (payload.get("resolution") or ticket.get("resolution") or "").strip()
        if not resolution:
            raise TransitionError("يجب كتابة الإجراءات المتخذة قبل الإغلاق والتوثيق")
        if ticket["fax_type"] == "fault":
            cause = (payload.get("cause") or ticket.get("cause") or "").strip()
            if not cause:
                raise TransitionError("يجب تسجيل سبب العطل قبل الإغلاق (يُستخدم في التنبيهات المستقبلية)")


def hours_since(ts: str, ref: Optional[datetime] = None) -> float:
    if not ts:
        return 0.0
    ref = ref or datetime.now()
    return max(0.0, (ref - datetime.fromisoformat(ts)).total_seconds() / 3600)


def wait_info(ticket: dict, max_hours: float, ref: Optional[datetime] = None) -> dict:
    in_state = hours_since(ticket["status_changed_at"], ref)
    waiting = ticket["status"] == "awaiting_coordination"
    return {
        "hours_in_status": round(in_state, 1),
        "waiting": waiting,
        "overdue": waiting and in_state > max_hours,
        "max_hours": max_hours,
    }
