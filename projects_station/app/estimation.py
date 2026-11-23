"""Rule-based preliminary estimation (cable lengths, splices, converters, equipment, time).

Every coefficient comes from the settings table so the section can tune it, and every output can be
overridden manually after the field survey.
"""
import math

from . import geo

TASK_NATURES = {
    "cable_laying": "مد كابل جديد",
    "fault_repair": "إصلاح عطل / قطع كابل",
    "fiber_splicing": "لحام ألياف بوصلات قائمة",
    "measurement": "قياس واختبار فقط",
}
TERRAINS = {"open": "أرض مفتوحة", "asphalt": "أسفلتية", "urban": "منطقة مأهولة"}

OVERRIDABLE = [
    "total_cable_m",
    "splice_closures",
    "fusion_splices",
    "media_converters",
    "travel_hours",
    "laying_hours",
    "splicing_hours",
    "testing_hours",
    "estimated_hours",
]


def _ceil_to(x, step):
    return int(math.ceil(x / step) * step) if x > 0 else 0


def cable_info(cable_type: str, catalog: dict):
    item = catalog.get(cable_type) or {}
    is_fiber = cable_type.startswith("fiber")
    fibers = 0
    if is_fiber:
        try:
            fibers = int(cable_type.rsplit("_", 1)[1])
        except (IndexError, ValueError):
            fibers = 24
    return is_fiber, fibers, item.get("name", cable_type)


def compute(inputs: dict, settings: dict, catalog: dict, site_point=None) -> dict:
    s = settings
    task = inputs.get("task_nature") or "cable_laying"
    if task not in TASK_NATURES:
        raise ValueError("طبيعة مهمة غير معروفة")
    terrain = inputs.get("terrain") or "open"
    if terrain not in TERRAINS:
        raise ValueError("نوع أرض غير معروف")
    cable_type = inputs.get("cable_type") or s.get("default_cable_type", "fiber_sm_24")
    is_fiber, fibers, cable_name = cable_info(cable_type, catalog)

    reserve = float(inputs.get("reserve_pct") if inputs.get("reserve_pct") not in (None, "") else s["reserve_pct_default"])
    reserve = min(max(reserve, float(s["reserve_pct_min"])), float(s["reserve_pct_max"]))
    measured = float(inputs.get("measured_length_m") or 0)
    if measured < 0:
        raise ValueError("المسافة لا يمكن أن تكون سالبة")
    connection_points = int(inputs.get("connection_points") or 0)
    if connection_points < 0:
        raise ValueError("عدد نقاط الربط لا يمكن أن يكون سالبًا")

    breakdown = []
    if task == "cable_laying":
        net = measured
        breakdown.append(f"الطول الصافي = المسافة المقاسة {measured:,.0f} م")
    elif task == "fault_repair":
        section = float(s["fault_repair_section_m"])
        net = max(section, measured)
        breakdown.append(f"طول قطعة الإصلاح = الأكبر بين المسافة المقاسة ({measured:,.0f} م) وطول القطعة القياسي ({section:,.0f} م)")
    else:
        net = 0.0

    total_cable = _ceil_to(net * (1 + reserve / 100), 10)
    if net:
        breakdown.append(f"الطول الكلي = {net:,.0f} × (1 + {reserve:g}%) مقربًا لأقرب 10 م = {total_cable:,} م")

    drum = float(s["drum_length_fiber_m"] if is_fiber else s["drum_length_copper_m"])
    if task == "cable_laying":
        closures = max(0, math.ceil(total_cable / drum) - 1) if total_cable else 0
        breakdown.append(f"جلب اللحام الوسيطة = ⌈{total_cable:,} ÷ طول البكرة {drum:,.0f}⌉ − 1 = {closures}")
    elif task == "fault_repair":
        closures = 2
        breakdown.append("جلب اللحام = 2 (طرفي قطعة الإصلاح)")
    elif task == "fiber_splicing":
        closures = max(1, int(inputs.get("splice_closures") or 1))
        breakdown.append(f"جلب اللحام = {closures} (حسب الوصلات القائمة)")
    else:
        closures = 0

    fusion = 0
    if is_fiber:
        fusion = closures * fibers + connection_points * fibers
        if fusion:
            breakdown.append(
                f"عدد لحامات الألياف = ({closures} جلبة + {connection_points} نقطة ربط) × {fibers} شعرة = {fusion}"
            )
    converters = 0
    if is_fiber and connection_points:
        converters = connection_points * int(s["converters_per_point"]) + int(s["spare_converters"])
        breakdown.append(
            f"أجهزة Media Converter = {connection_points} نقطة × {s['converters_per_point']} + {s['spare_converters']} احتياطي = {converters}"
        )

    # time
    travel_km = 0.0
    if site_point:
        travel_km = geo.haversine(float(s["base_lat"]), float(s["base_lon"]), site_point[0], site_point[1]) / 1000 * float(
            s["road_factor"]
        )
    travel_h = 2 * travel_km / float(s["travel_speed_kmh"]) if travel_km else 0.0
    laying_h = net / float(s["laying_rate_m_per_hour"]) if task in ("cable_laying", "fault_repair") else 0.0
    splicing_h = (fusion * float(s["fusion_splice_minutes"]) + closures * float(s["closure_prep_minutes"])) / 60
    if not is_fiber and closures:
        splicing_h += closures * float(s["copper_joint_hours"])
    testing_h = float(s["test_base_hours"]) + (closures + connection_points) * float(s["test_per_point_minutes"]) / 60
    factor = float(s[f"terrain_factor_{terrain}"])
    total_h = (travel_h + laying_h + splicing_h + testing_h) * factor
    breakdown.append(
        f"الزمن = (تحرك {travel_h:.1f} + مد {laying_h:.1f} + لحام {splicing_h:.1f} + اختبار {testing_h:.1f}) × معامل الصعوبة {factor:g} = {total_h:.1f} ساعة"
    )

    result = {
        "task_nature": task,
        "terrain": terrain,
        "cable_type": cable_type,
        "cable_name": cable_name,
        "fiber_count": fibers,
        "is_fiber": is_fiber,
        "measured_length_m": round(measured, 1),
        "length_source": inputs.get("length_source") or ("map" if measured else "none"),
        "reserve_pct": reserve,
        "net_length_m": round(net, 1),
        "total_cable_m": total_cable,
        "splice_closures": closures,
        "fusion_splices": fusion,
        "connection_points": connection_points,
        "media_converters": converters,
        "travel_km": round(travel_km, 1),
        "travel_hours": round(travel_h, 2),
        "laying_hours": round(laying_h, 2),
        "splicing_hours": round(splicing_h, 2),
        "testing_hours": round(testing_h, 2),
        "difficulty_factor": factor,
        "estimated_hours": round(total_h, 1),
        "breakdown": breakdown,
    }

    overrides = {k: v for k, v in (inputs.get("overrides") or {}).items() if k in OVERRIDABLE and v not in (None, "")}
    for k, v in overrides.items():
        result[k] = float(v) if "hours" in k else int(float(v))
    if overrides and "estimated_hours" not in overrides and any("hours" in k for k in overrides):
        result["estimated_hours"] = round(
            (result["travel_hours"] + result["laying_hours"] + result["splicing_hours"] + result["testing_hours"]) * factor, 1
        )
    result["manual_overrides"] = overrides
    result["estimated_days"] = round(math.ceil(result["estimated_hours"] / float(s["work_hours_per_day"]) * 10) / 10, 1)
    result["equipment"] = recommend_equipment(result, catalog)
    return result


def _item(catalog, code, qty, reason):
    c = catalog.get(code, {})
    return {
        "code": code,
        "name": c.get("name", code),
        "category": c.get("category", "tool"),
        "unit": c.get("unit", "عدد"),
        "quantity": qty,
        "reason": reason,
        "availability": c.get("default_availability", "available"),
        "guide": c.get("guide", ""),
        "safety": c.get("safety", ""),
    }


def recommend_equipment(r: dict, catalog: dict) -> list:
    items = []
    task, terrain, fiber = r["task_nature"], r["terrain"], r["is_fiber"]
    laying = task in ("cable_laying", "fault_repair")
    if r["total_cable_m"]:
        items.append(_item(catalog, r["cable_type"], r["total_cable_m"], "الطول الكلي شاملًا الاحتياطي والهالك"))
    if r["splice_closures"]:
        items.append(_item(catalog, "splice_closure" if fiber else "copper_joint_kit", r["splice_closures"], "وصلات المسار"))
    if fiber and r["fusion_splices"]:
        items.append(_item(catalog, "splice_sleeves", math.ceil(r["fusion_splices"] * 1.1), "واقيات لحام + 10% احتياطي"))
    if fiber and r["connection_points"]:
        items.append(_item(catalog, "pigtails", r["connection_points"] * r["fiber_count"], "تحويل الأطراف على ODF"))
        items.append(_item(catalog, "odf_panel", r["connection_points"], "لوحة توزيع ألياف لكل نقطة ربط"))
    if r["media_converters"]:
        items.append(_item(catalog, "media_converter", r["media_converters"], "التحويل من ألياف إلى نحاس عند نقاط الربط"))
    if task == "cable_laying" and r["net_length_m"]:
        items.append(_item(catalog, "warning_tape", _ceil_to(r["net_length_m"], 50), "شريط تحذير فوق الكابل بطول المسار"))
        if terrain in ("asphalt", "urban"):
            items.append(_item(catalog, "hdpe_duct", _ceil_to(r["net_length_m"], 50), "حماية الكابل في المناطق الأسفلتية/المأهولة"))
    # tools / devices
    if fiber and r["fusion_splices"]:
        items.append(_item(catalog, "fusion_splicer", 1, "لحام الألياف"))
        items.append(_item(catalog, "fiber_cleaver", 1, "قطع أطراف الألياف قبل اللحام"))
        items.append(_item(catalog, "fiber_tool_kit", 1, "تعرية وتنظيف الألياف"))
    if fiber:
        items.append(_item(catalog, "otdr", 1, "تحديد موقع القطع وقياس الفقد بعد التنفيذ"))
        items.append(_item(catalog, "power_meter", 1, "قياس مستوى الإشارة والاستلام"))
    else:
        items.append(_item(catalog, "copper_tester", 1, "اختبار الأزواج النحاسية"))
    if laying:
        if terrain == "asphalt":
            items.append(_item(catalog, "asphalt_cutter", 1, "قطع الأسفلت لفتح المجرى"))
        if task == "cable_laying" and terrain == "open" and r["net_length_m"] > 1000:
            items.append(_item(catalog, "trencher", 1, "حفر المجرى في الأرض المفتوحة"))
        else:
            items.append(_item(catalog, "excavation_tools", 1, "حفر يدوي"))
        if task == "cable_laying":
            items.append(_item(catalog, "drum_trailer", 1, "نقل وفرد بكرات الكابل"))
            items.append(_item(catalog, "duct_rodder", 1, "سحب الكابل داخل المواسير"))
        if terrain == "urban":
            items.append(_item(catalog, "barriers", 1, "تأمين موقع العمل للمارة والمركبات"))
    if r["splice_closures"] or r["fusion_splices"]:
        items.append(_item(catalog, "generator", 1, "تغذية معدات اللحام في الموقع"))
        items.append(_item(catalog, "splice_tent", 1, "حماية اللحام من الأتربة"))
    return items
