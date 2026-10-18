from flask import Flask
from flask_cors import CORS
from app.extensions import db

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")

    app.config.from_mapping(
        SECRET_KEY="inspectra_dev_secret_please_change",
        SQLALCHEMY_DATABASE_URI="sqlite:///inspectra.db",
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=True,
    )

    CORS(app, supports_credentials=True)
    db.init_app(app)

    return app
