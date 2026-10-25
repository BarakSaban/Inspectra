import logging

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import Inspector, User
from app.utils.auth import get_request_data, login_required_api

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
            "manager_code": user.manager_code,
            "full_name": user.full_name,
        })

    data = get_request_data()
    if not data:
        return jsonify({"error": "no data provided"}), 400

    new_username = (data.get('username') or user.username).strip()
    new_password = data.get('password')
    new_full_name = data.get('full_name')

    if not new_username:
        return jsonify({"error": "username cannot be empty"}), 400
    if new_username != user.username:
        if User.query.filter_by(username=new_username).first():
            return jsonify({"error": "username already taken"}), 400
        user.username = new_username
        session['user'] = new_username

    if new_password:
        user.set_password(new_password)

    if new_full_name is not None:
        user.full_name = new_full_name.strip()

    # Keep the inspector record's display name in sync
    if user.role == "inspector" and user.inspector_id and new_full_name:
        inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()
        if inspector:
            inspector.name = new_full_name.strip()

    try:
        db.session.commit()
        return jsonify({"success": True, "message": "Profile updated successfully"})
    except Exception:
        db.session.rollback()
        logger.exception("api_profile update failed")
        return jsonify({"error": "server error"}), 500
