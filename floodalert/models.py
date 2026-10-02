from datetime import datetime

from flask_login import UserMixin

from . import db


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    areas = db.relationship(
        "TrackedArea",
        backref="user",
        lazy=True,
        cascade="all, delete-orphan",
    )


class TrackedArea(db.Model):
    __tablename__ = "tracked_area"

    id = db.Column(db.Integer, primary_key=True)
    province = db.Column(db.String(100), nullable=False, index=True)
    district = db.Column(db.String(100), index=True)
    subdistrict = db.Column(db.String(100), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Alert(db.Model):
    __tablename__ = "alert"

    id = db.Column(db.Integer, primary_key=True)
    province = db.Column(db.String(100), nullable=False)
    district = db.Column(db.String(100))
    title = db.Column(db.String(255), nullable=False)
    detail = db.Column(db.Text)
    level = db.Column(db.String(30), nullable=False)
    source = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Notification(db.Model):
    __tablename__ = "notification"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    alert_id = db.Column(db.Integer, db.ForeignKey("alert.id"), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class WeatherData(db.Model):
    __tablename__ = "weather_data"

    id = db.Column(db.Integer, primary_key=True)
    station_code = db.Column(db.String(50), index=True)
    station_name = db.Column(db.String(150), nullable=False)
    province = db.Column(db.String(100), nullable=False, index=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    observed_at = db.Column(db.DateTime, nullable=False, index=True)
    air_temperature = db.Column(db.Float)
    dew_point = db.Column(db.Float)
    relative_humidity = db.Column(db.Float)
    wind_direction = db.Column(db.Float)
    wind_speed = db.Column(db.Float)
    rainfall = db.Column(db.Float)
    rainfall_24h = db.Column(db.Float)
    pressure = db.Column(db.Float)
    visibility = db.Column(db.Float)
    status_level = db.Column(
        db.String(20),
        nullable=False,
        default="green",
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class ForecastData(db.Model):
    __tablename__ = "forecast_data"

    id = db.Column(db.Integer, primary_key=True)
    province = db.Column(db.String(100), nullable=False, index=True)
    district = db.Column(db.String(100), index=True)
    subdistrict = db.Column(db.String(100), index=True)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    forecast_at = db.Column(db.DateTime, nullable=False, index=True)
    temperature = db.Column(db.Float)
    relative_humidity = db.Column(db.Float)
    rainfall = db.Column(db.Float)
    wind_speed = db.Column(db.Float)
    wind_direction = db.Column(db.Float)
    pressure = db.Column(db.Float)
    condition = db.Column(db.String(100))
    status_level = db.Column(
        db.String(20),
        nullable=False,
        default="green",
        index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        db.UniqueConstraint(
            "province",
            "district",
            "subdistrict",
            "forecast_at",
            name="uq_forecast_location_time",
        ),
    )


class WeatherWarning(db.Model):
    __tablename__ = "weather_warning"

    id = db.Column(db.Integer, primary_key=True)
    source_key = db.Column(db.String(255), unique=True, nullable=False, index=True)
    issue_no = db.Column(db.String(100), index=True)
    title = db.Column(db.String(500), nullable=False)
    headline = db.Column(db.Text)
    detail = db.Column(db.Text)
    warnings = db.Column(db.Text)
    category = db.Column(db.String(100), default="ประกาศเตือนภัย")
    agency = db.Column(db.String(255), default="กรมอุตุนิยมวิทยา")
    contact = db.Column(db.Text)
    published_at = db.Column(db.DateTime, index=True)
    effect_start_at = db.Column(db.DateTime)
    effect_end_at = db.Column(db.DateTime)
    source_url = db.Column(db.String(1000))
    fetched_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
