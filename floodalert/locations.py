"""Thailand administrative hierarchy loader.

The app keeps the 77-province list locally and lazily downloads a current
province/district/subdistrict hierarchy from an openly published dataset.
The downloaded hierarchy is cached under app/data so subsequent requests do
not need a network call.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

from .provinces import THAI_PROVINCES


SOURCE_URL = (
    "https://raw.githubusercontent.com/"
    "open-admin-data/thailand-administrative-divisions/"
    "main/data/hierarchy.json"
)

CACHE_PATH = Path(__file__).resolve().parent / "data" / "thailand_hierarchy.json"
CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60
REQUEST_TIMEOUT = 20


class LocationCatalogError(RuntimeError):
    """Raised when the administrative hierarchy cannot be loaded."""


def get_provinces() -> list[str]:
    return list(THAI_PROVINCES)


def get_districts(province: str) -> list[str]:
    catalog = _load_catalog()
    province_node = _find_province(catalog, province)

    if province_node is None:
        return []

    return [
        district["name"]["local"]
        for district in province_node.get("district", [])
    ]


def get_subdistricts(province: str, district: str) -> list[str]:
    catalog = _load_catalog()
    province_node = _find_province(catalog, province)

    if province_node is None:
        return []

    district_node = _find_district(
        province_node,
        district,
    )

    if district_node is None:
        return []

    return [
        item["name"]["local"]
        for item in district_node.get("subdistrict", [])
    ]


def refresh_catalog() -> dict:
    """Download and cache the full hierarchy now."""
    data = _download_catalog()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(data, ensure_ascii=False),
        encoding="utf-8",
    )
    return data


def _load_catalog() -> dict:
    if CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age <= CACHE_MAX_AGE_SECONDS:
            return _read_cache()

    try:
        return refresh_catalog()
    except Exception as exc:
        if CACHE_PATH.exists():
            return _read_cache()
        raise LocationCatalogError(
            "โหลดฐานข้อมูลจังหวัด/อำเภอ/ตำบลไม่สำเร็จ"
        ) from exc


def _read_cache() -> dict:
    try:
        return json.loads(
            CACHE_PATH.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        raise LocationCatalogError(
            "ไฟล์ฐานข้อมูลพื้นที่เสียหาย"
        ) from exc


def _download_catalog() -> dict:
    response = requests.get(
        SOURCE_URL,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise LocationCatalogError(
            "รูปแบบฐานข้อมูลพื้นที่ไม่ถูกต้อง"
        )

    return data


def _find_province(catalog: dict, province: str) -> dict | None:
    target = _normalize(province)

    for item in catalog.get("data", []):
        name = item.get("name", {}).get("local", "")
        if _normalize(name) == target:
            return item

    return None


def _find_district(province_node: dict, district: str) -> dict | None:
    target = _normalize(district)

    for item in province_node.get("district", []):
        name = item.get("name", {}).get("local", "")
        if _normalize(name) == target:
            return item

    return None


def _normalize(value: str) -> str:
    return " ".join(str(value or "").strip().split())
