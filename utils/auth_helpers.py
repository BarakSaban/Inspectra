from flask import session, request
import random
import string

def logged_in():
    return session.get("user") is not None

def current_role():
    return session.get("role")

def current_inspector_id():
    return session.get("inspector_id")

def get_request_data():
    data = request.get_json(silent=True)
    if data:
        return data
    if request.form:
        return request.form.to_dict()
    if request.args:
        return request.args.to_dict()
    return {}

def is_api_request():
    accept = request.headers.get("Accept", "")
    ctype = request.headers.get("Content-Type", "")
    return "application/json" in accept or request.path.startswith("/api/") or "application/json" in ctype

def generate_manager_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
