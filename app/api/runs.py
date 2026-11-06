"""An inspector's own runs and status. Admin-side assignment lives in `assignments.py`."""
import logging

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import Inspector, InspectorRun
from app.services import runs, shifts
from app.services.recommendations import describe_run
from app.services.stats import inspector_stats
from app.utils.auth import current_inspector_id, inspector_required_api
from app.utils.clock import now_local
from app.utils.serialization import to_serializable

logger = logging.getLogger(__name__)

runs_api = Blueprint("runs_api", __name__)


def _json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _answer(action, *args, status=200, **kwargs):
    """Run a lifecycle action and answer with the resulting run, mapping RunError to its HTTP status."""
    try:
        run = action(*args, **kwargs)
    except runs.RunError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status
    except Exception:
        db.session.rollback()
        logger.exception("run action failed")
        return jsonify({"error": "server error"}), 500
    return jsonify(runs.serialize_run(run)), status


def _on_own_run(run_id, action, **kwargs):
    run = db.session.get(InspectorRun, run_id)
    if run is None or run.inspector_id != current_inspector_id():
        return jsonify({"error": "run not found"}), 404
    return _answer(action, run, **kwargs)


@runs_api.route('/api/me', methods=['GET'])
@inspector_required_api
def me():
    """The signed-in inspector's profile plus today's numbers, for the field app's home and settings screens."""
    inspector = Inspector.query.filter_by(inspector_id=current_inspector_id()).first()
    if inspector is None:
        return jsonify({"error": "inspector not found"}), 404
    return jsonify(runs.serialize_inspector_summary(inspector))


@runs_api.route('/api/me/history', methods=['GET'])
@inspector_required_api
def my_history():
    """Fines per day for the last week and the latest finished rides, for the field app's "My day" screen."""
    try:
        days = int(request.args.get("days", 7))
    except ValueError:
        return jsonify({"error": "days must be a number"}), 400
    history = runs.inspector_history(current_inspector_id(), days=days)
    for ride in history["rides"][:10]:  # name the line and stop when the timetable knows the trip
        try:
            details = describe_run(ride["trip_id"], ride["stop_id"])
        except Exception:
            details = None
        if details:
            ride["route_num"] = details.get("route_num")
            ride["destination"] = details.get("destination")
            ride["stop_name"] = (details.get("stop_feature") or {}).get("properties", {}).get("stop_name")
    return jsonify(to_serializable(history))


def name_rides(rides, limit=15):
    """Name the line and stop of the first rides when the timetable knows the trip."""
    for ride in rides[:limit]:
        try:
            details = describe_run(ride["trip_id"], ride["stop_id"])
        except Exception:
            details = None
        if details:
            ride["route_num"] = details.get("route_num")
            ride["destination"] = details.get("destination")
            ride["stop_name"] = (details.get("stop_feature") or {}).get("properties", {}).get("stop_name")
    return rides


def stats_answer(inspector, logs=None):
    """Shared by the inspector's own page and the manager's view of one inspector."""
    try:
        period = request.args.get("period", "week")
        offset = int(request.args.get("offset", 0))
        data = inspector_stats(inspector, period, offset)
    except ValueError as exc:
        return jsonify({"error": str(exc) if "period" in str(exc) else "offset must be a number"}), 400
    name_rides(data["rides"])
    if logs is not None:
        data.update(logs(data["period"], data["offset"]))
    return jsonify(to_serializable(data))


@runs_api.route('/api/me/stats', methods=['GET'])
@inspector_required_api
def my_stats():
    """The inspector's numbers over a day, week, month or year, with the previous period for comparison."""
    inspector = Inspector.query.filter_by(inspector_id=current_inspector_id()).first()
    if inspector is None:
        return jsonify({"error": "inspector not found"}), 404
    return stats_answer(inspector)


@runs_api.route('/api/runs/current', methods=['GET'])
@inspector_required_api
def current_run():
    run = runs.get_active_run(current_inspector_id())
    return jsonify({"run": runs.serialize_run(run) if run else None})


@runs_api.route('/api/runs/<int:run_id>/details', methods=['GET'])
@inspector_required_api
def run_details(run_id):
    """Route, destination, stop and shape of one of the inspector's own runs (to redraw it after a reload)."""
    run = db.session.get(InspectorRun, run_id)
    if run is None or run.inspector_id != current_inspector_id():
        return jsonify({"error": "run not found"}), 404
    try:
        details = describe_run(run.trip_id, run.stop_id)
    except Exception:
        logger.exception("describe_run failed for run %s", run_id)
        details = None
    return jsonify(to_serializable({"run": runs.serialize_run(run), "details": details}))


@runs_api.route('/api/runs', methods=['POST'])
@inspector_required_api
def start_run():
    body = _json_body()
    return _answer(runs.start_run, current_inspector_id(), status=201, trip_id=body.get("trip_id"),
                   stop_id=body.get("stop_id"), potential_fines=body.get("potential_fines", 0))


@runs_api.route('/api/runs/<int:run_id>/accept', methods=['POST'])
@inspector_required_api
def accept_run(run_id):
    return _on_own_run(run_id, runs.accept_run)


@runs_api.route('/api/runs/<int:run_id>/cancel', methods=['POST'])
@inspector_required_api
def cancel_run(run_id):
    return _on_own_run(run_id, runs.cancel_run)


@runs_api.route('/api/runs/<int:run_id>/complete', methods=['POST'])
@inspector_required_api
def complete_run(run_id):
    return _on_own_run(run_id, runs.complete_run, actual_fines=_json_body().get("actual_fines", 0))


@runs_api.route('/api/runs/<int:run_id>/progress', methods=['PATCH'])
@inspector_required_api
def run_progress(run_id):
    """Save the running fine count of an accepted run (the field app's +/- counter)."""
    return _on_own_run(run_id, runs.update_progress, fines=_json_body().get("fines", 0))


@runs_api.route('/api/me/status', methods=['PUT'])
@inspector_required_api
def update_status():
    """The inspector goes available/unavailable and may report a position."""
    inspector = Inspector.query.filter_by(inspector_id=current_inspector_id()).first()
    if inspector is None:
        return jsonify({"error": "inspector not found"}), 404

    body = _json_body()
    try:
        if "break_extend" in body:
            runs.set_break(inspector, extend=body["break_extend"])
        elif "break_minutes" in body:
            runs.set_break(inspector, body["break_minutes"], reason=body.get("break_reason"))
        elif "available" in body:  # going online/offline by hand always ends a break
            going_online = bool(body["available"])
            inspector.break_until = None
            shifts.end_break_log(inspector.inspector_id)
            if going_online:
                shifts.open_shift(inspector.inspector_id)
            else:
                shifts.close_shift(inspector.inspector_id)
            inspector.available = going_online
        if "latitude" in body or "longitude" in body:
            lat, lon = float(body["latitude"]), float(body["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("coordinates out of range")
            inspector.latitude, inspector.longitude = lat, lon
            inspector.location_updated_at = now_local()
        db.session.commit()
    except runs.RunError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status
    except (KeyError, TypeError, ValueError) as exc:
        db.session.rollback()
        return jsonify({"error": f"invalid status: {exc}"}), 400
    return jsonify({"available": inspector.available, "latitude": inspector.latitude, "longitude": inspector.longitude})
