from flask import Blueprint, jsonify, session
from datetime import datetime
from app.extensions import db
from app.models import User, InspectorRun, Inspector
from utils.auth_helpers import logged_in, current_role, is_admin_role, get_scoped_inspector_query
from app.services.actions_service import get_actions
#NOTE: This is to be removed in the future in favour of automatic assignment of inspectors based on the algorithm. TODO!

assignments_api = Blueprint("assignments_api", __name__)

def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8):
    """
    Assign runs only to inspectors that belong to the current admin scope.
    """
    actions = get_actions
    if actions is None:
        print("⚠️ Actions module not initialized — cannot assign runs.")
        return []

    results = []
    try:
        inspector_users = get_scoped_inspector_query().all()
        inspector_ids = [u.inspector_id for u in inspector_users if u.inspector_id]
        inspectors_db = Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids)).all() if inspector_ids else []

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
    if not logged_in() or not is_admin_role():
        return jsonify({"error": "unauthorized"}), 401

    results = assign_and_persist_runs()
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})
