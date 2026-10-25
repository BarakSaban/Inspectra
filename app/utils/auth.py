"""Session helpers, access-control decorators and credential generators shared by the web layer."""
import secrets
import string
from functools import wraps

from flask import jsonify, request, session


def logged_in():
    return session.get("user") is not None


def current_role():
    return session.get("role")


def current_inspector_id():
    return session.get("inspector_id")


def login_required_api(view):
    """JSON 401 unless a user is logged in."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in():
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapper


def admin_required_api(view):
    """JSON 401 unless the logged-in user is an admin."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in() or current_role() != 'admin':
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapper


def inspector_required_api(view):
    """JSON 401 unless the logged-in user is an inspector with an inspector record."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not logged_in() or current_role() != 'inspector' or not current_inspector_id():
            return jsonify({"error": "unauthorized"}), 401
        return view(*args, **kwargs)
    return wrapper


def get_request_data():
    """Request payload from JSON or form data. Never the query string: credentials must not travel in URLs."""
    return request.get_json(silent=True) or request.form.to_dict()


def generate_manager_code(length=6):
    # Manager codes gate who can attach inspectors to an admin, so they must be unguessable.
    return ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(length))


def generate_temp_password(length=12):
    return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(length))
