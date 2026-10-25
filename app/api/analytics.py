import logging
from datetime import timedelta

from flask import Blueprint, jsonify, session
from sqlalchemy import func

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
from app.services.inspectors import (
    get_admin_inspector_users,
    get_inspector_ids,
    get_inspectors_by_id,
)
from app.services.runs import ACTIVE_STATUSES
from app.utils.auth import admin_required_api
from app.utils.clock import now_local

logger = logging.getLogger(__name__)

analytics_api = Blueprint("analytics_api", __name__)


@analytics_api.route('/api/analytics')
@admin_required_api
def api_analytics():
    """Summary analytics for the current admin's inspectors only."""
    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400

        users = get_admin_inspector_users(admin_code)
        ids = get_inspector_ids(users)
        inspectors = get_inspectors_by_id(ids)
        now = now_local()
        seven_days_ago = now - timedelta(days=7)

        total_fines = weekly_total = active_inspectors = assigned_inspectors = 0
        avg_completion_min = None
        total_actual = total_potential = 0
        if ids:
            total_fines = db.session.query(func.count(Fine.id)).filter(
                Fine.inspector_id.in_(ids), func.date(Fine.timestamp) == now.date().isoformat()
            ).scalar() or 0
            weekly_total = db.session.query(func.count(Fine.id)).filter(
                Fine.inspector_id.in_(ids), Fine.timestamp >= seven_days_ago
            ).scalar() or 0
            active_inspectors = Inspector.query.filter(Inspector.inspector_id.in_(ids), Inspector.available.is_(True)).count()
            total_actual, total_potential = db.session.query(
                func.coalesce(func.sum(InspectorRun.actual_fines), 0),
                func.coalesce(func.sum(InspectorRun.potential_fines), 0),
            ).filter(InspectorRun.inspector_id.in_(ids)).one()
            assigned_inspectors = db.session.query(func.count(func.distinct(InspectorRun.inspector_id))).filter(
                InspectorRun.inspector_id.in_(ids), InspectorRun.status.in_(ACTIVE_STATUSES)
            ).scalar() or 0
            finished_today = db.session.query(InspectorRun.accepted_at, InspectorRun.finished_at).filter(
                InspectorRun.inspector_id.in_(ids), InspectorRun.status == "completed",
                InspectorRun.accepted_at.isnot(None), func.date(InspectorRun.finished_at) == now.date().isoformat(),
            ).all()
            if finished_today:
                minutes = [(done - started).total_seconds() / 60 for started, done in finished_today]
                avg_completion_min = round(sum(minutes) / len(minutes), 1)

        avg_efficiency = int(total_actual / total_potential * 100) if total_potential > 0 else 0

        inspectors_summary = []
        for user in users:
            inspector = inspectors.get(user.inspector_id)
            inspectors_summary.append({
                "inspector_id": user.inspector_id,
                "name": inspector.name if inspector else (user.full_name or user.username),
                "latitude": inspector.latitude if inspector else None,
                "longitude": inspector.longitude if inspector else None,
                "available": inspector.available if inspector else True,
                "total_fines": inspector.total_fines if inspector else 0,
                "completed_trips": inspector.completed_trips if inspector else 0,
            })

        return jsonify({
            "totalFines": total_fines,
            "weeklyTotal": weekly_total,
            "activeInspectors": active_inspectors,
            "assignedInspectors": assigned_inspectors,
            "unassignedInspectors": len(ids) - assigned_inspectors,
            "avgCompletionMin": avg_completion_min,
            "avgEfficiency": avg_efficiency,
            "inspectors": inspectors_summary,
        })
    except Exception:
        logger.exception("api_analytics failed")
        return jsonify({"error": "server error"}), 500
