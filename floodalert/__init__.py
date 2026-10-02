import os

from dotenv import load_dotenv
from flask import Flask
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text


load_dotenv()


db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()


def create_app():
    base_dir = os.path.dirname(os.path.abspath(__file__))

    app = Flask(
        __name__,
        template_folder=os.path.join(base_dir, "templates"),
        static_folder=os.path.join(base_dir, "static"),
    )

    app.config["SECRET_KEY"] = os.getenv(
        "SECRET_KEY",
        "flood-alert-secret-key",
    )

    database_url = os.getenv("DATABASE_URL", "sqlite:///flood_alert.db").strip()

    # SQLAlchemy 2.x uses the psycopg (v3) driver explicitly.
    # Keep SQLite as the local-development fallback, while Render/Supabase
    # can provide a PostgreSQL URL through DATABASE_URL.
    if database_url.startswith("postgres://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgres://"): ]
    elif database_url.startswith("postgresql://"):
        database_url = "postgresql+psycopg://" + database_url[len("postgresql://"): ]

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
        "pool_pre_ping": True,
        "pool_recycle": 1800,
    }

    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "กรุณาเข้าสู่ระบบเพื่อเปิดพื้นที่ของฉัน"
    login_manager.login_message_category = "info"

    from .auth import auth
    from .main import main

    app.register_blueprint(auth)
    app.register_blueprint(main)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    with app.app_context():
        # Create tables on first boot. This works for both local SQLite and
        # persistent PostgreSQL databases. Existing PostgreSQL schemas are
        # left intact; the lightweight migration below handles the project
        # schema change already supported by the app.
        db.create_all()
        _migrate_tracked_area(app)

    # Vercel runs Flask as a request-driven function. Do not start a
    # long-lived APScheduler thread there; scheduled refreshes are handled
    # by the Vercel Cron endpoint in app/main.py. Keep APScheduler enabled
    # for the traditional local/Render server deployment.
    if (
        not os.environ.get("VERCEL")
        and (
            not app.debug
            or os.environ.get("WERKZEUG_RUN_MAIN") == "true"
        )
    ):
        from .scheduler import start_scheduler

        start_scheduler(app)

    return app


def _migrate_tracked_area(app):
    """Add the optional subdistrict column to an existing schema."""
    inspector = inspect(db.engine)

    if not inspector.has_table("tracked_area"):
        return

    columns = {
        column["name"]
        for column in inspector.get_columns("tracked_area")
    }

    if "subdistrict" in columns:
        return

    db.session.execute(
        text(
            "ALTER TABLE tracked_area "
            "ADD COLUMN subdistrict VARCHAR(100)"
        )
    )
    db.session.commit()
