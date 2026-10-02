import logging
import os
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler


logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()


def start_scheduler(app):
    """Start periodic forecast and public TMD warning refresh jobs."""
    if scheduler.running:
        return

    forecast_minutes = int(
        os.getenv(
            "WEATHER_UPDATE_MINUTES",
            "15",
        )
    )

    warning_minutes = int(
        os.getenv(
            "TMD_WARNING_UPDATE_MINUTES",
            "10",
        )
    )

    def refresh_forecasts():
        with app.app_context():
            try:
                from .weather_service import (
                    collect_forecast_for_tracked_areas,
                )

                saved = collect_forecast_for_tracked_areas()

                logger.info(
                    "Forecast refresh completed: %s records",
                    saved,
                )

            except Exception:
                from . import db

                db.session.rollback()

                logger.exception(
                    "Forecast refresh failed"
                )

    def refresh_warnings():
        with app.app_context():
            try:
                from .warning_service import sync_weather_warnings

                saved = sync_weather_warnings()

                logger.info(
                    "Warning refresh completed: %s records",
                    saved,
                )

            except Exception:
                from . import db

                db.session.rollback()

                logger.exception(
                    "Warning refresh failed"
                )

    scheduler.add_job(
        refresh_forecasts,
        trigger="interval",
        minutes=forecast_minutes,
        id="forecast_refresh",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(),
    )

    scheduler.add_job(
        refresh_warnings,
        trigger="interval",
        minutes=warning_minutes,
        id="warning_refresh",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(),
    )

    scheduler.start()

    logger.info(
        "Forecast scheduler started: every %s minutes",
        forecast_minutes,
    )

    logger.info(
        "Warning scheduler started: every %s minutes",
        warning_minutes,
    )
