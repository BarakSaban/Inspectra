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
    latitude = DB.Column(DB.Float, nullable=True)
    longitude = DB.Column(DB.Float, nullable=True)
    available = DB.Column(DB.Boolean, default=True)
    total_fines = DB.Column(DB.Integer, default=0)
    completed_trips = DB.Column(DB.Integer, default=0)
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
    finished_at = DB.Column(DB.DateTime, nullable=True)
    status = DB.Column(DB.String, default="assigned")

print("✅ InspectorRun model defined")
