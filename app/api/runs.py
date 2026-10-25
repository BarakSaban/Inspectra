"""An inspector's own runs and status. Admin-side assignment lives in `assignments.py`."""
import logging

from flask import Blueprint, jsonify, request

from app.extensions import db
from app.models import Inspector, InspectorRun
from app.services import runs
from app.utils.auth import current_inspector_id, inspector_required_api

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


@runs_api.route('/api/runs/current', methods=['GET'])
@inspector_required_api
def current_run():
    run = runs.get_active_run(current_inspector_id())
    return jsonify({"run": runs.serialize_run(run) if run else None})


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


@runs_api.route('/api/me/status', methods=['PUT'])
@inspector_required_api
def update_status():
    """The inspector goes available/unavailable and may report a position."""
    inspector = Inspector.query.filter_by(inspector_id=current_inspector_id()).first()
    if inspector is None:
        return jsonify({"error": "inspector not found"}), 404

    body = _json_body()
    try:
        if "available" in body:
            inspector.available = bool(body["available"])
        if "latitude" in body or "longitude" in body:
            lat, lon = float(body["latitude"]), float(body["longitude"])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("coordinates out of range")
            inspector.latitude, inspector.longitude = lat, lon
        db.session.commit()
    except (KeyError, TypeError, ValueError) as exc:
        db.session.rollback()
        return jsonify({"error": f"invalid status: {exc}"}), 400
    return jsonify({"available": inspector.available, "latitude": inspector.latitude, "longitude": inspector.longitude})
