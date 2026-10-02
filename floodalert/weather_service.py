import logging
import time
from datetime import datetime, timedelta

from . import db
from .models import ForecastData, TrackedArea
from .tmd_api import (
    TMDNotFoundError,
    TMDRateLimitError,
    TMDUnauthorizedError,
    get_hourly_forecast,
    parse_hourly_forecast,
)


logger = logging.getLogger(__name__)
REQUEST_DELAY_SECONDS = 2


def calculate_status(weather):
    """Application-level risk indicator; not an official warning."""
    score = 0

    rainfall = weather.get("rainfall")
    wind_speed = weather.get("wind_speed")

    if rainfall is not None:
        if rainfall >= 50:
            score += 3
        elif rainfall >= 20:
            score += 2
        elif rainfall >= 5:
            score += 1

    if wind_speed is not None:
        wind_kmh = wind_speed * 3.6
        if wind_kmh >= 60:
            score += 3
        elif wind_kmh >= 40:
            score += 2
        elif wind_kmh >= 20:
            score += 1

    if score >= 5:
        return "red"
    if score >= 3:
        return "orange"
    if score >= 1:
        return "yellow"
    return "green"


def collect_forecast_for_area(
    province,
    district=None,
    subdistrict=None,
):
    """Fetch and upsert forecast records for one tracked place."""
    payload, matched_scope = get_hourly_forecast(
        province=province,
        district=district,
        subdistrict=subdistrict,
        return_context=True,
    )

    records = parse_hourly_forecast(
        payload,
        requested_province=matched_scope["province"],
        requested_district=matched_scope["district"],
        requested_subdistrict=matched_scope["subdistrict"],
    )

    if not records:
        logger.warning(
            "TMD returned no forecast records: %s / %s / %s",
            province,
            district,
            subdistrict,
        )
        return 0

    saved_count = 0

    try:
        for item in records:
            item["status_level"] = calculate_status(item)

            existing = (
                ForecastData.query
                .filter_by(
                    province=item["province"],
                    district=item["district"],
                    subdistrict=item["subdistrict"],
                    forecast_at=item["forecast_at"],
                )
                .first()
            )

            if existing:
                _update_forecast_record(existing, item)
            else:
                db.session.add(ForecastData(**item))

            saved_count += 1

        db.session.commit()
        return saved_count

    except Exception:
        db.session.rollback()
        raise


def collect_forecast_for_tracked_areas():
    """Refresh unique tracked places sequentially to reduce 429 responses."""
    areas = (
        TrackedArea.query
        .order_by(
            TrackedArea.id
        )
        .all()
    )

    unique_places = []
    seen = set()

    for area in areas:
        province = (area.province or "").strip()
        district = (area.district or "").strip()
        subdistrict = (area.subdistrict or "").strip()

        if not province:
            continue

        key = (province, district, subdistrict)
        if key in seen:
            continue

        seen.add(key)
        unique_places.append(key)

    total = 0

    for index, (province, district, subdistrict) in enumerate(unique_places):
        try:
            total += collect_forecast_for_area(
                province=province,
                district=district or None,
                subdistrict=subdistrict or None,
            )

        except TMDNotFoundError as exc:
            db.session.rollback()
            logger.warning("TMD place not found: %s", exc)

        except TMDRateLimitError as exc:
            db.session.rollback()
            logger.warning("TMD rate limit reached: %s", exc)
            continue

        except TMDUnauthorizedError as exc:
            db.session.rollback()
            logger.error("TMD authentication failed: %s", exc)
            break

        except Exception:
            db.session.rollback()
            logger.exception(
                "Forecast update failed for %s / %s / %s",
                province,
                district,
                subdistrict,
            )

        if index < len(unique_places) - 1:
            time.sleep(REQUEST_DELAY_SECONDS)

    _cleanup_old_forecasts()
    return total


def get_forecast_for_area(
    province,
    district=None,
    subdistrict=None,
    hours=24,
):
    """Read the latest stored forecast window for a place."""
    query = ForecastData.query.filter(
        ForecastData.province == province
    )

    if district:
        query = query.filter(
            ForecastData.district == district
        )

    if subdistrict:
        query = query.filter(
            ForecastData.subdistrict == subdistrict
        )

    start = datetime.utcnow()
    end = start + timedelta(hours=hours)

    return (
        query
        .filter(
            ForecastData.forecast_at >= start,
            ForecastData.forecast_at <= end,
        )
        .order_by(
            ForecastData.forecast_at.asc()
        )
        .all()
    )


def _update_forecast_record(record, item):
    for field, value in item.items():
        setattr(record, field, value)


def _cleanup_old_forecasts(days=3):
    cutoff = datetime.utcnow() - timedelta(days=days)

    (
        ForecastData.query
        .filter(
            ForecastData.forecast_at < cutoff
        )
        .delete(synchronize_session=False)
    )

    db.session.commit()
