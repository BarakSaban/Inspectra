import logging

from flask import Blueprint, jsonify, session

from app.extensions import db
from app.models import Inspector, InspectorRun
from app.services.inspectors import get_admin_inspector_users, get_inspector_ids
from app.services.recommendations import fetch_live_options
from app.services.routing import InspectorLocation, get_engine
from app.services.runs import ACTIVE_STATUSES
from app.utils.auth import admin_required_api
from app.utils.clock import now_local

logger = logging.getLogger(__name__)

# NOTE: manual assignment trigger; meant to be replaced by automatic assignment based on the algorithm.
assignments_api = Blueprint("assignments_api", __name__)


def assign_and_persist_runs(buffer_minutes=3, radius_m=666, max_walk_minutes=8, admin_code=None):
    """
    Assign the best trips (live SIRI buses first, static GTFS as fallback) to available inspectors
    and persist them as InspectorRuns. Only inspectors of admin_code are considered when it is given.
    Inspectors who already have an active run are skipped so repeated calls don't pile up assignments.
    """
    engine = get_engine()
    if engine is None:
        logger.warning("Routing engine unavailable (GTFS not loaded); cannot assign runs.")
        return []

    try:
        query = Inspector.query.filter(Inspector.available.is_(True))
        if admin_code:
            query = query.filter(Inspector.inspector_id.in_(get_inspector_ids(get_admin_inspector_users(admin_code))))
        rows = [i for i in query.all() if i.latitude is not None and i.longitude is not None]

        busy = {
            inspector_id for (inspector_id,) in
            db.session.query(InspectorRun.inspector_id).filter(InspectorRun.status.in_(ACTIVE_STATUSES))
        }
        inspectors = [
            InspectorLocation(i.inspector_id, i.latitude, i.longitude)
            for i in rows if i.inspector_id not in busy
        ]
        if not inspectors:
            return []

        live_options_by_inspector = {
            i.inspector_id: fetch_live_options(i.lat, i.lon, engine.gtfs, radius_m) for i in inspectors
        }
        assigned = engine.assign_best_trips_global(
            inspectors, buffer_minutes, radius_m, max_walk_minutes, live_options_by_inspector=live_options_by_inspector
        )
        if assigned is None or assigned.empty:
            return []

        runs = [
            InspectorRun(
                inspector_id=row['inspector_id'],
                trip_id=str(row['trip_id']),
                stop_id=str(row['stop_id']),
                potential_fines=int(row['potential_fines']),
                assigned_at=now_local(),
                status="assigned",
            )
            for row in assigned.to_dict(orient='records')
        ]
        db.session.add_all(runs)
        db.session.commit()
        return [
            {
                "run_id": run.id,
                "inspector_id": run.inspector_id,
                "trip_id": run.trip_id,
                "stop_id": run.stop_id,
                "potential_fines": run.potential_fines,
            }
            for run in runs
        ]
    except Exception:
        logger.exception("assign_and_persist_runs failed")
        db.session.rollback()
        return []


@assignments_api.route('/api/assign_runs', methods=['POST'])
@admin_required_api
def api_assign_runs():
    results = assign_and_persist_runs(admin_code=session.get('admin_code'))
    return jsonify({"assigned_count": len(results), "results_preview": results[:10]})
