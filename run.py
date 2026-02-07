import os
from flask import Flask
from flask_cors import CORS

from app.extensions import db

from app.views.pages import views_bp
from app.api.profile import profile_api
from app.api.staff import staff_api
from app.api.analytics import analytics_api
from app.api.assign_runs import assignments_api
from app.api.trips import trips_api

from seeds import seed_fake_data, seed_inspectors
from utils.auth_helpers import generate_manager_code
from auth.authentication import auth_bp
from app.models import User

# ---------------- Flask Setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')

CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})

app.secret_key = os.environ.get("INSPECTRA_SECRET", "inspectra_dev_secret_please_change")

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
)

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "inspectra.db")

app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

app.register_blueprint(auth_bp)
app.register_blueprint(views_bp)
app.register_blueprint(profile_api)
app.register_blueprint(staff_api)
app.register_blueprint(analytics_api)
app.register_blueprint(assignments_api)
app.register_blueprint(trips_api, url_prefix="/api")

db.init_app(app)

# ---------------- DB Init ----------------
with app.app_context():
    try:
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin_user = User(username='admin', role='admin', manager_code=generate_manager_code(), full_name='Admin')
            admin_user.set_password(os.environ.get("INSPECTRA_ADMIN_PW", "admin"))
            db.session.add(admin_user)
            db.session.commit()
            print("✅ Default admin user created (username=admin).")
    except Exception as e:
        print("⚠️ DB init/create_all failed:", e)
        db.session.rollback()

    seed_inspectors()
    seed_fake_data()

# ---------------- Run App ----------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
