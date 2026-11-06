"""Per-team assignment settings and the audit trail of sensitive manager actions."""
from app.extensions import db
from app.models import AuditLog, TeamSettings
from app.utils.clock import now_local

DEFAULTS = {"buffer_minutes": 3, "radius_m": 666, "max_walk_minutes": 8, "max_break_minutes": 90}
LIMITS = {"buffer_minutes": (0, 30), "radius_m": (100, 2000), "max_walk_minutes": (1, 20), "max_break_minutes": (15, 180)}
AUDIT_KEEP = 500


def get_settings(admin_code):
    row = db.session.get(TeamSettings, admin_code) if admin_code else None
    return {key: getattr(row, key) if row else default for key, default in DEFAULTS.items()}


def update_settings(admin_code, values):
    """Validate and store the given settings; raises ValueError naming the bad field."""
    clean = {}
    for key, (low, high) in LIMITS.items():
        if key not in values:
            continue
        try:
            number = int(values[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be a number")
        if not low <= number <= high:
            raise ValueError(f"{key} must be between {low} and {high}")
        clean[key] = number
    row = db.session.get(TeamSettings, admin_code) or TeamSettings(admin_code=admin_code, **DEFAULTS)
    for key, number in clean.items():
        setattr(row, key, number)
    db.session.add(row)
    db.session.commit()
    return get_settings(admin_code)


def audit(admin_code, actor, action, target=None, detail=None):
    """Append an audit entry (committed with the caller's transaction) and keep the log bounded."""
    if not admin_code:
        return
    db.session.add(AuditLog(admin_code=admin_code, actor=str(actor or "?"), action=action, target=target, detail=(detail or None)))
    db.session.commit()
    stale = (AuditLog.query.filter_by(admin_code=admin_code).order_by(AuditLog.id.desc()).offset(AUDIT_KEEP).all())
    if stale:
        for row in stale:
            db.session.delete(row)
        db.session.commit()


def recent_audit(admin_code, limit=50):
    now = now_local()
    rows = AuditLog.query.filter_by(admin_code=admin_code).order_by(AuditLog.id.desc()).limit(max(1, min(int(limit), 200))).all()
    return [{"id": r.id, "at": r.at.isoformat(), "seconds_ago": max(0, int((now - r.at).total_seconds())), "actor": r.actor,
             "action": r.action, "target": r.target, "detail": r.detail} for r in rows]


def break_cap(inspector_id):
    """The longest single break this inspector's manager allows (the default when they have no manager)."""
    from app.models import User
    user = User.query.filter_by(inspector_id=inspector_id).first()
    return get_settings(user.manager_code if user else None)["max_break_minutes"]
