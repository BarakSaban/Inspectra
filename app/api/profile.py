from flask import Blueprint, jsonify, request, session
from app.extensions import db
from app.models import User, Inspector
from utils.auth_helpers import logged_in, get_request_data
import app.db_status as db_status
from app.fallback import sample_profile

profile_api = Blueprint("profile_api", __name__)

@profile_api.route('/api/profile', methods=['GET', 'POST'])
def api_profile():
    if not logged_in():
        return jsonify({"error": "unauthorized"}), 401

    username = session.get('user')
    if not db_status.DB_AVAILABLE:
        return jsonify(sample_profile(username))
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({"error": "user not found"}), 404

    if request.method == 'GET':
        # Return user details including full_name
        return jsonify({
            "username": user.username,
            "role": user.role,
            "inspector_id": user.inspector_id,
            "manager_code": user.manager_code,
            "full_name": user.full_name
        })

    elif request.method == 'POST':
        data = get_request_data()
        if not data:
            return jsonify({"error": "no data provided"}), 400

        # Allow changing username and password and full_name
        new_username = data.get('username', user.username).strip()
        new_password = data.get('password')
        new_full_name = data.get('full_name')

        # Check uniqueness for username
        if new_username != user.username:
            if User.query.filter_by(username=new_username).first():
                return jsonify({"error": "username already taken"}), 400
            user.username = new_username
            session['user'] = new_username  # update session

        if new_password:
            user.set_password(new_password)

        if new_full_name is not None:
            user.full_name = new_full_name.strip()

        # Optionally allow updating inspector name (if inspector)
        if user.role == "inspector" and user.inspector_id:
            inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()
            if inspector and new_full_name:
                inspector.name = new_full_name.strip()
                db.session.add(inspector)

        try:
            db.session.add(user)
            db.session.commit()
            return jsonify({"success": True, "message": "Profile updated successfully"})
        except Exception as e:
            db.session.rollback()
            print("⚠️ api_profile POST error:", e)
            return jsonify({"error": "server error"}), 500