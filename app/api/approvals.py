"""Manager accounts wait for the owner's approval; a manager can also replace their invite code."""
import logging

from flask import Blueprint, g, jsonify, session

from app.extensions import db
from app.models import AuditLog, TeamSettings, User
from app.services.team import audit
from app.utils.auth import admin_required_api, generate_manager_code

logger = logging.getLogger(__name__)

approvals_api = Blueprint("approvals_api", __name__)


def _owner_only():
    user = getattr(g, "user", None)
    return user is not None and user.is_owner


@approvals_api.route('/api/approvals', methods=['GET'])
@admin_required_api
def pending_managers():
    """Managers who signed up and are waiting. Only the owner account sees this list."""
    if not _owner_only():
        return jsonify({"owner": False, "pending": []})
    rows = User.query.filter_by(role='admin', approved=False).order_by(User.id).all()
    return jsonify({"owner": True, "pending": [{"username": u.username, "name": u.full_name or u.username} for u in rows]})


@approvals_api.route('/api/approvals/<path:username>/<decision>', methods=['POST'])
@admin_required_api
def decide(username, decision):
    if not _owner_only():
        return jsonify({"error": "unauthorized"}), 403
    if decision not in ("approve", "reject"):
        return jsonify({"error": "not found"}), 404
    user = User.query.filter_by(username=username, role='admin', approved=False).first()
    if user is None:
        return jsonify({"error": "not found"}), 404
    if decision == "approve":
        user.approved = True
    else:
        db.session.delete(user)   # a pending manager has no team or history yet
    db.session.commit()
    audit(session.get('admin_code'), session.get('user'), f"manager_{decision}d", username)
    return jsonify({"success": True})


@approvals_api.route('/api/admin/code/rotate', methods=['POST'])
@admin_required_api
def rotate_code():
    """Replace the invite code (a leaked one stops working). The team keeps everything; only the code changes."""
    old = session.get('admin_code')
    if not old:
        return jsonify({"error": "no admin code in session"}), 400
    for _ in range(500):
        new = generate_manager_code()
        if not User.query.filter((User.manager_code == new) | (User.former_manager_code == new)).first():
            break
    else:
        return jsonify({"error": "server error"}), 500
    try:
        User.query.filter_by(manager_code=old).update({"manager_code": new})
        User.query.filter_by(former_manager_code=old).update({"former_manager_code": new})
        TeamSettings.query.filter_by(admin_code=old).update({"admin_code": new})
        AuditLog.query.filter_by(admin_code=old).update({"admin_code": new})
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("rotate_code failed")
        return jsonify({"error": "server error"}), 500
    session['admin_code'] = new
    audit(new, session.get('user'), "code_rotated")
    return jsonify({"manager_code": new})
