from app.extensions import db
from app.utils.clock import now_local


class TeamSettings(db.Model):
    """Assignment parameters of one manager's team (keyed by manager code)."""
    __tablename__ = "team_settings"

    admin_code = db.Column(db.String(20), primary_key=True)
    buffer_minutes = db.Column(db.Integer, nullable=False, default=3)
    radius_m = db.Column(db.Integer, nullable=False, default=666)
    max_walk_minutes = db.Column(db.Integer, nullable=False, default=8)
    max_break_minutes = db.Column(db.Integer, nullable=False, default=90)


class AuditLog(db.Model):
    """Who did what to whom: password resets, removals, assignments, setting changes."""
    __tablename__ = "audit_log"

    id = db.Column(db.Integer, primary_key=True)
    admin_code = db.Column(db.String(20), nullable=False, index=True)
    at = db.Column(db.DateTime, default=now_local, nullable=False)
    actor = db.Column(db.String(200), nullable=False)
    action = db.Column(db.String(60), nullable=False)
    target = db.Column(db.String(200), nullable=True)
    detail = db.Column(db.String(300), nullable=True)
