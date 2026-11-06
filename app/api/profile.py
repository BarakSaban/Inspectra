import logging

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import Inspector, User
from app.utils.auth import clean_text, get_request_data, login_required_api, password_problem

logger = logging.getLogger(__name__)

profile_api = Blueprint("profile_api", __name__)


@profile_api.route('/api/profile', methods=['GET', 'POST'])
@login_required_api
def api_profile():
    user = User.query.filter_by(username=session.get('user')).first()
    if not user:
        return jsonify({"error": "user not found"}), 404

    if request.method == 'GET':
        return jsonify({
            "username": user.username,
            "role": user.role,
            "inspector_id": user.inspector_id,
            "manager_code": user.manager_code if user.role == "admin" else None,
            "full_name": user.full_name,
            "must_change": bool(user.must_change),
        })

    data = get_request_data()
    if not data:
        return jsonify({"error": "no data provided"}), 400

    new_username = clean_text(data.get('username') or user.username, 200)
    new_password = data.get('password')
    new_full_name = clean_text(data.get('full_name'), 120) if data.get('full_name') is not None else None

    if new_password:
        # Changing a password needs the current one (a stolen open session is not enough), except when it is a temporary one.
        if not user.must_change and not user.check_password(data.get('current_password') or ""):
            return jsonify({"error": "Current password is wrong"}), 400
        problem = password_problem(new_password)
        if problem:
            return jsonify({"error": problem}), 400
        if user.must_change and user.check_password(new_password):
            return jsonify({"error": "Choose a new password"}), 400
    elif user.must_change:
        return jsonify({"error": "Choose a new password"}), 400

    if not new_username:
        return jsonify({"error": "username cannot be empty"}), 400
    if new_username != user.username:
        if User.query.filter_by(username=new_username).first():
            return jsonify({"error": "username already taken"}), 400
        user.username = new_username
        session['user'] = new_username

    if new_password:
        user.set_password(new_password)
        user.must_change = False
        user.end_sessions()
        session['sv'] = user.session_version

    if new_full_name is not None:
        user.full_name = new_full_name

    # Keep the inspector record's display name in sync
    if user.role == "inspector" and user.inspector_id and new_full_name:
        inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()
        if inspector:
            inspector.name = new_full_name

    try:
        db.session.commit()
        return jsonify({"success": True, "message": "Profile updated successfully"})
    except Exception:
        db.session.rollback()
        logger.exception("api_profile update failed")
        return jsonify({"error": "server error"}), 500
