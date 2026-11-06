from app.extensions import db
from app.utils.clock import now_local


class ShiftLog(db.Model):
    """One stretch of being online. `ended_at` is empty while the shift is running."""
    __tablename__ = "shift_log"

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String(50), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=now_local, nullable=False)
    ended_at = db.Column(db.DateTime, nullable=True)


class BreakLog(db.Model):
    """One break: how long it was meant to be, why, and when it really ended."""
    __tablename__ = "break_log"

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String(50), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=now_local, nullable=False)
    planned_minutes = db.Column(db.Integer, nullable=False)
    extended_minutes = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(20), nullable=True)   # lunch | rest | other
    ended_at = db.Column(db.DateTime, nullable=True)
