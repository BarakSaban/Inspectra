from sqlalchemy import Index, text

from app.extensions import db
from app.utils.clock import now_local


class InspectorRun(db.Model):
    __tablename__ = "inspector_runs"

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(
        db.String,
        db.ForeignKey("inspectors.inspector_id"),
        nullable=False
    )
    trip_id = db.Column(db.String, nullable=False)
    stop_id = db.Column(db.String, nullable=True)
    potential_fines = db.Column(db.Integer, default=0)
    actual_fines = db.Column(db.Integer, nullable=True)
    fines_in_progress = db.Column(db.Integer, nullable=False, default=0, server_default="0")  # live counter during a ride
    assigned_at = db.Column(db.DateTime, default=now_local)
    accepted_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String, default="assigned")

    __table_args__ = (
        Index("ix_runs_inspector_status_finished", "inspector_id", "status", "finished_at"),
        # Two phones tapping at once can not both start a run: the database refuses the second.
        Index("uq_runs_one_active_per_inspector", "inspector_id", unique=True,
              sqlite_where=text("status IN ('assigned', 'accepted')")),
    )
