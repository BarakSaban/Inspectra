# app.py
import os
from datetime import datetime
from flask import Flask, render_template, jsonify, request, redirect
import pandas as pd

from my_models_final import Inspector, InspectorRun, DB as db
from Classes import Inspector as InspectorClass
from Actions import Actions

app = Flask(__name__, static_folder='static', template_folder='templates')
DB_PATH = os.path.join(os.path.abspath(os.path.dirname(__file__)), "inspectra.db")
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{DB_PATH}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

# ---------------- Load GTFS + routes ----------------
stops_df = pd.read_csv("./gtfs/gtfs_filtered/stops.txt")
stop_times_df = pd.read_csv("./gtfs/gtfs_filtered/stop_times.txt")
trips_df = pd.read_csv("./gtfs/gtfs_filtered/trips.txt")
routes_df = pd.read_csv("./static/routes_with_avgs.csv")

actions = Actions(stops_df, stop_times_df, trips_df, routes_df)

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

# ---------------- Routes ----------------
@app.route('/')
def root(): return redirect('/admin')

@app.route('/admin')
def admin_dashboard(): return render_template('Admin_main_dashboard.html')

@app.route('/analytics')
def analytics_page(): return render_template('Analytics.html')

@app.route('/inspect')
def inspect_page(): return render_template('inspector_view.html')

# ---------------- API ----------------
@app.route('/api/inspectors')
def api_inspectors():
    inspectors = Inspector.query.all()
    return jsonify([{
        "id": i.id,
        "inspector_id": i.inspector_id,
        "name": i.name,
        "latitude": i.latitude,
        "longitude": i.longitude,
        "available": i.available,
        "total_fines": i.total_fines,
        "completed_trips": i.completed_trips
    } for i in inspectors])

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
    if not run: return jsonify({"error": "run not found"}), 404
    run.actual_fines = actual_fines
    run.finished_at = datetime.utcnow()
    run.status = "completed"
    inspector = Inspector.query.filter_by(inspector_id=run.inspector_id).first()
    if inspector:
        inspector.total_fines += actual_fines
        inspector.completed_trips += 1
    db.session.commit()
    return jsonify({"message": "run completed", "run_id": run_id})

@app.route('/api/analytics')
def api_analytics():
    inspectors = Inspector.query.all()
    runs = InspectorRun.query.all()
    total_fines = sum(r.actual_fines or 0 for r in runs)
    active_inspectors = sum(1 for i in inspectors if i.available)
    now = datetime.utcnow()
    week_ago = now - pd.Timedelta(days=7)
    weekly_total = sum(r.actual_fines or 0 for r in runs if r.assigned_at and r.assigned_at >= week_ago)
    total_runs = len(runs)
    total_potential = sum(r.potential_fines or 0 for r in runs)
    avg_efficiency = round((total_fines / total_potential * 100), 2) if total_potential else 0

    hourly = {}
    for r in runs:
        if r.assigned_at:
            hr = r.assigned_at.hour
            hourly.setdefault(hr, 0)
            hourly[hr] += r.actual_fines or 0
    hourly_list = [{"hour": f"{h:02d}:00", "fines": v} for h,v in sorted(hourly.items())]

    inspectors_summary = [{
        "id": i.id,
        "inspector_id": i.inspector_id,
        "name": i.name,
        "latitude": i.latitude,
        "longitude": i.longitude,
        "available": i.available,
        "total_fines": i.total_fines,
        "completed_trips": i.completed_trips
    } for i in inspectors]

    return jsonify({
        "totalFines": total_fines,
        "activeInspectors": active_inspectors,
        "weeklyTotal": weekly_total,
        "avgEfficiency": avg_efficiency,
        "totalRuns": total_runs,
        "inspectors": inspectors_summary,
        "hourly": hourly_list
    })

# ---------------- Core assignment using Actions ----------------
def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8):
    results = []
    with app.app_context():
        inspectors_db = Inspector.query.all()
        inspector_objs = [InspectorClass(i.inspector_id, i.name, i.latitude, i.longitude, bool(i.available)) for i in inspectors_db]
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

# ---------------- DB init ----------------
with app.app_context():
    db.create_all()
    seed_inspectors()

if __name__ == '__main__':
    app.run(debug=True)
