import hashlib
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv

from . import db
from .models import WeatherWarning


load_dotenv()


DEFAULT_WARNING_URL = (
    "https://data.tmd.go.th/api/WeatherWarningNews/v2/?uid=demo&ukey=demokey"
)

WARNING_API_URL = os.getenv(
    "TMD_WARNING_URL",
    DEFAULT_WARNING_URL,
)

WARNING_TIMEOUT = int(
    os.getenv("TMD_WARNING_TIMEOUT", os.getenv("TMD_TIMEOUT", "30"))
)

WARNING_CACHE_MINUTES = int(
    os.getenv("TMD_WARNING_CACHE_MINUTES", "10")
)

WARNING_SOURCE_URL = (
    "https://www.tmd.go.th/warning-and-events/warning-storm"
)


class WarningAPIError(RuntimeError):
    """Raised when the public TMD warning feed cannot be read."""



def get_weather_warnings(force_refresh=False, limit=10):
    """
    Return cached TMD warnings and refresh when stale.

    The public Open Government Data catalog identifies WeatherWarningNews
    as public XML data with no access condition. The default endpoint is
    configurable through TMD_WARNING_URL.
    """
    latest = (
        WeatherWarning.query
        .order_by(WeatherWarning.published_at.desc())
        .limit(limit)
        .all()
    )

    should_refresh = force_refresh or _cache_is_stale()

    if should_refresh:
        try:
            sync_weather_warnings()
            latest = (
                WeatherWarning.query
                .order_by(WeatherWarning.published_at.desc())
                .limit(limit)
                .all()
            )
        except Exception as exc:
            if latest:
                return {
                    "ok": True,
                    "items": [serialize_warning(item) for item in latest],
                    "error": None,
                    "stale": True,
                    "source_url": WARNING_SOURCE_URL,
                }

            return {
                "ok": False,
                "items": [],
                "error": f"โหลดประกาศเตือนภัยจาก TMD ไม่สำเร็จ: {exc}",
                "stale": False,
                "source_url": WARNING_SOURCE_URL,
            }

    return {
        "ok": bool(latest),
        "items": [serialize_warning(item) for item in latest],
        "error": None if latest else "ยังไม่มีประกาศเตือนภัยจาก TMD",
        "stale": False,
        "source_url": WARNING_SOURCE_URL,
    }



def sync_weather_warnings():
    """Fetch the public XML feed from TMD and upsert warning records."""
    response = requests.get(
        WARNING_API_URL,
        timeout=WARNING_TIMEOUT,
        headers={"Accept": "application/xml, text/xml, */*"},
    )
    response.raise_for_status()

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise WarningAPIError(
            "TMD Warning API ส่ง XML ที่อ่านไม่ได้"
        ) from exc

    records = _parse_warning_records(root)

    for item in records:
        existing = (
            WeatherWarning.query
            .filter_by(source_key=item["source_key"])
            .first()
        )

        if existing:
            for field, value in item.items():
                setattr(existing, field, value)
        else:
            db.session.add(WeatherWarning(**item))

    db.session.commit()
    return len(records)



def serialize_warning(item):
    return {
        "id": item.id,
        "issue_no": item.issue_no,
        "title": item.title,
        "headline": item.headline,
        "detail": item.detail,
        "warnings": item.warnings,
        "category": item.category,
        "agency": item.agency,
        "contact": item.contact,
        "published_at": _format_dt(item.published_at),
        "effect_start_at": _format_dt(item.effect_start_at),
        "effect_end_at": _format_dt(item.effect_end_at),
        "source_url": item.source_url or WARNING_SOURCE_URL,
    }



def _parse_warning_records(root):
    field_names = {
        "AnnounceDate",
        "EffectStartDate",
        "EffectEndDate",
        "IssueNo",
        "TitleThai",
        "HeadlineThai",
        "DescriptionThai",
        "Warnings",
        "ContactThai",
        "WebUrlThai",
    }

    candidates = []
    _collect_record_candidates(root, candidates, field_names, is_root=True)

    # Fallback: some XML variants use a direct record element under the root.
    if not candidates:
        for child in list(root):
            values = _collect_fields(child, field_names)
            if len(values) >= 2:
                candidates.append(values)

    records = []
    seen = set()

    for values in candidates:
        title = _clean_text(values.get("TitleThai"))
        headline = _clean_text(values.get("HeadlineThai"))
        description = _clean_text(values.get("DescriptionThai"))
        warnings = _clean_text(values.get("Warnings"))
        issue_no = _clean_text(values.get("IssueNo"))

        if not title:
            title = headline or "ประกาศเตือนภัยลักษณะอากาศ"

        detail = _join_text(
            headline,
            description,
            warnings,
        )

        if not detail:
            detail = title

        published_at = _parse_datetime(
            values.get("AnnounceDate")
        )
        effect_start_at = _parse_datetime(
            values.get("EffectStartDate")
        )
        effect_end_at = _parse_datetime(
            values.get("EffectEndDate")
        )

        source_url = _normalize_url(
            values.get("WebUrlThai")
        )

        source_key = _build_source_key(
            issue_no,
            published_at,
            title,
            detail,
        )

        if source_key in seen:
            continue

        seen.add(source_key)

        records.append(
            {
                "source_key": source_key,
                "issue_no": issue_no or None,
                "title": title,
                "headline": headline or None,
                "detail": detail,
                "warnings": warnings or None,
                "category": "ประกาศเตือนภัย",
                "agency": "กรมอุตุนิยมวิทยา",
                "contact": _clean_text(values.get("ContactThai")) or None,
                "published_at": published_at,
                "effect_start_at": effect_start_at,
                "effect_end_at": effect_end_at,
                "source_url": source_url or WARNING_SOURCE_URL,
            }
        )

    records.sort(
        key=lambda item: item["published_at"] or datetime.min,
        reverse=True,
    )

    return records



def _collect_record_candidates(
    node,
    output,
    field_names,
    is_root=False,
):
    direct_values = _collect_direct_fields(
        node,
        field_names,
    )

    if len(direct_values) >= 2:
        output.append(direct_values)
        return

    for child in list(node):
        _collect_record_candidates(
            child,
            output,
            field_names,
        )



def _collect_direct_fields(node, field_names):
    values = {}

    for child in list(node):
        name = _local_name(child.tag)
        if name not in field_names:
            continue

        values[name] = _element_value(child)

    return values



def _collect_fields(node, field_names):
    values = {}

    for element in node.iter():
        name = _local_name(element.tag)
        if name not in field_names:
            continue

        if name not in values:
            values[name] = _element_value(element)

    return values



def _element_value(element):
    value = element.attrib.get("Value")
    if value:
        return value.strip()

    if element.text and element.text.strip():
        return element.text.strip()

    return ""



def _local_name(tag):
    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag



def _clean_text(value):
    if value is None:
        return ""

    text = re.sub(r"\\s+", " ", str(value)).strip()
    return text



def _join_text(*parts):
    cleaned = []

    for part in parts:
        value = _clean_text(part)
        if value and value not in cleaned:
            cleaned.append(value)

    return "\n\n".join(cleaned)



def _parse_datetime(value):
    if not value:
        return None

    text = _clean_text(value)

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None

    if parsed is None:
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue

    if parsed is None:
        return None

    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)

    return parsed



def _normalize_url(value):
    url = _clean_text(value)
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return ""



def _build_source_key(issue_no, published_at, title, detail):
    raw = "|".join(
        [
            issue_no or "",
            _format_dt(published_at) or "",
            title or "",
            detail or "",
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()



def _format_dt(value):
    if value is None:
        return None
    return value.isoformat(sep=" ", timespec="seconds")



def _cache_is_stale():
    latest = (
        WeatherWarning.query
        .order_by(WeatherWarning.fetched_at.desc())
        .first()
    )

    if latest is None or latest.fetched_at is None:
        return True

    age_seconds = (
        datetime.utcnow() - latest.fetched_at
    ).total_seconds()

    return age_seconds >= WARNING_CACHE_MINUTES * 60
