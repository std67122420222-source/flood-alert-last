import os
from datetime import datetime, timedelta
from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from . import db
from .locations import (
    LocationCatalogError,
    get_districts,
    get_provinces,
    get_subdistricts,
)
from .models import ForecastData, TrackedArea, WeatherData
from .provinces import THAI_PROVINCES
from .risk_service import summarize_forecast
from .weather_service import (
    collect_forecast_for_area,
    get_forecast_for_area,
)
from .warning_service import (
    get_weather_warnings,
)


main = Blueprint("main", __name__)


@main.route("/healthz")
def healthz():
    return jsonify({"ok": True, "service": "flood-alert"})


@main.route("/api/cron/refresh")
def cron_refresh():
    """Refresh tracked forecasts and warnings from a scheduled HTTP call.

    Vercel is request-driven, so this replaces the long-lived APScheduler
    thread used by local/Render deployments. Vercel Cron sends the secret
    as an Authorization bearer token.
    """
    expected = request.environ.get("HTTP_X_CRON_SECRET") or request.headers.get("Authorization", "")
    configured = os.getenv("CRON_SECRET", "").strip()

    if os.getenv("VERCEL"):
        if not configured:
            return jsonify({"ok": False, "error": "CRON_SECRET is not configured"}), 503
        if expected != f"Bearer {configured}" and expected != configured:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401

    try:
        from .weather_service import collect_forecast_for_tracked_areas

        forecast_saved = collect_forecast_for_tracked_areas()

        from .warning_service import sync_weather_warnings

        warnings_saved = sync_weather_warnings()

        return jsonify({
            "ok": True,
            "forecast_saved": forecast_saved,
            "warnings_saved": warnings_saved,
        })
    except Exception as exc:
        db.session.rollback()
        return jsonify({
            "ok": False,
            "error": str(exc),
        }), 500


def get_latest_weather_by_province(areas):
    weather_by_area = {}

    for area in areas:
        weather = (
            WeatherData.query
            .filter_by(province=area.province)
            .order_by(WeatherData.observed_at.desc())
            .first()
        )
        weather_by_area[area.id] = weather

    return weather_by_area


def serialize_forecast(row):
    return {
        "province": row.province,
        "district": row.district,
        "subdistrict": row.subdistrict,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "forecast_at": row.forecast_at.isoformat(),
        "temperature": row.temperature,
        "relative_humidity": row.relative_humidity,
        "rainfall": row.rainfall,
        "wind_speed": row.wind_speed,
        "wind_speed_kmh": (
            round(row.wind_speed * 3.6, 1)
            if row.wind_speed is not None
            else None
        ),
        "wind_direction": row.wind_direction,
        "pressure": row.pressure,
        "condition": row.condition,
        "status": row.status_level,
    }


@main.route("/")
def index():
    return render_template("index.html")


def get_public_forecast_areas(limit=100):
    """Return distinct cached forecast locations without loading whole rows."""
    rows = (
        db.session.query(
            ForecastData.province,
            ForecastData.district,
            ForecastData.subdistrict,
        )
        .distinct()
        .order_by(
            ForecastData.province,
            ForecastData.district,
            ForecastData.subdistrict,
        )
        .limit(limit)
        .all()
    )

    return [
        (province, district or "", subdistrict or "")
        for province, district, subdistrict in rows
    ]


@main.route("/dashboard")
def dashboard():
    """Render the dashboard shell quickly.

    Heavy data (Forecast and official warnings) is loaded by the browser
    after the HTML shell is visible. This keeps navigation snappy and avoids
    making page rendering wait for an external TMD request.
    """
    if current_user.is_authenticated:
        areas = (
            TrackedArea.query
            .filter_by(user_id=current_user.id)
            .order_by(
                TrackedArea.province,
                TrackedArea.district,
                TrackedArea.subdistrict,
            )
            .all()
        )
    else:
        areas = []

    return render_template(
        "dashboard.html",
        areas=areas,
        provinces=THAI_PROVINCES,
        is_public_dashboard=not current_user.is_authenticated,
        public_forecast_locations=[],
    )


@main.route("/areas/add", methods=["POST"])
@login_required
def add_area():
    province = request.form.get("province", "").strip()
    district = request.form.get("district", "").strip()
    subdistrict = request.form.get("subdistrict", "").strip()

    if not province:
        flash("กรุณาระบุจังหวัด", "danger")
        return redirect(url_for("main.dashboard"))

    existing = (
        TrackedArea.query
        .filter_by(
            user_id=current_user.id,
            province=province,
            district=district,
            subdistrict=subdistrict,
        )
        .first()
    )

    if existing:
        flash("พื้นที่นี้ถูกเพิ่มไว้แล้ว", "warning")
        return redirect(url_for("main.dashboard"))

    area = TrackedArea(
        province=province,
        district=district or None,
        subdistrict=subdistrict or None,
        user_id=current_user.id,
    )

    db.session.add(area)
    db.session.commit()

    try:
        saved_count = collect_forecast_for_area(
            province=province,
            district=district or None,
            subdistrict=subdistrict or None,
        )

        flash(
            f"เพิ่มพื้นที่แล้ว และโหลดพยากรณ์ {saved_count} รายการ",
            "success",
        )
    except Exception as exc:
        flash(
            f"เพิ่มพื้นที่แล้ว แต่โหลด TMD ไม่สำเร็จ: {exc}",
            "warning",
        )

    return redirect(url_for("main.dashboard"))


@main.route("/areas/delete/<int:area_id>", methods=["POST"])
@login_required
def delete_area(area_id):
    area = (
        TrackedArea.query
        .filter_by(
            id=area_id,
            user_id=current_user.id,
        )
        .first_or_404()
    )

    db.session.delete(area)
    db.session.commit()

    flash("ลบพื้นที่แล้ว", "success")
    return redirect(url_for("main.dashboard"))


@main.route("/api/provinces")
def api_provinces():
    return jsonify({
        "ok": True,
        "items": get_provinces(),
    })


@main.route("/api/locations/districts")
def api_districts():
    province = request.args.get("province", "").strip()

    if not province:
        return jsonify({
            "ok": False,
            "error": "กรุณาระบุจังหวัด",
            "items": [],
        }), 400

    try:
        districts = get_districts(province)
    except LocationCatalogError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "items": [],
        }), 503

    return jsonify({
        "ok": True,
        "province": province,
        "items": districts,
    })


@main.route("/api/locations/subdistricts")
def api_subdistricts():
    province = request.args.get("province", "").strip()
    district = request.args.get("district", "").strip()

    if not province or not district:
        return jsonify({
            "ok": False,
            "error": "กรุณาระบุจังหวัดและอำเภอ/เขต",
            "items": [],
        }), 400

    try:
        subdistricts = get_subdistricts(
            province,
            district,
        )
    except LocationCatalogError as exc:
        return jsonify({
            "ok": False,
            "error": str(exc),
            "items": [],
        }), 503

    return jsonify({
        "ok": True,
        "province": province,
        "district": district,
        "items": subdistricts,
    })


@main.route("/api/weather")
@login_required
def api_weather():
    areas = (
        TrackedArea.query
        .filter_by(user_id=current_user.id)
        .order_by(TrackedArea.province, TrackedArea.district)
        .all()
    )

    weather_by_area = get_latest_weather_by_province(areas)
    data = []

    for area in areas:
        weather = weather_by_area.get(area.id)
        if weather is None:
            continue

        data.append(
            {
                "area_id": area.id,
                "province": area.province,
                "district": area.district,
                "subdistrict": area.subdistrict,
                "station": weather.station_name,
                "temperature": weather.air_temperature,
                "rainfall": weather.rainfall,
                "rainfall_24h": weather.rainfall_24h,
                "humidity": weather.relative_humidity,
                "wind_speed": weather.wind_speed,
                "pressure": weather.pressure,
                "status": weather.status_level,
                "latitude": weather.latitude,
                "longitude": weather.longitude,
                "observed_at": weather.observed_at.isoformat(),
            }
        )

    return jsonify(data)


@main.route("/api/forecast")
def api_forecast():
    province = request.args.get("province", "").strip()
    district = request.args.get("district", "").strip()
    subdistrict = request.args.get("subdistrict", "").strip()

    if not province:
        return jsonify({
            "ok": False,
            "error": "กรุณาระบุ province",
        }), 400

    rows = get_forecast_for_area(
        province=province,
        district=district or None,
        subdistrict=subdistrict or None,
        hours=24,
    )

    return jsonify({
        "ok": True,
        "province": province,
        "district": district,
        "subdistrict": subdistrict,
        "items": [serialize_forecast(row) for row in rows],
    })


@main.route("/api/forecast/all")
def api_forecast_all():
    """Return all requested forecast areas with one database read.

    The previous implementation issued one SQL query per area. Grouping a
    single 24-hour result set avoids N+1 queries and makes large dashboards
    noticeably faster.
    """
    if current_user.is_authenticated:
        tracked_areas = (
            TrackedArea.query
            .filter_by(user_id=current_user.id)
            .order_by(
                TrackedArea.province,
                TrackedArea.district,
                TrackedArea.subdistrict,
            )
            .all()
        )

        locations = [
            (
                area.id,
                area.province,
                area.district or "",
                area.subdistrict or "",
            )
            for area in tracked_areas
        ]
    else:
        locations = [
            (
                f"public-{index}",
                province,
                district,
                subdistrict,
            )
            for index, (province, district, subdistrict)
            in enumerate(get_public_forecast_areas(), start=1)
        ]

    if not locations:
        return jsonify({
            "ok": True,
            "public": not current_user.is_authenticated,
            "areas": [],
        })

    now = datetime.utcnow()
    end = now + timedelta(hours=24)
    provinces = sorted({location[1] for location in locations if location[1]})

    query = ForecastData.query.filter(
        ForecastData.forecast_at >= now,
        ForecastData.forecast_at <= end,
    )
    if provinces:
        query = query.filter(ForecastData.province.in_(provinces))

    rows = (
        query
        .order_by(ForecastData.forecast_at.asc())
        .all()
    )

    grouped = {}
    for row in rows:
        key = (
            row.province,
            row.district or "",
            row.subdistrict or "",
        )
        grouped.setdefault(key, []).append(serialize_forecast(row))

    result = []
    for area_id, province, district, subdistrict in locations:
        items = grouped.get((province, district, subdistrict), [])
        result.append({
            "area_id": area_id,
            "province": province,
            "district": district,
            "subdistrict": subdistrict,
            "items": items,
            "risk_summary": summarize_forecast(items),
        })

    return jsonify({
        "ok": True,
        "public": not current_user.is_authenticated,
        "areas": result,
    })


@main.route("/api/warnings")
def api_warnings():
    force_refresh = request.args.get("refresh") == "1"
    return jsonify(
        get_weather_warnings(
            force_refresh=force_refresh,
            limit=10,
        )
    )
