from datetime import datetime
from app.extensions import db

class Fine(db.Model):
    __tablename__ = "fines"

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(
        db.String,
        db.ForeignKey("inspectors.inspector_id"),
        nullable=False
    )
    run_id = db.Column(
        db.Integer,
        db.ForeignKey("inspector_runs.id"),
        nullable=True
    )
    trip_id = db.Column(db.String, nullable=True)
    stop_id = db.Column(db.String, nullable=True)
    count = db.Column(db.Integer, default=0)
    amount = db.Column(db.Float, default=0.0)
    timestamp = db.Column(db.DateTime, default=datetime.now)
