"""Manager tools beyond the dashboard: activity feed, manual assignment, inspector detail and reactivation."""
import logging

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import Inspector, InspectorRun, User
from app.services import push as push_service
from app.services import runs as run_service
from app.services.activity import inspector_detail, recent_activity
from app.services.inspectors import (
    STALE_POSITION_SECONDS,
    find_owned_inspector,
    get_admin_inspector_users,
    get_inspector_ids,
    inspector_state,
    seconds_since,
)
from app.services.live_trips import get_live_trip_options
from app.services.recommendations import describe_run
from app.services.routing import get_engine
from app.services.team import audit, get_settings, recent_audit, update_settings
from app.utils.auth import admin_required_api
from app.utils.clock import now_local
from app.utils.serialization import to_serializable

logger = logging.getLogger(__name__)

admin_ops_api = Blueprint("admin_ops_api", __name__)

MAX_OPTIONS = 15
MAX_OPTION_RADIUS_M = 1500


@admin_ops_api.route('/api/activity', methods=['GET'])
@admin_required_api
def activity():
    """What the team has been doing: offers, accepted rides, finished rides (with fines) and cancellations."""
    try:
        limit = int(request.args.get("limit", 30))
    except ValueError:
        return jsonify({"error": "limit must be a number"}), 400
    ids = get_inspector_ids(get_admin_inspector_users(session.get('admin_code')))
    return jsonify({"events": recent_activity(ids, limit)})


OFFER_PATIENCE_S = 90          # the phone gives an offer 30 s; this long without an answer is worth a look
BREAK_GRACE_S = 120            # a break may run over by this much before it is flagged


@admin_ops_api.route('/api/attention', methods=['GET'])
@admin_required_api
def attention():
    """What needs the manager right now: unanswered offers, silent phones, breaks that ran over."""
    users = get_admin_inspector_users(session.get('admin_code'))
    ids = get_inspector_ids(users)
    if not ids:
        return jsonify({"items": []})
    now = now_local()
    people = {i.inspector_id: i for i in Inspector.query.filter(Inspector.inspector_id.in_(ids)).all()}
    items = []
    offers = InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids), InspectorRun.status == "assigned").all()
    offered = {r.inspector_id for r in offers}
    for run in offers:
        waited = seconds_since(run.assigned_at, now)
        if waited is not None and waited > OFFER_PATIENCE_S and run.inspector_id in people:
            items.append({"kind": "offer_unanswered", "inspector_id": run.inspector_id, "name": people[run.inspector_id].name, "seconds": waited, "run_id": run.id})
    for person in people.values():
        if person.break_until and person.break_until < now and (now - person.break_until).total_seconds() > BREAK_GRACE_S:
            items.append({"kind": "break_overrun", "inspector_id": person.inspector_id, "name": person.name, "seconds": int((now - person.break_until).total_seconds())})
        elif person.available and person.inspector_id not in offered and person.location_updated_at is not None:
            quiet = seconds_since(person.location_updated_at, now)
            if quiet is not None and quiet > STALE_POSITION_SECONDS:
                items.append({"kind": "phone_silent", "inspector_id": person.inspector_id, "name": person.name, "seconds": quiet})
    items.sort(key=lambda i: -i["seconds"])
    return jsonify({"items": items})


@admin_ops_api.route('/api/admin/options', methods=['GET'])
@admin_required_api
def assignment_options():
    """Live buses an inspector could be sent to right now, with expected fines, for manual assignment."""
    owned = find_owned_inspector(session.get('admin_code'), request.args.get("inspector_id"))
    if owned is None:
        return jsonify({"error": "not found"}), 404
    inspector = owned[1]
    if inspector.latitude is None or inspector.longitude is None:
        return jsonify({"error": "inspector has no position yet"}), 409
    try:
        radius = float(request.args.get("radius", 800))
        if not 0 < radius <= MAX_OPTION_RADIUS_M:
            raise ValueError
    except ValueError:
        return jsonify({"error": "invalid radius"}), 400

    engine = get_engine()
    if engine is None:
        return jsonify({"options": [], "source": "unavailable"})
    try:
        live = get_live_trip_options(inspector.latitude, inspector.longitude, engine.gtfs, radius)
    except Exception:
        logger.exception("assignment options failed")
        return jsonify({"options": [], "source": "error"})

    options = []
    for o in live[:MAX_OPTIONS * 2]:
        props = (o.get("stop_feature") or {}).get("properties") or {}
        options.append({
            "trip_id": o["trip_id"], "stop_id": o["stop_id"], "route_id": o["route_id"], "route_num": o["route_num"],
            "destination": o["destination"], "stop_name": props.get("stop_name"),
            "minutes_until_arrival": o["minutes_until_arrival"],
            "potential_fines": engine.estimate_potential_fines(o["route_id"], o["stop_id"], o["minutes_until_arrival"]),
        })
    options.sort(key=lambda x: (-x["potential_fines"], x["minutes_until_arrival"]))
    return jsonify(to_serializable({"options": options[:MAX_OPTIONS], "source": "live"}))


@admin_ops_api.route('/api/admin/assign', methods=['POST'])
@admin_required_api
def assign_manually():
    """Send one inspector to a chosen bus. The inspector sees it as an offer and accepts or declines."""
    body = request.get_json(silent=True) or {}
    owned = find_owned_inspector(session.get('admin_code'), body.get("inspector_id"))
    if owned is None:
        return jsonify({"error": "not found"}), 404
    trip_id, stop_id = body.get("trip_id"), body.get("stop_id")
    if not trip_id or stop_id is None:
        return jsonify({"error": "trip_id and stop_id are required"}), 400
    try:
        fines = int(body.get("potential_fines", 0))
        if not 0 <= fines <= run_service.MAX_FINES_PER_RUN:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "potential_fines must be a non-negative number"}), 400
    if run_service.get_active_run(owned[1].inspector_id) is not None:
        return jsonify({"error": "this inspector already has an active run"}), 409
    if owned[1].break_until and owned[1].break_until > now_local():
        return jsonify({"error": "this inspector is on a break"}), 409

    try:
        run = run_service.create_run(inspector_id=owned[1].inspector_id, trip_id=str(trip_id), stop_id=str(stop_id),
                                     potential_fines=fines, assigned_at=now_local(), status="assigned")
    except run_service.RunError as exc:
        return jsonify({"error": exc.message}), exc.status
    db.session.commit()
    audit(session.get('admin_code'), session.get('user'), "run_assigned", owned[1].inspector_id, f"trip {trip_id}")
    push_service.notify_inspector(owned[1].inspector_id, "offer")
    return jsonify(run_service.serialize_run(run)), 201


@admin_ops_api.route('/api/admin/runs/<int:run_id>/cancel', methods=['POST'])
@admin_required_api
def cancel_inspector_run(run_id):
    """Take back an offer or stop a ride of one of the manager's own inspectors."""
    run = db.session.get(InspectorRun, run_id)
    if run is None or find_owned_inspector(session.get('admin_code'), run.inspector_id) is None:
        return jsonify({"error": "run not found"}), 404
    try:
        run_service.cancel_run(run)
    except run_service.RunError as exc:
        db.session.rollback()
        return jsonify({"error": exc.message}), exc.status
    audit(session.get('admin_code'), session.get('user'), "run_cancelled", run.inspector_id, f"run {run.id}")
    return jsonify(run_service.serialize_run(run))


@admin_ops_api.route('/api/inspector/<inspector_id>/detail', methods=['GET'])
@admin_required_api
def inspector_detail_api(inspector_id):
    owned = find_owned_inspector(session.get('admin_code'), inspector_id)
    if owned is None:
        return jsonify({"error": "not found"}), 404
    user, inspector = owned
    run = run_service.get_active_run(inspector_id)
    detail = inspector_detail(inspector)
    for ride in detail["runs"][:10]:       # name the line and stop when the timetable knows the trip
        try:
            d = describe_run(ride["trip_id"], ride["stop_id"])
        except Exception:
            d = None
        if d:
            ride["route_num"], ride["destination"] = d.get("route_num"), d.get("destination")
            ride["stop_name"] = ((d.get("stop_feature") or {}).get("properties") or {}).get("stop_name")
    return jsonify(to_serializable({
        "inspector_id": inspector_id, "username": user.username, "name": inspector.name, "email": inspector.email,
        "latitude": inspector.latitude, "longitude": inspector.longitude,
        "state": inspector_state(inspector, run), "last_seen_seconds": seconds_since(inspector.location_updated_at),
        "current_run": run_service.serialize_run(run) if run else None,
        **detail,
    }))


@admin_ops_api.route('/api/inspector/<inspector_id>/stats', methods=['GET'])
@admin_required_api
def inspector_stats_view(inspector_id):
    from app.api.runs import stats_answer
    owned = find_owned_inspector(session.get('admin_code'), inspector_id)
    if owned is None:
        return jsonify({"error": "not found"}), 404
    from app.services.stats import inspector_logs
    return stats_answer(owned[1], logs=lambda period, offset: inspector_logs(inspector_id, period, offset))


@admin_ops_api.route('/api/staff/deactivated', methods=['GET'])
@admin_required_api
def deactivated_staff():
    """Inspectors this manager removed but who have history, so they can be brought back."""
    code = session.get('admin_code')
    if not code:
        return jsonify([])
    users = User.query.filter_by(role='inspector', former_manager_code=code, manager_code=None).all()
    inspectors = {i.inspector_id: i for i in Inspector.query.filter(Inspector.inspector_id.in_([u.inspector_id for u in users])).all()} if users else {}
    return jsonify([{"inspector_id": u.inspector_id, "name": getattr(inspectors.get(u.inspector_id), "name", u.full_name or u.username),
                     "total_fines": getattr(inspectors.get(u.inspector_id), "total_fines", 0)} for u in users])


@admin_ops_api.route('/api/inspector/<inspector_id>/reactivate', methods=['POST'])
@admin_required_api
def reactivate_inspector(inspector_id):
    code = session.get('admin_code')
    user = User.query.filter_by(role='inspector', inspector_id=inspector_id, former_manager_code=code, manager_code=None).first() if code else None
    if user is None:
        return jsonify({"error": "not found"}), 404
    user.manager_code, user.former_manager_code = code, None
    inspector = Inspector.query.filter_by(inspector_id=inspector_id).first()
    if inspector is not None:
        inspector.available = True
    db.session.commit()
    audit(code, session.get('user'), "inspector_reactivated", inspector_id)
    return jsonify({"success": True, "inspector_id": inspector_id})


@admin_ops_api.route('/api/team/settings', methods=['GET'])
@admin_required_api
def team_settings():
    return jsonify(get_settings(session.get('admin_code')))


@admin_ops_api.route('/api/team/settings', methods=['PUT'])
@admin_required_api
def save_team_settings():
    code = session.get('admin_code')
    if not code:
        return jsonify({"error": "no admin code in session"}), 400
    body = request.get_json(silent=True) or {}
    try:
        saved = update_settings(code, body)
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    audit(code, session.get('user'), "settings_changed", None, ", ".join(f"{k}={v}" for k, v in saved.items()))
    return jsonify(saved)


@admin_ops_api.route('/api/audit', methods=['GET'])
@admin_required_api
def audit_log():
    code = session.get('admin_code')
    return jsonify({"entries": recent_audit(code, request.args.get("limit", 50)) if code else []})


@admin_ops_api.route('/api/staff/bulk', methods=['POST'])
@admin_required_api
def bulk_staff():
    """Take several of the manager's inspectors online or offline, or deactivate them, at once."""
    code = session.get('admin_code')
    body = request.get_json(silent=True) or {}
    action, ids = body.get("action"), body.get("inspector_ids")
    if action not in ("online", "offline", "deactivate") or not isinstance(ids, list) or not ids or len(ids) > 200:
        return jsonify({"error": "action must be online, offline or deactivate, with a list of inspector_ids"}), 400
    users = {u.inspector_id: u for u in get_admin_inspector_users(code)}
    chosen = [i for i in ids if isinstance(i, str) and i in users]
    changed = 0
    for inspector in Inspector.query.filter(Inspector.inspector_id.in_(chosen)).all() if chosen else []:
        inspector.available = action == "online"
        inspector.break_until = None
        if action == "deactivate":
            user = users[inspector.inspector_id]
            user.former_manager_code, user.manager_code = user.manager_code, None
            user.end_sessions()
        changed += 1
    db.session.commit()
    if changed:
        audit(code, session.get('user'), f"bulk_{action}", str(changed))
    return jsonify({"changed": changed})
