"""Inspector lookups scoped to an admin (tenant): an admin only ever sees inspectors that carry their manager code."""
from app.models import Inspector, User

# Where a new inspector is placed until they report a position (central Tel Aviv)
DEFAULT_LAT, DEFAULT_LON = 32.0853, 34.7818


def get_admin_inspector_users(admin_code):
    """Inspector user accounts that belong to the admin identified by manager_code."""
    if not admin_code:
        return []
    return User.query.filter_by(role='inspector', manager_code=admin_code).all()


def get_inspector_ids(users):
    return [u.inspector_id for u in users if u.inspector_id]


def get_inspectors_by_id(inspector_ids):
    """inspector_id -> Inspector row, fetched in a single query."""
    if not inspector_ids:
        return {}
    return {i.inspector_id: i for i in Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids)).all()}


def find_owned_inspector(admin_code, inspector_id):
    """(user, inspector) for an inspector owned by this admin, else None. Never crosses admin boundaries."""
    if not admin_code or not inspector_id:
        return None
    user = User.query.filter_by(role='inspector', manager_code=admin_code, inspector_id=inspector_id).first()
    if user is None:
        return None
    inspector = Inspector.query.filter_by(inspector_id=inspector_id).first()
    return (user, inspector) if inspector is not None else None
