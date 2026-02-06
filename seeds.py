# seeds.py
import random
from datetime import datetime
import pandas as pd

from app.extensions import db
from app.models import Inspector, InspectorRun, Fine

# Default inspectors list (can be imported from config if preferred)
DEFAULT_INSPECTORS = [
    {"inspector_id": "I001", "name": "Lior Cohen", "latitude": 32.0853, "longitude": 34.7818},
    {"inspector_id": "I002", "name": "Dana Levi", "latitude": 32.1093, "longitude": 34.8555},
    {"inspector_id": "I003", "name": "Amir Ben David", "latitude": 32.0500, "longitude": 34.7667},
    {"inspector_id": "I004", "name": "Noa Shahar", "latitude": 31.9725, "longitude": 34.7890},
    {"inspector_id": "I005", "name": "Yossi Alon", "latitude": 32.2000, "longitude": 34.8833}
]

def seed_inspectors():
    """Seed default inspectors if table is empty."""
    try:
        count = Inspector.query.count()
        if count == 0:
            print("🌱 Seeding default inspectors...")
            for ins in DEFAULT_INSPECTORS:
                kwargs = dict(
                    inspector_id=ins["inspector_id"],
                    name=ins["name"],
                    latitude=ins["latitude"],
                    longitude=ins["longitude"],
                    available=True
                )
                if hasattr(Inspector, 'total_fines'):
                    kwargs['total_fines'] = 0
                if hasattr(Inspector, 'completed_trips'):
                    kwargs['completed_trips'] = 0
                db.session.add(Inspector(**kwargs))
            db.session.commit()
            print("✓ Inspectors seeded.")
        else:
            print("✓ Inspectors already exist — skipping.")
    except Exception as e:
        print("⚠️ seed_inspectors failed:", e)
        db.session.rollback()


def seed_fake_data():
    """Seed fake inspector runs and fines."""
    try:
        runs_count = InspectorRun.query.count()
        fines_count = Fine.query.count()
        if runs_count > 0 or fines_count > 0:
            print("✓ Fake data already exists — skipping.")
            return

        inspectors = Inspector.query.all() or seed_inspectors()
        inspectors = Inspector.query.all()
        print("🌱 Seeding fake runs and fines...")

        for ins in inspectors:
            for _ in range(random.randint(5, 10)):
                days_ago = random.randint(0, 6)
                assigned_at = datetime.now() - pd.Timedelta(days=days_ago, hours=random.randint(0, 23))
                trip_id = f"T{random.randint(1000,9999)}"
                stop_id = f"S{random.randint(100,999)}"
                potential_fines = random.randint(10, 30)
                actual_fines = random.randint(0, potential_fines)

                run = InspectorRun(
                    inspector_id=ins.inspector_id,
                    trip_id=trip_id,
                    stop_id=stop_id,
                    potential_fines=potential_fines,
                    actual_fines=actual_fines,
                    assigned_at=assigned_at,
                    finished_at=assigned_at + pd.Timedelta(hours=1),
                    status="completed"
                )
                db.session.add(run)

                for _ in range(actual_fines):
                    fine = Fine(
                        inspector_id=ins.inspector_id,
                        trip_id=trip_id,
                        stop_id=stop_id,
                        amount=100,
                        timestamp=assigned_at + pd.Timedelta(minutes=random.randint(5, 55))
                    )
                    db.session.add(fine)

        db.session.commit()
        print("✓ Fake data seeded.")

    except Exception as e:
        print("⚠️ seed_fake_data failed:", e)
        db.session.rollback()


def run_all_seeds():
    """Helper to run both seeds inside app context."""
    from run import app  # only import here to avoid circular imports
    with app.app_context():
        seed_inspectors()
        seed_fake_data()
