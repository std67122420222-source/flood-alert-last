"""Application-level risk summaries for forecast data.

This module intentionally does not replace official TMD warnings. It turns the
status levels already calculated by the application into a clear dashboard
summary and adds descriptive forecast metrics.
"""

STATUS_RANK = {
    "green": 0,
    "yellow": 1,
    "orange": 2,
    "red": 3,
    "pending": -1,
}

STATUS_LABELS = {
    "green": "ปกติ",
    "yellow": "เฝ้าระวัง",
    "orange": "ระวังสูง",
    "red": "ระดับรุนแรง",
    "pending": "รอข้อมูล",
}

STATUS_ICONS = {
    "green": "🟢",
    "yellow": "🟡",
    "orange": "🟠",
    "red": "🔴",
    "pending": "⚪",
}


def _safe_numbers(items, key):
    values = []
    for item in items:
        value = item.get(key)
        if value is None:
            continue
        try:
            values.append(float(value))
        except (TypeError, ValueError):
            continue
    return values


def summarize_forecast(items):
    """Return a display-friendly 24-hour summary for one location."""
    if not items:
        return {
            "status": "pending",
            "status_label": STATUS_LABELS["pending"],
            "status_icon": STATUS_ICONS["pending"],
            "items_count": 0,
            "rain_total_24h": None,
            "max_rainfall": None,
            "max_wind_kmh": None,
            "max_temperature": None,
            "min_temperature": None,
            "peak_forecast_at": None,
        }

    status = "green"
    peak_item = None
    for item in items:
        candidate = item.get("status") or "pending"
        if STATUS_RANK.get(candidate, -1) > STATUS_RANK.get(status, -1):
            status = candidate
            peak_item = item

    if peak_item is None:
        peak_item = items[0]

    rainfall = _safe_numbers(items, "rainfall")
    wind_kmh = _safe_numbers(items, "wind_speed_kmh")
    temperatures = _safe_numbers(items, "temperature")

    return {
        "status": status,
        "status_label": STATUS_LABELS.get(status, "รอข้อมูล"),
        "status_icon": STATUS_ICONS.get(status, "⚪"),
        "items_count": len(items),
        "rain_total_24h": round(sum(rainfall), 1) if rainfall else None,
        "max_rainfall": round(max(rainfall), 1) if rainfall else None,
        "max_wind_kmh": round(max(wind_kmh), 1) if wind_kmh else None,
        "max_temperature": round(max(temperatures), 1) if temperatures else None,
        "min_temperature": round(min(temperatures), 1) if temperatures else None,
        "peak_forecast_at": peak_item.get("forecast_at"),
    }


def summarize_areas(areas):
    """Return dashboard-wide status counts and the highest observed level."""
    counts = {
        "total": len(areas),
        "green": 0,
        "yellow": 0,
        "orange": 0,
        "red": 0,
        "pending": 0,
    }

    for area in areas:
        summary = area.get("risk_summary") or summarize_forecast(area.get("items", []))
        status = summary.get("status", "pending")
        if status not in counts:
            status = "pending"
        counts[status] += 1

    highest = "pending"
    for status in ("red", "orange", "yellow", "green"):
        if counts[status] > 0:
            highest = status
            break

    counts["highest_status"] = highest
    counts["highest_label"] = STATUS_LABELS[highest]
    counts["highest_icon"] = STATUS_ICONS[highest]
    counts["note"] = (
        "ระดับนี้เป็นตัวชี้วัดของระบบจาก Forecast และไม่ได้แทนประกาศเตือนภัยอย่างเป็นทางการ"
    )
    return counts
