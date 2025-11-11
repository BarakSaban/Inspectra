import os
from datetime import datetime, date
from flask import Flask, render_template, jsonify, request, redirect, session, url_for
import pandas as pd
import numpy as np
from sqlalchemy import func
import random
from werkzeug.security import generate_password_hash, check_password_hash

# Inspectra core modules
from Classes import Inspector as InspectorClass
from Actions import Actions
from my_models_final import Inspector, InspectorRun, DB as db

# ---------------- Flask Setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')

# secret for sessions — replace with env var in production
app.secret_key = os.environ.get("INSPECTRA_SECRET", "inspectra_dev_secret_please_change")

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "inspectra.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ---------------- Load GTFS + Actions ----------------
GTFS_PATH = os.path.join(BASE_DIR, "gtfs", "gtfs_filtered")
try:
    stops_df = pd.read_csv(os.path.join(GTFS_PATH, "stops.txt"))
    stop_times_df = pd.read_csv(os.path.join(GTFS_PATH, "stop_times.txt"))
    trips_df = pd.read_csv(os.path.join(GTFS_PATH, "trips.txt"))
    routes_df = pd.read_csv(os.path.join(BASE_DIR, "static", "routes_with_avgs.csv"))
    actions = Actions(stops_df, stop_times_df, trips_df, routes_df)
except Exception as e:
    print("⚠️ GTFS or routes load failed:", e)
    stops_df = pd.DataFrame()
    stop_times_df = pd.DataFrame()
    trips_df = pd.DataFrame()
    routes_df = pd.DataFrame()
    actions = None

# ---------------- Extra models for auth (new table) ----------------
class User(db.Model):
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String, unique=True, nullable=False)   # login name (email or phone or custom)
    password_hash = db.Column(db.String, nullable=False)
    role = db.Column(db.String, nullable=False)  # 'admin' or 'inspector'
    inspector_id = db.Column(db.String, nullable=True)  # optional link to Inspector.inspector_id

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

# ---------------- Fine model (existing style) ----------------
class Fine(db.Model):
    __tablename__ = "fines"
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String, db.ForeignKey("inspectors.inspector_id"))
    trip_id = db.Column(db.String, nullable=True)
    stop_id = db.Column(db.String, nullable=True)
    amount = db.Column(db.Float, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- Default Inspectors (seed) ----------------
DEFAULT_INSPECTORS = [
    {"inspector_id": "I001", "name": "Lior Cohen", "latitude": 32.0853, "longitude": 34.7818},
    {"inspector_id": "I002", "name": "Dana Levi", "latitude": 32.1093, "longitude": 34.8555},
    {"inspector_id": "I003", "name": "Amir Ben David", "latitude": 32.0500, "longitude": 34.7667},
    {"inspector_id": "I004", "name": "Noa Shahar", "latitude": 31.9725, "longitude": 34.7890},
    {"inspector_id": "I005", "name": "Yossi Alon", "latitude": 32.2000, "longitude": 34.8833}
]

def seed_inspectors():
    with app.app_context():
        if Inspector.query.count() == 0:
            print("🌱 Seeding default inspectors...")
            for ins in DEFAULT_INSPECTORS:
                # Some Inspector models may not have total_fines/completed_trips; guard with hasattr
                kwargs = dict(
                    inspector_id=ins["inspector_id"],
                    name=ins["name"],
                    latitude=ins["latitude"],
                    longitude=ins["longitude"],
                    available=True
                )
                if hasattr(Inspector, 'total_fines'):
                    kwargs['total_fines'] = 0
                if hasattr(Inspector, 'completed_trips'):
                    kwargs['completed_trips'] = 0
                db.session.add(Inspector(**kwargs))
            db.session.commit()
            print("✅ Inspectors seeded.")

def seed_fake_data():
    with app.app_context():
        if InspectorRun.query.count() > 0 or Fine.query.count() > 0:
            print("✅ Fake data already exists — skipping seeding.")
            return

        inspectors = Inspector.query.all()
        if not inspectors:
            seed_inspectors()
            inspectors = Inspector.query.all()

        print("🌱 Seeding fake runs and fines...")
        for ins in inspectors:
            for _ in range(random.randint(5, 10)):
                days_ago = random.randint(0, 6)
                assigned_at = datetime.utcnow() - pd.Timedelta(days=days_ago, hours=random.randint(0, 23))
                trip_id = f"T{random.randint(1000,9999)}"
                stop_id = f"S{random.randint(100,999)}"
                potential_fines = random.randint(10, 30)
                actual_fines = random.randint(0, potential_fines)

                run = InspectorRun(
                    inspector_id=ins.inspector_id,
                    trip_id=trip_id,
                    stop_id=stop_id,
                    potential_fines=potential_fines,
                    actual_fines=actual_fines,
                    assigned_at=assigned_at,
                    finished_at=assigned_at + pd.Timedelta(hours=1),
                    status="completed"
                )
                db.session.add(run)
                for _ in range(actual_fines):
                    fine = Fine(
                        inspector_id=ins.inspector_id,
                        trip_id=trip_id,
                        stop_id=stop_id,
                        amount=100,
                        timestamp=assigned_at + pd.Timedelta(minutes=random.randint(5, 55))
                    )
                    db.session.add(fine)
        db.session.commit()
        print("✅ Fake data seeded successfully.")

# ---------------- Helpers ----------------
def logged_in():
    return session.get("user") is not None

def current_role():
    return session.get("role")

def current_inspector_id():
    return session.get("inspector_id")

# ---------------- Auth routes (login/signup/logout) ----------------
# Keep HTML GET endpoints (they render templates without sidebar)
@app.route('/login', methods=['GET'])
def login_get():
    if logged_in():
        if current_role() == 'admin':
            return redirect(url_for('admin_dashboard'))
        if current_role() == 'inspector':
            return redirect(url_for('inspect_page'))
    return render_template('login.html', show_sidebar=False, show_signout=False, error=None)

@app.route('/signup', methods=['GET'])
def signup_get():
    return render_template('signup.html', show_sidebar=False, show_signout=False, error=None)

# JSON API login (used by your frontend)
@app.route('/api/login', methods=['POST'])
def api_login():
    data = request.get_json() or {}
    contact = (data.get('contact') or "").strip()
    password = data.get('password')
    role_hint = (data.get('role') or "").lower()

    if not contact or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    # find user by username (frontend uses contact as username)
    user = User.query.filter_by(username=contact).first()
    if not user:
        # if role_hint == 'inspector' maybe contact is inspector_id, try to find user by inspector_id
        user = User.query.filter_by(inspector_id=contact).first()

    if not user:
        return jsonify({"success": False, "message": "User not found"}), 404

    if not user.check_password(password):
        return jsonify({"success": False, "message": "Invalid password"}), 401

    # login success — set session
    session.clear()
    session['user'] = user.username
    session['role'] = user.role
    session['inspector_id'] = user.inspector_id

    # choose redirect target
    redirect_target = '/admin' if user.role == 'admin' else '/inspect'
    return jsonify({"success": True, "redirect": redirect_target})

# JSON API register (used by your frontend)
@app.route('/api/register', methods=['POST'])
def api_register():
    data = request.get_json() or {}
    # frontend sends: name, email, phone, role, manager_code, team_name, password
    name = (data.get('name') or "").strip()
    email = (data.get('email') or "").strip()
    phone = (data.get('phone') or "").strip()
    role = (data.get('role') or 'inspector').lower()
    password = data.get('password')

    if not password or not (email or phone or name):
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    # choose username preference: email if provided, else phone, else name
    username_candidate = email or phone or name
    username_candidate = username_candidate.strip()

    # ensure unique username — if taken, append random suffix
    unique_username = username_candidate
    suffix_try = 0
    while User.query.filter_by(username=unique_username).first() is not None:
        suffix_try += 1
        unique_username = f"{username_candidate}_{suffix_try}"
        if suffix_try > 50:
            # unlikely, but stop infinite loop
            return jsonify({"success": False, "message": "Unable to generate unique username"}), 500

    linked_inspector_id = None
    if role == 'inspector':
        # create inspector_id (unique)
        # try to use phone as inspector_id if starts with 'I' or if phone provided; else generate
        if phone and phone.startswith('I'):
            candidate = phone
            if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                linked_inspector_id = candidate
        if not linked_inspector_id:
            # generate unique inspector id
            for _ in range(100):
                candidate = f"I{random.randint(1000,9999)}"
                if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                    linked_inspector_id = candidate
                    break
        # create Inspector row if missing
        if not Inspector.query.filter_by(inspector_id=linked_inspector_id).first():
            new_ins = Inspector(
                inspector_id=linked_inspector_id,
                name=name or unique_username,
                latitude=32.0853,
                longitude=34.7818,
                available=True
            )
            # optional fields
            if hasattr(Inspector, 'total_fines'):
                setattr(new_ins, 'total_fines', 0)
            if hasattr(Inspector, 'completed_trips'):
                setattr(new_ins, 'completed_trips', 0)
            db.session.add(new_ins)
            db.session.commit()

    # create User
    new_user = User(username=unique_username, role=role, inspector_id=linked_inspector_id)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    # auto-login and return JSON redirect
    session.clear()
    session['user'] = new_user.username
    session['role'] = new_user.role
    session['inspector_id'] = new_user.inspector_id

    redirect_target = '/admin' if new_user.role == 'admin' else '/inspect'
    return jsonify({"success": True, "redirect": redirect_target})

# optional JSON logout
@app.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "redirect": "/login"})

# ---------------- Role-based pages ----------------
@app.route('/')
def root():
    if logged_in():
        if current_role() == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_role() == 'inspector':
            return redirect(url_for('inspect_page'))
    return redirect(url_for('login_get'))

@app.route('/admin')
def admin_dashboard():
    # only admin allowed
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))
    # Admin sees sidebar and signout
    return render_template('Admin_main_dashboard.html', show_sidebar=True, show_signout=True, user=session.get('user'))

@app.route('/analytics')
def analytics_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))
    return render_template('Analytics.html', show_sidebar=True, show_signout=True, user=session.get('user'))

@app.route('/staff')
def staff_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))
    return render_template('staff_managment.html', show_sidebar=True, show_signout=True, user=session.get('user'))

@app.route('/inspect')
def inspect_page():
    # only inspectors allowed
    if not logged_in() or current_role() != 'inspector':
        return redirect(url_for('login_get'))
    # Inspectors do NOT see sidebar
    return render_template('inspector_view.html',
                           show_sidebar=False,
                           show_signout=True,
                           user=session.get('user'),
                           inspector_id=session.get('inspector_id'))

# ---------------- Staff Management APIs (protected) ----------------
@app.route('/api/staff')
def api_staff():
    # Only admin can request staff list
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    inspectors_db = Inspector.query.all()
    today = date.today()
    seven_days_ago = datetime.utcnow() - pd.Timedelta(days=7)

    staff_list = []
    for i in inspectors_db:
        weekly_fines = db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==i.inspector_id, Fine.timestamp>=seven_days_ago).scalar() or 0
        today_trips = db.session.query(func.count(InspectorRun.id)).filter(InspectorRun.inspector_id==i.inspector_id, func.date(InspectorRun.assigned_at)==today).scalar() or 0
        current_run = InspectorRun.query.filter_by(inspector_id=i.inspector_id).filter(InspectorRun.status.in_(["assigned","accepted"])).order_by(InspectorRun.assigned_at.desc()).first()
        current_assignment = {
            "trip_id": current_run.trip_id,
            "status": current_run.status,
            "potential_fines": current_run.potential_fines
        } if current_run else None

        staff_list.append({
            "inspector_id": i.inspector_id,
            "name": i.name,
            "email": getattr(i,'email',None),
            "latitude": i.latitude,
            "longitude": i.longitude,
            "available": i.available,
            "today_trips": today_trips,
            "weekly_fines": weekly_fines,
            "current_assignment": current_assignment
        })

    return jsonify(staff_list)

@app.route('/api/inspector/<inspector_id>', methods=['GET'])
def get_inspector(inspector_id):
    # allow admin or the inspector themself
    if not logged_in():
        return jsonify({"error": "unauthorized"}), 401
    if current_role() != 'admin' and current_inspector_id() != inspector_id:
        return jsonify({"error": "unauthorized"}), 401

    inspector = Inspector.query.filter_by(inspector_id=inspector_id).first()
    if not inspector:
        return jsonify({"error":"Inspector not found"}),404

    today = date.today()
    seven_days_ago = datetime.utcnow() - pd.Timedelta(days=7)
    weekly_fines = db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==inspector_id, Fine.timestamp>=seven_days_ago).scalar() or 0
    today_trips = db.session.query(func.count(InspectorRun.id)).filter(InspectorRun.inspector_id==inspector_id, func.date(InspectorRun.assigned_at)==today).scalar() or 0
    current_run = InspectorRun.query.filter_by(inspector_id=inspector_id).filter(InspectorRun.status.in_(["assigned","accepted"])).order_by(InspectorRun.assigned_at.desc()).first()

    return jsonify({
        "inspector_id":inspector.inspector_id,
        "name":inspector.name,
        "email":getattr(inspector,'email',None),
        "latitude":inspector.latitude,
        "longitude":inspector.longitude,
        "available":inspector.available,
        "weekly_fines":weekly_fines,
        "today_trips":today_trips,
        "current_assignment":{"trip_id":current_run.trip_id,"status":current_run.status,"potential_fines":current_run.potential_fines} if current_run else None
    })

# (other APIs retained — assign_and_persist_runs, etc.)

def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8):
    if actions is None:
        print("⚠️ Actions module not initialized — cannot assign runs.")
        return []

    results = []
    with app.app_context():
        inspectors_db = Inspector.query.all()
        inspector_objs = [
            InspectorClass(i.inspector_id, i.name, i.latitude, i.longitude, bool(i.available))
            for i in inspectors_db
        ]
        df = actions.assign_best_trips_global(inspector_objs, buffer_minutes, radius_m, max_walk_minutes)
        if df is None or df.empty:
            return []
        for _, row in df.iterrows():
            run = InspectorRun(
                inspector_id=row['inspector_id'],
                trip_id=str(row['trip_id']),
                stop_id=str(row['stop_id']),
                potential_fines=int(row.get('potential_fines', 0)),
                assigned_at=datetime.utcnow(),
                status="assigned"
            )
            db.session.add(run)
            db.session.commit()
            results.append({
                "run_id": run.id,
                "inspector_id": run.inspector_id,
                "trip_id": run.trip_id,
                "stop_id": run.stop_id,
                "potential_fines": run.potential_fines
            })
    return results

@app.route('/api/assign_runs', methods=['POST'])
def api_assign_runs():
    # only admin should assign runs
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401
    results = assign_and_persist_runs()
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})

# ---------------- DB Init ----------------
with app.app_context():
    db.create_all()
    # create a default admin user if not present
    if not User.query.filter_by(username='admin').first():
        admin_user = User(username='admin', role='admin')
        admin_user.set_password(os.environ.get("INSPECTRA_ADMIN_PW", "admin"))  # default admin:admin (override in env)
        db.session.add(admin_user)
        db.session.commit()
        print("✅ Default admin user created (username=admin).")

    seed_inspectors()
    seed_fake_data()

# ---------------- Run App ----------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
