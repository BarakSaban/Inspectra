# my_models_final.py
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

print("✅ Loading my_models_final.py started")

DB = SQLAlchemy()
print("✅ DB object created")

class Inspector(DB.Model):
    __tablename__ = "inspectors"
    id = DB.Column(DB.Integer, primary_key=True)
    inspector_id = DB.Column(DB.String, unique=True, nullable=False)
    name = DB.Column(DB.String, nullable=False)
    email = DB.Column(DB.String, nullable=True)
    latitude = DB.Column(DB.Float, nullable=True)
    longitude = DB.Column(DB.Float, nullable=True)
    available = DB.Column(DB.Boolean, default=True)
    total_fines = DB.Column(DB.Integer, default=0)
    completed_trips = DB.Column(DB.Integer, default=0)
    last_assignment_completed_at = DB.Column(DB.DateTime, nullable=True)
    created_at = DB.Column(DB.DateTime, default=datetime.utcnow)

print("✅ Inspector model defined")

class InspectorRun(DB.Model):
    __tablename__ = "inspector_runs"
    id = DB.Column(DB.Integer, primary_key=True)
    inspector_id = DB.Column(DB.String, DB.ForeignKey("inspectors.inspector_id"), nullable=False)
    trip_id = DB.Column(DB.String, nullable=False)
    stop_id = DB.Column(DB.String, nullable=True)
    potential_fines = DB.Column(DB.Integer, default=0)
    actual_fines = DB.Column(DB.Integer, nullable=True)
    assigned_at = DB.Column(DB.DateTime, default=datetime.utcnow)
    accepted_at = DB.Column(DB.DateTime, nullable=True)
    finished_at = DB.Column(DB.DateTime, nullable=True)
    status = DB.Column(DB.String, default="assigned")  # assigned, accepted, completed, canceled

print("✅ InspectorRun model defined")

class Fine(DB.Model):
    __tablename__ = "fines"
    id = DB.Column(DB.Integer, primary_key=True)
    inspector_id = DB.Column(DB.String, DB.ForeignKey("inspectors.inspector_id"), nullable=False)
    run_id = DB.Column(DB.Integer, DB.ForeignKey("inspector_runs.id"), nullable=True)
    trip_id = DB.Column(DB.String, nullable=True)
    stop_id = DB.Column(DB.String, nullable=True)
    count = DB.Column(DB.Integer, default=0)  # number of fines in this record
    amount = DB.Column(DB.Float, default=0.0)  # total money collected for this record
    timestamp = DB.Column(DB.DateTime, default=datetime.utcnow)

print("✅ Fine model defined")
