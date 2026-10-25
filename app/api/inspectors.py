import logging

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun, User
from app.services.inspectors import DEFAULT_LAT, DEFAULT_LON, find_owned_inspector
from app.utils.auth import admin_required_api, generate_temp_password

logger = logging.getLogger(__name__)

inspectors_api = Blueprint("inspectors_api", __name__)


def _serialize(inspector):
    return {
        "inspector_id": inspector.inspector_id,
        "name": inspector.name,
        "email": inspector.email,
        "latitude": inspector.latitude,
        "longitude": inspector.longitude,
        "available": inspector.available,
        "total_fines": inspector.total_fines,
        "completed_trips": inspector.completed_trips,
    }


def _coordinate(value, low, high, default):
    """Parse an optional coordinate; None/'' -> default; raises ValueError when out of range."""
    if value in (None, ""):
        return default
    number = float(value)
    if not low <= number <= high:
        raise ValueError("coordinate out of range")
    return number


def _apply_fields(inspector, data):
    """Copy the editable fields present in `data` onto the inspector. Raises ValueError on bad values."""
    if "name" in data:
        name = (data["name"] or "").strip()
        if not name:
            raise ValueError("name cannot be empty")
        inspector.name = name
    if "email" in data:
        inspector.email = (data["email"] or "").strip() or None
    if "latitude" in data:
        inspector.latitude = _coordinate(data["latitude"], -90, 90, inspector.latitude)
    if "longitude" in data:
        inspector.longitude = _coordinate(data["longitude"], -180, 180, inspector.longitude)
    if "available" in data:
        inspector.available = bool(data["available"])


@inspectors_api.route('/api/inspector', methods=['POST'])
@admin_required_api
def create_inspector():
    admin_code = session.get('admin_code')
    data = request.get_json(silent=True) or {}
    inspector_id = (data.get("inspector_id") or "").strip()
    name = (data.get("name") or "").strip()
    if not inspector_id or not name:
        return jsonify({"error": "inspector_id and name are required"}), 400
    if not admin_code:
        return jsonify({"error": "no admin code in session"}), 400
    if Inspector.query.filter_by(inspector_id=inspector_id).first() or User.query.filter_by(username=inspector_id).first():
        return jsonify({"error": "inspector id already exists"}), 409

    try:
        inspector = Inspector(
            inspector_id=inspector_id,
            name=name,
            latitude=DEFAULT_LAT,
            longitude=DEFAULT_LON,
            available=True,
        )
        _apply_fields(inspector, {k: v for k, v in data.items() if k in ("email", "latitude", "longitude", "available")})

        # The inspector needs an account to belong to this admin; the admin hands over the temporary password.
        temp_password = generate_temp_password()
        user = User(username=inspector_id, role='inspector', inspector_id=inspector_id,
                    manager_code=admin_code, full_name=name)
        user.set_password(temp_password)
        db.session.add_all([inspector, user])
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        logger.exception("create_inspector failed")
        return jsonify({"error": "server error"}), 500

    return jsonify({**_serialize(inspector), "temporary_password": temp_password}), 201


@inspectors_api.route('/api/inspector/<inspector_id>', methods=['GET'])
@admin_required_api
def get_inspector(inspector_id):
    owned = find_owned_inspector(session.get('admin_code'), inspector_id)
    if owned is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(_serialize(owned[1]))


@inspectors_api.route('/api/inspector/<inspector_id>', methods=['PUT'])
@admin_required_api
def update_inspector(inspector_id):
    owned = find_owned_inspector(session.get('admin_code'), inspector_id)
    if owned is None:
        return jsonify({"error": "not found"}), 404
    user, inspector = owned

    try:
        _apply_fields(inspector, request.get_json(silent=True) or {})
        user.full_name = inspector.name
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        return jsonify({"error": str(exc)}), 400
    except Exception:
        db.session.rollback()
        logger.exception("update_inspector failed")
        return jsonify({"error": "server error"}), 500
    return jsonify(_serialize(inspector))


@inspectors_api.route('/api/inspector/<inspector_id>', methods=['DELETE'])
@admin_required_api
def delete_inspector(inspector_id):
    owned = find_owned_inspector(session.get('admin_code'), inspector_id)
    if owned is None:
        return jsonify({"error": "not found"}), 404
    user, inspector = owned

    try:
        has_history = (
            InspectorRun.query.filter_by(inspector_id=inspector_id).first() is not None
            or Fine.query.filter_by(inspector_id=inspector_id).first() is not None
        )
        if has_history:
            # Keep runs/fines for reporting integrity: detach from the admin and take offline instead of deleting.
            user.manager_code = None
            inspector.available = False
            db.session.commit()
            return jsonify({"success": True, "deactivated": True})

        db.session.delete(user)
        db.session.delete(inspector)
        db.session.commit()
    except Exception:
        db.session.rollback()
        logger.exception("delete_inspector failed")
        return jsonify({"error": "server error"}), 500
    return jsonify({"success": True, "deactivated": False})
