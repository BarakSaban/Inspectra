import os
from datetime import datetime, date
from flask import Flask, render_template, jsonify, request, redirect
import pandas as pd
from sqlalchemy import func

from Classes import Inspector as InspectorClass
from Actions import Actions
from my_models_final import Inspector, InspectorRun, DB as db

# ---------------- Setup ----------------
app = Flask(__name__, static_folder='static', template_folder='templates')
DB_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), "inspectra.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ---------------- Load GTFS + routes ----------------
stops_df = pd.read_csv("./gtfs/gtfs_filtered/stops.txt")
stop_times_df = pd.read_csv("./gtfs/gtfs_filtered/stop_times.txt")
trips_df = pd.read_csv("./gtfs/gtfs_filtered/trips.txt")
routes_df = pd.read_csv("./static/routes_with_avgs.csv")  # has AvgDontPay

actions = Actions(stops_df, stop_times_df, trips_df, routes_df)

# ---------------- Models extension ----------------
class Fine(db.Model):
    __tablename__ = "fines"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String, db.ForeignKey("inspectors.inspector_id"))
    trip_id = db.Column(db.String, nullable=True)
    stop_id = db.Column(db.String, nullable=True)
    amount = db.Column(db.Float, default=0)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- Seed default inspectors ----------------
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
            for ins in DEFAULT_INSPECTORS:
                db.session.add(Inspector(
                    inspector_id=ins["inspector_id"],
                    name=ins["name"],
                    latitude=ins["latitude"],
                    longitude=ins["longitude"],
                    available=True
                ))
            db.session.commit()

# ---------------- Pages ----------------
@app.route('/')
def root():
    return redirect('/admin')

@app.route('/admin')
def admin_dashboard():
    return render_template('Admin_main_dashboard.html')

@app.route('/analytics')
def analytics_page():
    return render_template('Analytics.html')

@app.route('/staff')
def staff_page():
    return render_template('staff_managment.html')

@app.route('/inspect')
def inspect_page():
    return render_template('inspector_view.html')

# ---------------- Staff Management APIs ----------------
@app.route('/api/staff')
def api_staff():
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
    inspector = Inspector.query.filter_by(inspector_id=inspector_id).first()
    if not inspector: return jsonify({"error":"Inspector not found"}),404

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

@app.route('/api/inspector/<inspector_id>', methods=['PUT'])
def update_inspector(inspector_id):
    data = request.get_json()
    inspector = Inspector.query.filter_by(inspector_id=inspector_id).first()
    if not inspector: return jsonify({"error":"Inspector not found"}),404
    inspector.name = data.get("name", inspector.name)
    inspector.email = data.get("email", getattr(inspector,'email',None))
    inspector.latitude = data.get("latitude", inspector.latitude)
    inspector.longitude = data.get("longitude", inspector.longitude)
    inspector.available = data.get("available", inspector.available)
    db.session.commit()
    return jsonify({"message":"Inspector updated"})

@app.route('/api/inspector', methods=['POST'])
def create_inspector():
    data = request.get_json()
    if Inspector.query.filter_by(inspector_id=data['inspector_id']).first():
        return jsonify({"error":"Inspector already exists"}),400
    new_ins = Inspector(
        inspector_id=data['inspector_id'],
        name=data['name'],
        email=data.get("email"),
        latitude=data.get("latitude"),
        longitude=data.get("longitude"),
        available=data.get("available",True)
    )
    db.session.add(new_ins)
    db.session.commit()
    return jsonify({"message":"Inspector created","inspector_id":new_ins.inspector_id})

# ---------------- Fines APIs ----------------
@app.route('/api/add_fine', methods=['POST'])
def add_fine():
    data = request.get_json()
    fine = Fine(
        inspector_id=data.get("inspector_id"),
        trip_id=data.get("trip_id"),
        stop_id=data.get("stop_id"),
        amount=data.get("amount", 100)
    )
    db.session.add(fine)
    db.session.commit()
    return jsonify({"message": "fine recorded", "fine_id": fine.id})

@app.route('/api/fines/hourly')
def fines_per_hour():
    results = (
        db.session.query(
            func.strftime('%H', Fine.timestamp).label("hour"),
            func.count(Fine.id)
        )
        .group_by("hour")
        .order_by("hour")
        .all()
    )
    data = [{"hour": f"{h}:00", "fines": c} for h, c in results]
    return jsonify(data)

@app.route('/api/fines/daily')
def fines_per_day():
    results = (
        db.session.query(
            func.date(Fine.timestamp).label("day"),
            func.count(Fine.id)
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    data = [{"day": str(d), "fines": c} for d, c in results]
    return jsonify(data)

# ---------------- Assign Runs APIs ----------------
@app.route('/api/assign_runs', methods=['POST'])
def api_assign_runs():
    results = assign_and_persist_runs()
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})

@app.route('/api/complete_run', methods=['POST'])
def api_complete_run():
    data = request.get_json()
    run_id = data.get("run_id")
    actual_fines = int(data.get("actual_fines", 0))
    run = InspectorRun.query.get(run_id)
    if not run:
        return jsonify({"error": "run not found"}), 404

    run.actual_fines = actual_fines
    run.finished_at = datetime.utcnow()
    run.status = "completed"

    inspector = Inspector.query.filter_by(inspector_id=run.inspector_id).first()
    if inspector:
        inspector.total_fines += actual_fines
        inspector.completed_trips += 1
    db.session.commit()

    for _ in range(actual_fines):
        fine = Fine(
            inspector_id=run.inspector_id,
            trip_id=run.trip_id,
            stop_id=run.stop_id,
            amount=100
        )
        db.session.add(fine)
    db.session.commit()

    return jsonify({"message": "run completed", "run_id": run_id})

# ---------------- Analytics ----------------
@app.route('/api/analytics')
def api_analytics():
    total_fines = db.session.query(func.count(Fine.id)).scalar() or 0
    active_inspectors = Inspector.query.filter_by(available=True).count()
    week_ago = datetime.utcnow() - pd.Timedelta(days=7)
    weekly_total = db.session.query(func.count(Fine.id)).filter(Fine.timestamp >= week_ago).scalar() or 0
    total_runs = InspectorRun.query.count()
    total_potential = sum(r.potential_fines or 0 for r in InspectorRun.query.all())
    avg_efficiency = round((total_fines / total_potential * 100), 2) if total_potential else 0

    hourly = db.session.query(func.strftime('%H', Fine.timestamp).label("hour"), func.count(Fine.id)).group_by("hour").order_by("hour").all()
    hourly_list = [{"hour": f"{h}:00", "fines": c} for h, c in hourly]

    daily = db.session.query(func.date(Fine.timestamp).label("day"), func.count(Fine.id)).group_by("day").order_by("day").all()
    daily_list = [{"day": str(d), "fines": c} for d, c in daily]

    return jsonify({
        "totalFines": total_fines,
        "activeInspectors": active_inspectors,
        "weeklyTotal": weekly_total,
        "avgEfficiency": avg_efficiency,
        "totalRuns": total_runs,
        "hourly": hourly_list,
        "daily": daily_list
    })

# ---------------- Core assignment using Actions ----------------
def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8):
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

# ---------------- DB Init ----------------
with app.app_context():
    db.create_all()
    seed_inspectors()

# ---------------- Run ----------------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
