import os
from flask import Flask
from flask_cors import CORS
from app.extensions import db

def create_app():
    app = Flask(__name__, static_folder="../static", template_folder="../templates")

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        pg_user = os.environ.get("POSTGRES_USER")
        pg_password = os.environ.get("POSTGRES_PASSWORD")
        pg_host = os.environ.get("DATABASE_HOST", "postgres")
        pg_port = os.environ.get("DATABASE_PORT", "5432")
        pg_name = os.environ.get("POSTGRES_DB")
        if pg_user and pg_password and pg_name:
            db_url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_name}"
        else:
            db_url = "sqlite:///inspectra.db"

    app.config.from_mapping(
        SECRET_KEY=os.environ.get("INSPECTRA_SECRET", "inspectra_dev_secret_please_change"),
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_SAMESITE=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
        SESSION_COOKIE_HTTPONLY=os.environ.get("SESSION_COOKIE_HTTPONLY", "True") == "True",
        SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "True") == "True",
    )

    CORS(app, supports_credentials=True)
    db.init_app(app)

    return app
