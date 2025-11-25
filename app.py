import os
from datetime import datetime, date
from flask import Flask, render_template, jsonify, request, redirect, session, url_for, make_response
import pandas as pd
import numpy as np
from sqlalchemy import func
import random
from werkzeug.security import generate_password_hash, check_password_hash
from flask_cors import CORS
import string

# Inspectra core modules
from Classes import Inspector as InspectorClass
from Actions import Actions
from my_models_final import Inspector, InspectorRun, DB as db

# ---------------- Flask Setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')

CORS(app, supports_credentials=True, resources={r"/*": {"origins": "*"}})

app.secret_key = os.environ.get("INSPECTRA_SECRET", "inspectra_dev_secret_please_change")

app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,   # <---- NEW: strict cookie handling
)

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
    print("✓ GTFS and Actions loaded")
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
    username = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    inspector_id = db.Column(db.String(100), nullable=True)
    manager_code = db.Column(db.String(20), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        try:
            return check_password_hash(self.password_hash, raw)
        except Exception:
            return False

# ---------------- Fine model ----------------
class Fine(db.Model):
    __tablename__ = "fines"
    __table_args__ = {'extend_existing': True}
    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String, db.ForeignKey("inspectors.inspector_id"))
    trip_id = db.Column(db.String, nullable=True)
    stop_id = db.Column(db.String, nullable=True)
    amount = db.Column(db.Float, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- Default Inspectors ----------------
DEFAULT_INSPECTORS = [
    {"inspector_id": "I001", "name": "Lior Cohen", "latitude": 32.0853, "longitude": 34.7818},
    {"inspector_id": "I002", "name": "Dana Levi", "latitude": 32.1093, "longitude": 34.8555},
    {"inspector_id": "I003", "name": "Amir Ben David", "latitude": 32.0500, "longitude": 34.7667},
    {"inspector_id": "I004", "name": "Noa Shahar", "latitude": 31.9725, "longitude": 34.7890},
    {"inspector_id": "I005", "name": "Yossi Alon", "latitude": 32.2000, "longitude": 34.8833}
]

# ---------------- Seed functions ----------------
def seed_inspectors():
    with app.app_context():
        try:
            count = Inspector.query.count() if Inspector.query.count() else 0
            if count == 0:
                print("🌱 Seeding default inspectors...")
                for ins in DEFAULT_INSPECTORS:
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
                print("✓ Inspectors seeded.")
        except Exception as e:
            print("⚠️ seed_inspectors failed:", e)
            db.session.rollback()

def seed_fake_data():
    with app.app_context():
        try:
            runs_count = InspectorRun.query.count() if InspectorRun.query.count() else 0
            fines_count = Fine.query.count() if Fine.query.count() else 0
            if runs_count > 0 or fines_count > 0:
                print("✓ Fake data already exists — skipping.")
                return
            inspectors = Inspector.query.all() or seed_inspectors()
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
            print("✓ Fake data seeded.")
        except Exception as e:
            print("⚠️ seed_fake_data failed:", e)
            db.session.rollback()

# ---------------- Helpers ----------------
def logged_in():
    return session.get("user") is not None

def current_role():
    return session.get("role")

def current_inspector_id():
    return session.get("inspector_id")

def _get_request_data():
    data = request.get_json(silent=True)
    if data:
        return data
    if request.form:
        return request.form.to_dict()
    if request.args:
        return request.args.to_dict()
    return {}

def _is_api_request():
    accept = request.headers.get("Accept", "")
    ctype = request.headers.get("Content-Type", "")
    return "application/json" in accept or request.path.startswith("/api/") or "application/json" in ctype

def generate_manager_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ---------------- Auth routes ----------------
@app.route('/login', methods=['GET'])
def login_get():
    return render_template('login.html', show_sidebar=False, show_signout=False, error=None)

@app.route('/signup', methods=['GET'])
def signup_get():
    return render_template('signup.html', show_sidebar=False, show_signout=False, error=None)

# JSON API login
@app.route('/api/login', methods=['POST'])
def api_login():
    data = _get_request_data() or {}
    contact = (data.get('contact') or data.get('username') or "").strip()
    password = data.get('password')

    if not contact or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    try:
        user = User.query.filter_by(username=contact).first()
        if not user:
            user = User.query.filter_by(inspector_id=contact).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"success": False, "message": "Invalid password"}), 401

        session.clear()
        session['user'] = user.username
        session['role'] = user.role
        session['inspector_id'] = user.inspector_id
        session['admin_code'] = user.manager_code
        session.permanent = False

        redirect_target = '/admin' if user.role == 'admin' else '/inspect'
        return jsonify({"success": True, "redirect": redirect_target})
    except Exception as e:
        print("⚠️ api_login error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/api/register', methods=['POST'])
def api_register():
    return _register_common()

@app.route('/register', methods=['POST'])
def register_form():
    return _register_common(allow_redirect=True)

def _register_common(allow_redirect=False):
    data = _get_request_data() or {}
    name = (data.get('name') or data.get('full_name') or "").strip()
    email = (data.get('email') or "").strip()
    phone = (data.get('phone') or data.get('phone_number') or "").strip()
    role = (data.get('role') or 'inspector').lower()
    password = data.get('password')
    manager_code_input = data.get("manager_code") or data.get("manager_code_input")

    if not password or not (email or phone or name):
        if allow_redirect and not _is_api_request():
            return redirect(url_for('signup_get'))
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    username_candidate = (email or phone or name).strip()
    unique_username = username_candidate
    suffix_try = 0

    try:
        while User.query.filter_by(username=unique_username).first() is not None:
            suffix_try += 1
            unique_username = f"{username_candidate}_{suffix_try}"
            if suffix_try > 200:
                if allow_redirect and not _is_api_request():
                    return redirect(url_for('signup_get'))
                return jsonify({"success": False, "message": "Unable to generate username"}), 500

        linked_inspector_id = None

        if role == 'inspector':
            if manager_code_input:
                parent_admin = User.query.filter_by(manager_code=manager_code_input, role='admin').first()
                if not parent_admin:
                    if allow_redirect and not _is_api_request():
                        return redirect(url_for('signup_get'))
                    return jsonify({"success": False, "message": "Invalid manager code"}), 400

            if phone and phone.upper().startswith('I'):
                candidate = phone.upper()
                if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                    linked_inspector_id = candidate

            if not linked_inspector_id:
                for _ in range(500):
                    candidate = f"I{random.randint(1000,9999)}"
                    if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                        linked_inspector_id = candidate
                        break

            try:
                if linked_inspector_id and not Inspector.query.filter_by(inspector_id=linked_inspector_id).first():
                    new_ins = Inspector(
                        inspector_id=linked_inspector_id,
                        name=name or unique_username,
                        latitude=32.0853,
                        longitude=34.7818,
                        available=True
                    )
                    if hasattr(Inspector, 'total_fines'):
                        setattr(new_ins, 'total_fines', 0)
                    if hasattr(Inspector, 'completed_trips'):
                        setattr(new_ins, 'completed_trips', 0)
                    db.session.add(new_ins)
                    db.session.commit()
            except Exception as ei:
                print("⚠️ inspector create failed:", ei)
                db.session.rollback()

            new_user = User(
                username=unique_username,
                role=role,
                inspector_id=linked_inspector_id,
                manager_code=manager_code_input,
                full_name=name or unique_username
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

        else:
            for _ in range(500):
                generated_code = generate_manager_code()
                if User.query.filter_by(manager_code=generated_code).first() is None:
                    break

            new_user = User(
                username=unique_username,
                role=role,
                manager_code=generated_code,
                full_name=name or unique_username
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            session['admin_code'] = generated_code

        session.clear()
        session['user'] = new_user.username
        session['role'] = new_user.role
        session['inspector_id'] = new_user.inspector_id
        session['admin_code'] = new_user.manager_code
        session.permanent = False

        redirect_target = '/admin' if new_user.role == 'admin' else '/inspect'

        if allow_redirect and not _is_api_request():
            return redirect(redirect_target)

        return jsonify({"success": True, "redirect": redirect_target})

    except Exception as e:
        print("⚠️ api_register error:", e)
        db.session.rollback()
        if allow_redirect and not _is_api_request():
            return redirect(url_for('signup_get'))
        return jsonify({"success": False, "message": "Server error"}), 500

@app.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "redirect": "/login"})

@app.route('/logout')
def logout_page():
    session.clear()
    return redirect(url_for('login_get'))

# ---------------- Role-based pages ----------------

@app.route('/')
def root():
    # <---- NEW LOGIC
    if logged_in():
        return redirect('/admin' if current_role() == 'admin' else '/inspect')
    return redirect(url_for('login_get'))

@app.route('/admin')
def admin_dashboard():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))
    username = session.get('user')
    user = User.query.filter_by(username=username).first()

    return render_template(
        'Admin_main_dashboard.html',
        show_sidebar=True,
        show_signout=True,
        user=user,
        admin_code=session.get('admin_code')
    )

@app.route('/analytics')
def analytics_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))
    username = session.get('user')
    user = User.query.filter_by(username=username).first()

    return render_template('Analytics.html',
                            show_sidebar=True,
                            show_signout=True,
                            user=user,
                            admin_code=session.get('admin_code'))

@app.route("/sidebar")
def sidebar():
    if "user" not in session:
        return "", 401
    return render_template("sidebar.html", user=session["user"])

@app.route('/staff')
def staff_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('login_get'))

    username = session.get('user')
    user = User.query.filter_by(username=username).first()

    return render_template('staff_managment.html',
                            show_sidebar=True,
                            show_signout=True,
                            user=user,
                            admin_code=session.get('admin_code'))


# ---------------- Profile page ----------------
@app.route('/profile')
def profile_page():
    if not logged_in():
        return redirect(url_for('login_get'))

    # get real db user object
    username = session.get('user')
    user = User.query.filter_by(username=username).first()

    # if inspector, also fetch inspector table details
    inspector = None
    if user and user.role == "inspector" and user.inspector_id:
        inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()

    return render_template(
        'profile.html',
        show_sidebar=True,
        show_signout=True,
        user=user,                     # <-- REAL USER OBJECT
        inspector=inspector,           # <-- extra inspector data
        role=user.role if user else None,
        inspector_id=user.inspector_id if user else None,
        admin_code=user.manager_code if user else None
    )


@app.route('/inspect')
def inspect_page():
    if not logged_in() or current_role() != 'inspector':
        return redirect(url_for('login_get'))

    username = session.get('user')
    user = User.query.filter_by(username=username).first()

    return render_template(
        'inspector_view.html',
        show_sidebar=False,
        show_signout=True,
        user=user,
        inspector_id=session.get('inspector_id')
    )


# ---------------- Profile API ----------------
@app.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    if not logged_in():
        return jsonify({"error": "unauthorized"}), 401

    username = session.get('user')
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "user not found"}), 404

    if request.method == 'GET':
        # Return user details including full_name
        return jsonify({
            "username": user.username,
            "role": user.role,
            "inspector_id": user.inspector_id,
            "manager_code": user.manager_code,
            "full_name": user.full_name
        })

    elif request.method == 'POST':
        data = _get_request_data()
        if not data:
            return jsonify({"error": "no data provided"}), 400

        # Allow changing username and password and full_name
        new_username = data.get('username', user.username).strip()
        new_password = data.get('password')
        new_full_name = data.get('full_name')

        # Check uniqueness for username
        if new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({"error": "username already taken"}), 400
            user.username = new_username
            session['user'] = new_username  # update session

        if new_password:
            user.set_password(new_password)

        if new_full_name is not None:
            user.full_name = new_full_name.strip()

        # Optionally allow updating inspector name (if inspector)
        if user.role == "inspector" and user.inspector_id:
            inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()
            if inspector and new_full_name:
                inspector.name = new_full_name.strip()
                db.session.add(inspector)

        try:
            db.session.add(user)
            db.session.commit()
            return jsonify({"success": True, "message": "Profile updated successfully"})
        except Exception as e:
            db.session.rollback()
            print("⚠️ api_profile POST error:", e)
            return jsonify({"error": "server error"}), 500


# ---------------- Staff Management API ----------------
@app.route('/api/staff')
def api_staff():
    """
    Returns the list of inspectors that belong to the currently-logged-in admin
    (filtered by manager_code stored in session). If session has no admin_code,
    returns empty list.
    """
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify([])

        # find Users that are inspectors under this admin
        inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()

        today = date.today()
        seven_days_ago = datetime.utcnow() - pd.Timedelta(days=7)

        staff_list = []
        for u in inspector_users:
            # try to find Inspector record for coordinates/status
            insp = Inspector.query.filter_by(inspector_id=u.inspector_id).first()
            weekly_fines = db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==u.inspector_id, Fine.timestamp>=seven_days_ago).scalar() or 0
            today_trips = db.session.query(func.count(InspectorRun.id)).filter(InspectorRun.inspector_id==u.inspector_id, func.date(InspectorRun.assigned_at)==today).scalar() or 0
            current_run = InspectorRun.query.filter_by(inspector_id=u.inspector_id).filter(InspectorRun.status.in_( ["assigned","accepted"]) ).order_by(InspectorRun.assigned_at.desc()).first()
            current_assignment = {
                "trip_id": current_run.trip_id,
                "status": current_run.status,
                "potential_fines": current_run.potential_fines
            } if current_run else None

            staff_list.append({
                "inspector_id": u.inspector_id,
                "username": u.username,
                "name": getattr(insp, 'name', u.full_name or u.username),
                "email": getattr(u, 'email', None),
                "latitude": getattr(insp, 'latitude', None),
                "longitude": getattr(insp, 'longitude', None),
                "available": getattr(insp, 'available', True),
                "today_trips": today_trips,
                "weekly_fines": weekly_fines,
                "current_assignment": current_assignment,
                # optional: totals from Inspector table if present
                "total_fines": getattr(insp, 'total_fines', 0),
                "completed_trips": getattr(insp, 'completed_trips', 0)
            })

        return jsonify(staff_list)
    except Exception as e:
        print("⚠️ api_staff error:", e)
        return jsonify({"error": "server error"}), 500


# ---------------- Analytics API (admin-scoped) ----------------
@app.route('/api/analytics')
def api_analytics():
    """
    Returns summary analytics for the current admin's inspectors only.
    """
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400

        # inspector users belonging to admin
        inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()
        inspector_ids = [u.inspector_id for u in inspector_users if u.inspector_id]

        # basic totals
        totalFines = 0
        weeklyTotal = 0
        today = date.today()
        seven_days_ago = datetime.utcnow() - pd.Timedelta(days=7)

        for iid in inspector_ids:
            # count fines for today and week
            totalFines += db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==iid, func.date(Fine.timestamp)==today).scalar() or 0
            weeklyTotal += db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==iid, Fine.timestamp>=seven_days_ago).scalar() or 0

        # active inspectors: those available == True (from Inspector table)
        activeInspectors = Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids), Inspector.available==True).count() if inspector_ids else 0

        # avgEfficiency: simple metric: completed_trips / (completed_trips + potential) across inspector_ids if fields exist
        total_completed = 0
        total_potential = 0
        for iid in inspector_ids:
            total_completed += db.session.query(func.coalesce(func.sum(InspectorRun.actual_fines), 0)).filter(InspectorRun.inspector_id==iid).scalar() or 0
            total_potential += db.session.query(func.coalesce(func.sum(InspectorRun.potential_fines), 0)).filter(InspectorRun.inspector_id==iid).scalar() or 0

        avgEfficiency = int((total_completed / total_potential * 100) if (total_potential > 0) else 0)

        # prepare inspectors summary for frontend (small)
        inspectors_summary = []
        for u in inspector_users:
            insp = Inspector.query.filter_by(inspector_id=u.inspector_id).first()
            inspectors_summary.append({
                "inspector_id": u.inspector_id,
                "name": getattr(insp, 'name', u.full_name or u.username),
                "latitude": getattr(insp, 'latitude', None),
                "longitude": getattr(insp, 'longitude', None),
                "available": getattr(insp, 'available', True),
                "total_fines": getattr(insp, 'total_fines', 0),
                "completed_trips": getattr(insp, 'completed_trips', 0)
            })

        return jsonify({
            "totalFines": totalFines,
            "weeklyTotal": weeklyTotal,
            "activeInspectors": activeInspectors,
            "avgEfficiency": avgEfficiency,
            "inspectors": inspectors_summary
        })
    except Exception as e:
        print("⚠️ api_analytics error:", e)
        return jsonify({"error": "server error"}), 500


# Assign runs (admin-scoped)
def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8, admin_code=None):
    """
    Assign runs only to inspectors that belong to admin_code (if provided).
    If admin_code is None, will assign globally (but this function is only used by admin endpoints).
    """
    if actions is None:
        print("⚠️ Actions module not initialized — cannot assign runs.")
        return []

    results = []
    with app.app_context():
        try:
            if admin_code:
                # get inspector objects that belong to this admin
                inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()
                inspector_ids = [u.inspector_id for u in inspector_users if u.inspector_id]
                inspectors_db = Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids)).all()
            else:
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
        except Exception as e:
            print("⚠️ assign_and_persist_runs error:", e)
            db.session.rollback()
    return results


@app.route('/api/assign_runs', methods=['POST'])
def api_assign_runs():
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    admin_code = session.get('admin_code')
    results = assign_and_persist_runs(admin_code=admin_code)
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})


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
