"""Inspectra: recommends the next bus an inspector should board to maximise expected fare-violation fines."""
import logging
import threading

from flask import Flask

from app import config
from app.extensions import db

logger = logging.getLogger(__name__)


def create_app(overrides=None):
    """Application factory. `overrides` (a dict) takes precedence over `app.config.Config`; tests use it."""
    logging.basicConfig(level=config.LOG_LEVEL, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    app = Flask(__name__)
    app.config.from_object(config.Config)
    app.config.update(overrides or {})

    if app.config["SECRET_KEY"] == config.DEFAULT_SECRET:
        logger.warning("INSPECTRA_SECRET is not set: sessions are signed with the public default key. Set it in production.")

    if app.config["CORS_ORIGINS"]:
        from flask_cors import CORS
        CORS(app, supports_credentials=True, resources={r"/*": {"origins": app.config["CORS_ORIGINS"]}})

    db.init_app(app)
    _register_blueprints(app)

    if app.config["BOOTSTRAP_DB"]:
        from app.seeds import bootstrap_database
        with app.app_context():
            bootstrap_database(app.config)

    if app.config["WARM_UP"]:
        threading.Thread(target=_warm_up, name="warm-up", daemon=True).start()

    return app


def _warm_up():
    """Build the routing engine (loads GTFS) ahead of the first request."""
    from app.services.routing import get_engine
    get_engine()


def _register_blueprints(app):
    from app.api.analytics import analytics_api
    from app.api.assignments import assignments_api
    from app.api.auth import auth_api
    from app.api.inspectors import inspectors_api
    from app.api.profile import profile_api
    from app.api.runs import runs_api
    from app.api.staff import staff_api
    from app.api.trips import trips_api
    from app.views.pages import views_bp

    for blueprint in (views_bp, auth_api, profile_api, staff_api, analytics_api, assignments_api, inspectors_api, runs_api):
        app.register_blueprint(blueprint)
    app.register_blueprint(trips_api, url_prefix="/api")
