import logging
import random

from flask import Blueprint, jsonify, request, session

from app.extensions import db
from app.models import Inspector, User
from app.services.inspectors import DEFAULT_LAT, DEFAULT_LON
from app.utils.auth import generate_manager_code, get_request_data
from app.utils.ratelimit import login_limiter

logger = logging.getLogger(__name__)

auth_api = Blueprint("auth_api", __name__)

ROLES = ("admin", "inspector")


def _start_session(user):
    """Replace the session with a fresh one for `user` and return the page they land on."""
    session.clear()
    session['user'] = user.username
    session['role'] = user.role
    session['inspector_id'] = user.inspector_id
    session['admin_code'] = user.manager_code
    session.permanent = False
    return '/admin' if user.role == 'admin' else '/inspect'


@auth_api.route('/api/login', methods=['POST'])
def api_login():
    data = get_request_data()
    contact = (data.get('contact') or data.get('username') or "").strip()
    password = data.get('password')

    if not contact or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    attempt_key = (request.remote_addr, contact.lower())
    if login_limiter.blocked(attempt_key):
        return jsonify({"success": False, "message": "Too many failed attempts. Try again later."}), 429

    try:
        user = User.query.filter_by(username=contact).first() or User.query.filter_by(inspector_id=contact).first()
        # One generic answer for unknown user and wrong password, so accounts can not be enumerated.
        if not user or not user.check_password(password):
            login_limiter.record_failure(attempt_key)
            return jsonify({"success": False, "message": "Invalid credentials"}), 401
        login_limiter.reset(attempt_key)
        return jsonify({"success": True, "redirect": _start_session(user)})
    except Exception:
        logger.exception("api_login error")
        return jsonify({"success": False, "message": "Server error"}), 500


def _unique_username(candidate):
    username, attempt = candidate, 0
    while User.query.filter_by(username=username).first() is not None:
        attempt += 1
        if attempt > 200:
            return None
        username = f"{candidate}_{attempt}"
    return username


def _new_inspector_id(preferred):
    """The inspector id the person asked for (a phone starting with 'I'), else a free random one."""
    if preferred and preferred.upper().startswith('I') and not Inspector.query.filter_by(inspector_id=preferred.upper()).first():
        return preferred.upper()
    for _ in range(500):
        candidate = f"I{random.randint(1000, 9999)}"
        if not Inspector.query.filter_by(inspector_id=candidate).first():
            return candidate
    return None


def _new_manager_code():
    for _ in range(500):
        code = generate_manager_code()
        if not User.query.filter_by(manager_code=code).first():
            return code
    return None


@auth_api.route('/api/register', methods=['POST'])
def api_register():
    data = get_request_data()
    name = (data.get('name') or data.get('full_name') or "").strip()
    email = (data.get('email') or "").strip()
    phone = (data.get('phone') or data.get('phone_number') or "").strip()
    role = (data.get('role') or 'inspector').lower()
    password = data.get('password')
    manager_code = data.get("manager_code") or data.get("manager_code_input")

    def fail(message, status):
        return jsonify({"success": False, "message": message}), status

    if not password or not (email or phone or name):
        return fail("Missing required fields", 400)
    if role not in ROLES:
        return fail("Invalid role", 400)

    try:
        username = _unique_username(email or phone or name)
        if username is None:
            return fail("Unable to generate username", 500)
        display_name = name or username

        # The account and (for inspectors) their inspector record are created in one transaction.
        if role == 'inspector':
            if manager_code and not User.query.filter_by(manager_code=manager_code, role='admin').first():
                return fail("Invalid manager code", 400)
            inspector_id = _new_inspector_id(phone)
            if inspector_id:
                db.session.add(Inspector(inspector_id=inspector_id, name=display_name,
                                         latitude=DEFAULT_LAT, longitude=DEFAULT_LON, available=True))
            user = User(username=username, role=role, inspector_id=inspector_id,
                        manager_code=manager_code, full_name=display_name)
        else:
            user = User(username=username, role=role, manager_code=_new_manager_code(), full_name=display_name)

        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        return jsonify({"success": True, "redirect": _start_session(user)})
    except Exception:
        logger.exception("register error")
        db.session.rollback()
        return fail("Server error", 500)


@auth_api.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "redirect": "/login"})
