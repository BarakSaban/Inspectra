from datetime import date, datetime
from flask import Blueprint, jsonify, session
from sqlalchemy import func
import pandas as pd

from app.extensions import db
from app.models import User, InspectorRun, Fine
from Classes import Inspector
from utils.auth_helpers import logged_in, current_role

analytics_api = Blueprint("analytics_api", __name__)

@analytics_api.route('/api/analytics')
def api_analytics():
    """
    Returns summary analytics for the current admin's inspectors only.
    """
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400

        # inspector users belonging to admin
        inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()
        inspector_ids = [u.inspector_id for u in inspector_users if u.inspector_id]

        # basic totals
        totalFines = 0
        weeklyTotal = 0
        today = date.today()
        seven_days_ago = datetime.now() - pd.Timedelta(days=7)

        for iid in inspector_ids:
            # count fines for today and week
            totalFines += db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==iid, func.date(Fine.timestamp)==today).scalar() or 0
            weeklyTotal += db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==iid, Fine.timestamp>=seven_days_ago).scalar() or 0

        # active inspectors: those available == True (from Inspector table)
        activeInspectors = Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids), Inspector.available==True).count() if inspector_ids else 0

        # avgEfficiency: simple metric: completed_trips / (completed_trips + potential) across inspector_ids if fields exist
        total_completed = 0
        total_potential = 0
        for iid in inspector_ids:
            total_completed += db.session.query(func.coalesce(func.sum(InspectorRun.actual_fines), 0)).filter(InspectorRun.inspector_id==iid).scalar() or 0
            total_potential += db.session.query(func.coalesce(func.sum(InspectorRun.potential_fines), 0)).filter(InspectorRun.inspector_id==iid).scalar() or 0

        avgEfficiency = int((total_completed / total_potential * 100) if (total_potential > 0) else 0)

        # prepare inspectors summary for frontend (small)
        inspectors_summary = []
        for u in inspector_users:
            insp = Inspector.query.filter_by(inspector_id=u.inspector_id).first()
            inspectors_summary.append({
                "inspector_id": u.inspector_id,
                "name": getattr(insp, 'name', u.full_name or u.username),
                "latitude": getattr(insp, 'latitude', None),
                "longitude": getattr(insp, 'longitude', None),
                "available": getattr(insp, 'available', True),
                "total_fines": getattr(insp, 'total_fines', 0),
                "completed_trips": getattr(insp, 'completed_trips', 0)
            })

        return jsonify({
            "totalFines": totalFines,
            "weeklyTotal": weeklyTotal,
            "activeInspectors": activeInspectors,
            "avgEfficiency": avgEfficiency,
            "inspectors": inspectors_summary
        })
    except Exception as e:
        print("⚠️ api_analytics error:", e)
        return jsonify({"error": "server error"}), 500
    