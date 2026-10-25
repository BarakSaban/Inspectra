"""Database bootstrap: tables, the default admin and (optionally) demo inspectors/runs/fines for an empty database."""
import logging
import random
from datetime import timedelta

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun, User
from app.utils.auth import generate_manager_code
from app.utils.clock import now_local

logger = logging.getLogger(__name__)

# Demo inspectors for an empty database
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
            logger.info("Seeding default inspectors...")
            for ins in DEFAULT_INSPECTORS:
                db.session.add(Inspector(
                    inspector_id=ins["inspector_id"],
                    name=ins["name"],
                    latitude=ins["latitude"],
                    longitude=ins["longitude"],
                    available=True,
                    total_fines=0,
                    completed_trips=0,
                ))
            db.session.commit()
            logger.info("Inspectors seeded.")
    except Exception:
        logger.exception("seed_inspectors failed")
        db.session.rollback()


def seed_fake_data():
    """Seed fake inspector runs and fines."""
    try:
        runs_count = InspectorRun.query.count()
        fines_count = Fine.query.count()
        if runs_count > 0 or fines_count > 0:
            return

        inspectors = Inspector.query.all()
        logger.info("Seeding fake runs and fines...")

        for ins in inspectors:
            for _ in range(random.randint(5, 10)):
                days_ago = random.randint(0, 6)
                assigned_at = now_local() - timedelta(days=days_ago, hours=random.randint(0, 23))
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
                    finished_at=assigned_at + timedelta(hours=1),
                    status="completed"
                )
                db.session.add(run)

                for _ in range(actual_fines):
                    fine = Fine(
                        inspector_id=ins.inspector_id,
                        trip_id=trip_id,
                        stop_id=stop_id,
                        amount=100,
                        timestamp=assigned_at + timedelta(minutes=random.randint(5, 55))
                    )
                    db.session.add(fine)

        db.session.commit()
        logger.info("Fake data seeded.")

    except Exception:
        logger.exception("seed_fake_data failed")
        db.session.rollback()


def seed_admin(password):
    """Create the default admin account (username `admin`) if it does not exist."""
    if User.query.filter_by(username='admin').first():
        return
    from app import config
    if password == config.DEFAULT_ADMIN_PASSWORD:
        logger.warning("Default admin created with the default password. Set INSPECTRA_ADMIN_PW and change it.")
    admin = User(username='admin', role='admin', manager_code=generate_manager_code(), full_name='Admin')
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    logger.info("Default admin user created (username=admin).")


def bootstrap_database(app_config):
    """Create tables and seed data. A failure is logged and never prevents the app from starting."""
    try:
        db.create_all()
        seed_admin(app_config["ADMIN_PASSWORD"])
    except Exception:
        logger.exception("DB init/create_all failed")
        db.session.rollback()
        return

    # Demo data is only inserted into an empty database; INSPECTRA_SEED_DEMO=0 disables it.
    if app_config["SEED_DEMO_DATA"]:
        seed_inspectors()
        seed_fake_data()
