from datetime import date, datetime
from flask import Blueprint, jsonify, session
from sqlalchemy import func

from app.extensions import db
from app.models import User, InspectorRun, Fine
from Classes import Inspector
from utils.auth_helpers import logged_in, current_role
import pandas as pd

staff_api = Blueprint("staff_api", __name__)

@staff_api.route('/api/staff')
def api_staff():
    """
    Returns the list of inspectors that belong to the currently-logged-in admin
    (filtered by manager_code stored in session). If session has no admin_code,
    returns empty list.
    """
    if not logged_in() or current_role() != 'admin':
        return jsonify({"error": "unauthorized"}), 401

    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify([])

        # find Users that are inspectors under this admin
        inspector_users = User.query.filter_by(role='inspector', manager_code=admin_code).all()

        today = date.today()
        seven_days_ago = datetime.now() - pd.Timedelta(days=7)

        staff_list = []
        for u in inspector_users:
            # try to find Inspector record for coordinates/status
            insp = Inspector.query.filter_by(inspector_id=u.inspector_id).first()
            weekly_fines = db.session.query(func.count(Fine.id)).filter(Fine.inspector_id==u.inspector_id, Fine.timestamp>=seven_days_ago).scalar() or 0
            today_trips = db.session.query(func.count(InspectorRun.id)).filter(InspectorRun.inspector_id==u.inspector_id, func.date(InspectorRun.assigned_at)==today).scalar() or 0
            current_run = InspectorRun.query.filter_by(inspector_id=u.inspector_id).filter(InspectorRun.status.in_( ["assigned","accepted"]) ).order_by(InspectorRun.assigned_at.desc()).first()
            current_assignment = {
                "trip_id": current_run.trip_id,
                "status": current_run.status,
                "potential_fines": current_run.potential_fines
            } if current_run else None

            staff_list.append({
                "inspector_id": u.inspector_id,
                "username": u.username,
                "name": getattr(insp, 'name', u.full_name or u.username),
                "email": getattr(u, 'email', None),
                "latitude": getattr(insp, 'latitude', None),
                "longitude": getattr(insp, 'longitude', None),
                "available": getattr(insp, 'available', True),
                "today_trips": today_trips,
                "weekly_fines": weekly_fines,
                "current_assignment": current_assignment,
                # optional: totals from Inspector table if present
                "total_fines": getattr(insp, 'total_fines', 0),
                "completed_trips": getattr(insp, 'completed_trips', 0)
            })

        return jsonify(staff_list)
    except Exception as e:
        print("⚠️ api_staff error:", e)
        return jsonify({"error": "server error"}), 500
