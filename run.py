import os
from flask import Flask, jsonify
from flask_cors import CORS

from app.extensions import db

from app.views.pages import views_bp
from app.api.profile import profile_api
from app.api.staff import staff_api
from app.api.analytics import analytics_api
from app.api.assign_runs import assignments_api
from app.api.trips import trips_api

from auth.authentication import auth_bp

# ---------------- Flask Setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')

CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})

app.secret_key = os.environ.get("INSPECTRA_SECRET", "inspectra_dev_secret_please_change")

app.config.update(
    SESSION_COOKIE_SAMESITE=os.environ.get("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_HTTPONLY=os.environ.get("SESSION_COOKIE_HTTPONLY", "True") == "True",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "True") == "True",
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "inspectra.db")

database_url = os.environ.get("DATABASE_URL")
if not database_url:
    pg_user = os.environ.get("POSTGRES_USER")
    pg_password = os.environ.get("POSTGRES_PASSWORD")
    pg_host = os.environ.get("DATABASE_HOST", "postgres")
    pg_port = os.environ.get("DATABASE_PORT", "5432")
    pg_name = os.environ.get("POSTGRES_DB")
    if pg_user and pg_password and pg_name:
        database_url = f"postgresql+psycopg2://{pg_user}:{pg_password}@{pg_host}:{pg_port}/{pg_name}"
    else:
        database_url = f"sqlite:///{DB_PATH}"

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.register_blueprint(auth_bp)
app.register_blueprint(views_bp)
app.register_blueprint(profile_api)
app.register_blueprint(staff_api)
app.register_blueprint(analytics_api)
app.register_blueprint(assignments_api)
app.register_blueprint(trips_api, url_prefix="/api")

db.init_app(app)

# ---------------- Health and Readiness ----------------
@app.route('/healthz', methods=['GET'])
def healthz():
    return jsonify(status='ok'), 200

@app.route('/readyz', methods=['GET'])
def readyz():
    return jsonify(status='ready'), 200

# ---------------- Run App ----------------
if __name__ == '__main__':
    app.run(debug=os.environ.get("FLASK_DEBUG", "False") == "True", host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
