import logging
from datetime import timedelta

from flask import Blueprint, jsonify, session
from sqlalchemy import func

from app.extensions import db
from app.models import Fine, InspectorRun
from app.services.inspectors import (
    get_admin_inspector_users,
    get_inspector_ids,
    get_inspectors_by_id,
)
from app.services.runs import ACTIVE_STATUSES
from app.utils.auth import admin_required_api
from app.utils.clock import now_local

logger = logging.getLogger(__name__)

staff_api = Blueprint("staff_api", __name__)


@staff_api.route('/api/staff')
@admin_required_api
def api_staff():
    """Inspectors of the logged-in admin (matched by manager_code) with their weekly/today stats."""
    try:
        users = get_admin_inspector_users(session.get('admin_code'))
        if not users:
            return jsonify([])

        ids = get_inspector_ids(users)
        inspectors = get_inspectors_by_id(ids)
        now = now_local()
        seven_days_ago = now - timedelta(days=7)

        # One grouped query per metric instead of several queries per inspector.
        weekly_fines = dict(
            db.session.query(Fine.inspector_id, func.count(Fine.id))
            .filter(Fine.inspector_id.in_(ids), Fine.timestamp >= seven_days_ago)
            .group_by(Fine.inspector_id).all()
        )
        today_trips = dict(
            db.session.query(InspectorRun.inspector_id, func.count(InspectorRun.id))
            .filter(InspectorRun.inspector_id.in_(ids), func.date(InspectorRun.assigned_at) == now.date().isoformat())
            .group_by(InspectorRun.inspector_id).all()
        )
        current_runs = {}
        for run in (
            InspectorRun.query
            .filter(InspectorRun.inspector_id.in_(ids), InspectorRun.status.in_(ACTIVE_STATUSES))
            .order_by(InspectorRun.assigned_at.desc()).all()
        ):
            current_runs.setdefault(run.inspector_id, run)  # newest first

        staff_list = []
        for user in users:
            inspector = inspectors.get(user.inspector_id)
            run = current_runs.get(user.inspector_id)
            staff_list.append({
                "inspector_id": user.inspector_id,
                "username": user.username,
                "name": inspector.name if inspector else (user.full_name or user.username),
                "email": inspector.email if inspector else None,
                "latitude": inspector.latitude if inspector else None,
                "longitude": inspector.longitude if inspector else None,
                "available": inspector.available if inspector else True,
                "today_trips": today_trips.get(user.inspector_id, 0),
                "weekly_fines": weekly_fines.get(user.inspector_id, 0),
                "current_assignment": {
                    "trip_id": run.trip_id,
                    "status": run.status,
                    "potential_fines": run.potential_fines,
                } if run else None,
                "total_fines": inspector.total_fines if inspector else 0,
                "completed_trips": inspector.completed_trips if inspector else 0,
            })

        return jsonify(staff_list)
    except Exception:
        logger.exception("api_staff failed")
        return jsonify({"error": "server error"}), 500
