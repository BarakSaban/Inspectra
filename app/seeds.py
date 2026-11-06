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
    if password == config.DEFAULT_ADMIN_PASSWORD and not config.DEBUG:
        from app.utils.auth import generate_temp_password
        password = generate_temp_password()
        logger.warning("INSPECTRA_ADMIN_PW is not set. The admin account was created with the one-time password %s (change it in Profile).", password)
    elif password == config.DEFAULT_ADMIN_PASSWORD:
        logger.warning("Default admin created with the default password (debug mode only).")
    admin = User(username='admin', role='admin', manager_code=generate_manager_code(), full_name='Admin')
    admin.set_password(password)
    db.session.add(admin)
    db.session.commit()
    logger.info("Default admin user created (username=admin).")


def _add_missing_columns():
    """`create_all` never alters existing tables, so columns added later are added here (older databases keep working)."""
    from sqlalchemy import inspect, text
    additions = {
        "inspector_runs": [("fines_in_progress", "INTEGER NOT NULL DEFAULT 0")],
        "inspectors": [("break_until", "DATETIME"), ("location_updated_at", "DATETIME")],
        "users": [("former_manager_code", "VARCHAR(20)"), ("session_version", "INTEGER NOT NULL DEFAULT 0"),
                  ("approved", "BOOLEAN NOT NULL DEFAULT 1"), ("must_change", "BOOLEAN NOT NULL DEFAULT 0")],
        "team_settings": [("max_break_minutes", "INTEGER NOT NULL DEFAULT 90")],
    }
    inspector = inspect(db.engine)
    for table, columns in additions.items():
        have = {c["name"] for c in inspector.get_columns(table)}
        for name, ddl in columns:
            if name not in have:
                db.session.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
    db.session.commit()


INDEXES = [
    "CREATE INDEX IF NOT EXISTS ix_runs_inspector_status_finished ON inspector_runs (inspector_id, status, finished_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_one_active_per_inspector ON inspector_runs (inspector_id) WHERE status IN ('assigned', 'accepted')",
    "CREATE INDEX IF NOT EXISTS ix_fines_inspector_time ON fines (inspector_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS ix_users_manager_code ON users (manager_code)",
    "CREATE INDEX IF NOT EXISTS ix_users_inspector_id ON users (inspector_id)",
]


def _ensure_indexes():
    """`create_all` does not add indexes to tables that already exist. One failing index (say, old duplicate data) must not stop the rest."""
    from sqlalchemy import text
    for statement in INDEXES:
        try:
            db.session.execute(text(statement))
            db.session.commit()
        except Exception:
            db.session.rollback()
            logger.warning("Could not create index: %s", statement.split(" ON ")[0], exc_info=True)


def bootstrap_database(app_config):
    """Create tables and seed data. A schema failure stops the start; demo seeding failures only log."""
    try:
        db.create_all()
        _add_missing_columns()
        _ensure_indexes()
        seed_admin(app_config["ADMIN_PASSWORD"])
    except Exception:
        logger.exception("DB init/create_all failed")
        db.session.rollback()
        raise   # a half-built schema must stop the start, not hide until the first query

    # Demo data is only inserted into an empty database; INSPECTRA_SEED_DEMO=0 disables it.
    if app_config["SEED_DEMO_DATA"]:
        seed_inspectors()
        seed_fake_data()
