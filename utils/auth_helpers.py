from flask import session, request
import random
import string
from app.models import Team, User

def logged_in():
    return session.get("user") is not None

def current_role():
    return session.get("role")

def is_admin_role():
    return current_role() in ('admin', 'org_admin', 'team_admin')

def current_inspector_id():
    return session.get("inspector_id")

def get_scoped_inspector_query():
    """Return the inspector user query that matches the current admin scope."""
    org_id = session.get('org_id')
    team_id = session.get('team_id')
    admin_code = session.get('admin_code')

    if current_role() == 'org_admin' and org_id:
        return User.query.filter(User.role == 'inspector', User.teams.any(Team.organization_id == org_id)).distinct()

    if current_role() == 'team_admin' and team_id:
        return User.query.filter(User.role == 'inspector', User.teams.any(Team.id == team_id)).distinct()

    if admin_code:
        return User.query.filter_by(role='inspector', manager_code=admin_code)

    return User.query.filter_by(role='inspector').filter(False)


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
    if request.path.startswith("/api/"):
        if request.method == "POST" and "application/x-www-form-urlencoded" in ctype:
            return False
        return True
    return "application/json" in accept or "application/json" in ctype

def generate_manager_code(length=6):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
