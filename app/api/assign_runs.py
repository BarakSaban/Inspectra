from flask import Blueprint, jsonify, session
from datetime import datetime
import os
import pandas as pd
from app.extensions import db
from app.models import User, InspectorRun
from Classes import Inspector
from utils.auth_helpers import logged_in, current_role

from Actions import Actions
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
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

#NOTE: This is to be removed in the future in favour of automatic assignment of inspectors based on the algorithm. TODO!

assignments_api = Blueprint("assignments_api", __name__)

def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8, admin_code=None):
    """
    Assign runs only to inspectors that belong to admin_code (if provided).
    If admin_code is None, will assign globally (but this function is only used by admin endpoints).
    """
    if actions is None:
        print("⚠️ Actions module not initialized — cannot assign runs.")
        return []

    results = []
    try:
        if admin_code:
            # get inspector objects that belong to this admin
            inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()
            inspector_ids = [u.inspector_id for u in inspector_users if u.inspector_id]
            inspectors_db = Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids)).all()
        else:
            inspectors_db = Inspector.query.all()

        inspector_objs = [
            Inspector(i.inspector_id, i.name, i.latitude, i.longitude, bool(i.available))
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
                assigned_at=datetime.now(),
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


@assignments_api.route('/api/assign_runs', methods=['POST'])
def api_assign_runs():
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    admin_code = session.get('admin_code')
    results = assign_and_persist_runs(admin_code=admin_code)
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})
