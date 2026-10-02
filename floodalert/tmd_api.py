import os
import time
from datetime import datetime, timezone

import requests
from dotenv import load_dotenv


load_dotenv()

TMD_FORECAST_URL = os.getenv(
    "TMD_FORECAST_URL",
    "https://data.tmd.go.th/nwpapi/v1/forecast/location/hourly/place",
)
TMD_ACCESS_TOKEN = os.getenv("TMD_ACCESS_TOKEN")
TMD_TIMEOUT = int(os.getenv("TMD_TIMEOUT", "30"))
TMD_FORECAST_HOURS = int(os.getenv("TMD_FORECAST_HOURS", "24"))
TMD_MAX_RETRIES = int(os.getenv("TMD_MAX_RETRIES", "3"))
TMD_RETRY_BASE_SECONDS = float(os.getenv("TMD_RETRY_BASE_SECONDS", "5"))
TMD_REQUEST_DELAY_SECONDS = float(os.getenv("TMD_REQUEST_DELAY_SECONDS", "2"))
TMD_FORECAST_FIELDS = os.getenv(
    "TMD_FORECAST_FIELDS",
    "tc,rh,slp,rain,ws10m,wd10m,cond",
)


class TMDNotFoundError(RuntimeError):
    """The requested place is not available in TMD's place index."""


class TMDRateLimitError(RuntimeError):
    """TMD returned HTTP 429."""


class TMDUnauthorizedError(RuntimeError):
    """TMD returned HTTP 401."""


def get_hourly_forecast(
    province,
    district=None,
    subdistrict=None,
    return_context=False,
):
    """Request hourly NWP forecast with place-level fallback and 429 retry."""
    if not TMD_ACCESS_TOKEN:
        raise RuntimeError("กรุณากำหนด TMD_ACCESS_TOKEN ใน .env")

    requested = {
        "province": _clean(province),
        "district": _clean(district),
        "subdistrict": _clean(subdistrict),
    }

    if not requested["province"]:
        raise ValueError("ต้องระบุจังหวัด")

    scopes = _build_scopes(requested)
    last_not_found = None

    for scope in scopes:
        try:
            payload = _request_forecast(scope)
        except TMDNotFoundError as exc:
            last_not_found = exc
            continue

        if return_context:
            return payload, scope

        return payload

    if last_not_found:
        raise TMDNotFoundError(
            "TMD ไม่พบชื่อสถานที่ในทุกระดับ: "
            f"จังหวัด='{requested['province']}', "
            f"อำเภอ='{requested['district']}', "
            f"ตำบล='{requested['subdistrict']}'"
        )

    raise RuntimeError("ไม่สามารถเรียก TMD Forecast API ได้")


def _request_forecast(scope):
    params = {
        "province": scope["province"],
        "duration": TMD_FORECAST_HOURS,
        "fields": TMD_FORECAST_FIELDS,
    }

    if scope["district"]:
        params["amphoe"] = scope["district"]

    if scope["subdistrict"]:
        params["tambon"] = scope["subdistrict"]

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {TMD_ACCESS_TOKEN}",
    }

    last_rate_limit = False

    for attempt in range(TMD_MAX_RETRIES + 1):
        if attempt > 0:
            time.sleep(
                TMD_RETRY_BASE_SECONDS * (2 ** (attempt - 1))
            )

        response = requests.get(
            TMD_FORECAST_URL,
            params=params,
            headers=headers,
            timeout=TMD_TIMEOUT,
        )

        if response.status_code == 401:
            raise TMDUnauthorizedError(
                "TMD Access Token ไม่ถูกต้องหรือหมดอายุ"
            )

        if response.status_code == 404:
            raise TMDNotFoundError(
                "TMD ไม่พบพื้นที่: "
                f"{scope['province']} / "
                f"{scope['district']} / "
                f"{scope['subdistrict']}"
            )

        if response.status_code == 429:
            last_rate_limit = True

            if attempt >= TMD_MAX_RETRIES:
                break

            retry_after = _parse_retry_after(
                response.headers.get("Retry-After")
            )

            if retry_after is not None:
                time.sleep(retry_after)

            continue

        if 500 <= response.status_code <= 599:
            if attempt < TMD_MAX_RETRIES:
                continue

        response.raise_for_status()

        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError(
                "TMD ส่งข้อมูลที่ไม่ใช่ JSON"
            ) from exc

    if last_rate_limit:
        raise TMDRateLimitError(
            f"TMD API rate limit exceeded หลัง retry {TMD_MAX_RETRIES} ครั้ง"
        )

    raise RuntimeError("TMD Forecast API ล้มเหลว")


def parse_hourly_forecast(
    payload,
    requested_province=None,
    requested_district=None,
    requested_subdistrict=None,
):
    """Normalize TMD response into flat forecast records."""
    locations = _extract_locations(payload)
    records = []

    for location in locations:
        if not isinstance(location, dict):
            continue

        location_info = location.get("location", location)

        province = _first_value(
            location_info,
            "province",
            "Province",
        ) or requested_province or ""

        district = _first_value(
            location_info,
            "amphoe",
            "district",
            "Amphoe",
        ) or requested_district or ""

        subdistrict = _first_value(
            location_info,
            "tambon",
            "subdistrict",
            "Tambon",
        ) or requested_subdistrict or ""

        latitude = _to_float(
            _first_value(
                location_info,
                "lat",
                "latitude",
                "Latitude",
            )
        )

        longitude = _to_float(
            _first_value(
                location_info,
                "lon",
                "longitude",
                "Longitude",
            )
        )

        forecasts = (
            location.get("forecasts")
            or location.get("forecast")
            or []
        )

        if not isinstance(forecasts, list):
            continue

        for item in forecasts:
            if not isinstance(item, dict):
                continue

            forecast_time = _parse_datetime(
                item.get("time")
                or item.get("forecastTime")
                or item.get("datetime")
            )

            if forecast_time is None:
                continue

            data = (
                item.get("data")
                or item.get("Data")
                or item
            )

            if not isinstance(data, dict):
                data = {}

            records.append(
                {
                    "province": province,
                    "district": district,
                    "subdistrict": subdistrict,
                    "latitude": latitude,
                    "longitude": longitude,
                    "forecast_at": forecast_time,
                    "temperature": _to_float(
                        _first_value(data, "tc", "temperature", "temp")
                    ),
                    "relative_humidity": _to_float(
                        _first_value(data, "rh", "humidity")
                    ),
                    "rainfall": _to_float(
                        _first_value(data, "rain", "rainfall")
                    ),
                    "wind_speed": _to_float(
                        _first_value(data, "ws10m", "wind_speed", "ws")
                    ),
                    "wind_direction": _to_float(
                        _first_value(data, "wd10m", "wind_direction", "wd")
                    ),
                    "pressure": _to_float(
                        _first_value(data, "slp", "pressure")
                    ),
                    "condition": _first_value(
                        data,
                        "cond",
                        "condition",
                    ),
                }
            )

    return records


def _build_scopes(requested):
    scopes = []

    if requested["subdistrict"]:
        scopes.append(
            {
                "province": requested["province"],
                "district": requested["district"],
                "subdistrict": requested["subdistrict"],
            }
        )

    if requested["district"]:
        scopes.append(
            {
                "province": requested["province"],
                "district": requested["district"],
                "subdistrict": None,
            }
        )

    scopes.append(
        {
            "province": requested["province"],
            "district": None,
            "subdistrict": None,
        }
    )

    return list(_unique_scopes(scopes))


def _extract_locations(payload):
    if not isinstance(payload, dict):
        return []

    for key in (
        "WeatherForcasts",
        "WeatherForecasts",
        "weatherForecasts",
        "data",
        "locations",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return value

    for value in payload.values():
        if isinstance(value, list) and any(
            isinstance(item, dict) for item in value
        ):
            return value

    return []


def _first_value(data, *keys):
    if not isinstance(data, dict):
        return None

    for key in keys:
        value = data.get(key)
        if value is not None and value != "":
            return value

    return None


def _to_float(value):
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean(value):
    return str(value or "").strip()


def _unique_scopes(scopes):
    seen = set()

    for scope in scopes:
        key = (
            scope["province"],
            scope["district"],
            scope["subdistrict"],
        )

        if key in seen:
            continue

        seen.add(key)
        yield scope


def _parse_retry_after(value):
    if value is None:
        return None

    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return None


def _parse_datetime(value):
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    text = str(value).strip()

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError:
        pass

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue

    return datetime.now(timezone.utc).replace(tzinfo=None)
