from app.extensions import db
from app.utils.clock import now_local


class Inspector(db.Model):
    __tablename__ = "inspectors"

    id = db.Column(db.Integer, primary_key=True)
    inspector_id = db.Column(db.String, unique=True, nullable=False)
    name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    available = db.Column(db.Boolean, default=True)
    total_fines = db.Column(db.Integer, default=0)
    completed_trips = db.Column(db.Integer, default=0)
    last_assignment_completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now_local)
