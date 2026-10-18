from datetime import datetime
from app.extensions import db

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
    assigned_at = db.Column(db.DateTime, default=datetime.now)
    accepted_at = db.Column(db.DateTime, nullable=True)
    finished_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String, default="assigned")
