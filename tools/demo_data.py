"""Demo accounts and history stored in the real database, easy to remove again.

Usage (from the repository root):
    python -m tools.demo_data create [--days 45]   add two managers, their inspectors and past shifts, breaks, rides and fines
    python -m tools.demo_data status               list the demo accounts and what they own
    python -m tools.demo_data live                 keep four demo inspectors online (fresh position every 30 s) until Ctrl-C
    python -m tools.demo_data delete [--yes]       remove everything this tool created (shows counts first, asks unless --yes)

Everything it makes is recognisable: usernames start with `demo.` and inspector ids with `DM`. Real accounts are never
touched. Rides use real trips and stops from the GTFS timetable, so lines and stop names show correctly. The database is
the one the app uses (INSPECTRA_DB_PATH, default `inspectra.db`).
"""
import argparse
import random
import sys
import time
from datetime import datetime, time as dtime, timedelta

from app import create_app
from app.extensions import db
from app.models import AuditLog, BreakLog, Fine, Inspector, InspectorRun, ShiftLog, TeamSettings, User
from app.services.gtfs import get_gtfs
from app.services.team import DEFAULTS
from app.utils.auth import generate_manager_code
from app.utils.clock import now_local

PASSWORD = "demo1234"
USER_PREFIX = "demo."
ID_PREFIX = "DM"
FINE_AMOUNT = 100

MANAGERS = [
    {"username": "demo.manager1", "name": "מירי הדר", "max_break": 90,
     "inspectors": ["דנה לוי", "יוסי כהן", "נועה שחר", "אמיר בן דוד", "ליאור מזרחי", "רוני אלון"]},
    {"username": "demo.manager2", "name": "עומר ביטון", "max_break": 60,
     "inspectors": ["מיכל גולן", "אורי פרץ", "תמר אביב"]},
]
# Around central Tel Aviv, where the SIRI feed has live buses.
AREA = (32.04, 32.12, 34.76, 34.82)


def _is_demo_user(user):
    return user.username.startswith(USER_PREFIX)


def _demo_users():
    return User.query.filter(User.username.like(f"{USER_PREFIX}%")).all()


def _demo_inspector_ids():
    return [i.inspector_id for i in Inspector.query.filter(Inspector.inspector_id.like(f"{ID_PREFIX}%")).all()]


def _new_code():
    while True:
        code = generate_manager_code()
        if not User.query.filter_by(manager_code=code).first():
            return code


def _stop_pool(gtfs):
    """Real stops inside the demo area that have plenty of service, with a few trips each."""
    south, north, west, east = AREA
    stops = gtfs.stops
    inside = stops[(stops["stop_lat"].between(south, north)) & (stops["stop_lon"].between(west, east))]
    pool = []
    for _, row in inside.iterrows():
        frame = gtfs.stop_times_by_stop.get(row["stop_id"])
        if frame is None or len(frame) < 8:
            continue
        pool.append({"stop_id": str(row["stop_id"]), "lat": float(row["stop_lat"]), "lon": float(row["stop_lon"]),
                     "trips": [str(t) for t in frame["trip_id"].unique()[:30]]})
    return pool


def create(days):
    if _demo_users():
        print("Demo data already exists. Run `delete` first if you want to rebuild it.")
        return 1
    gtfs = get_gtfs()
    if gtfs is None:
        print("The GTFS timetable could not be loaded.")
        return 1
    pool = _stop_pool(gtfs)
    if not pool:
        print("No stops with service found in the demo area.")
        return 1
    rng = random.Random(2026)
    now = now_local()
    counter = 0
    accounts = []

    for spec in MANAGERS:
        code = _new_code()
        manager = User(username=spec["username"], role="admin", manager_code=code, full_name=spec["name"])
        manager.set_password(PASSWORD)
        db.session.add(manager)
        settings = dict(DEFAULTS, max_break_minutes=spec["max_break"])
        db.session.add(TeamSettings(admin_code=code, **settings))
        db.session.add(AuditLog(admin_code=code, at=now - timedelta(days=3), actor=spec["username"], action="settings_changed",
                                detail=f"max_break_minutes={spec['max_break']}"))
        accounts.append((spec["username"], "manager", spec["name"], code))

        for name in spec["inspectors"]:
            counter += 1
            inspector_id = f"{ID_PREFIX}{counter:02d}"
            home = rng.choice(pool)
            username = f"{USER_PREFIX}i{counter:02d}"
            db.session.add(Inspector(inspector_id=inspector_id, name=name, available=False, latitude=home["lat"], longitude=home["lon"],
                                     location_updated_at=None, total_fines=0, completed_trips=0))
            user = User(username=username, role="inspector", inspector_id=inspector_id, manager_code=code, full_name=name)
            user.set_password(PASSWORD)
            db.session.add(user)
            accounts.append((username, "inspector", name, inspector_id))
            db.session.add(AuditLog(admin_code=code, at=now - timedelta(days=days - 1), actor=spec["username"],
                                    action="inspector_created", target=inspector_id))
            _history(rng, pool, inspector_id, days, now)
            db.session.flush()
    db.session.commit()

    # Totals on the inspector rows follow the rides just created.
    for inspector in Inspector.query.filter(Inspector.inspector_id.like(f"{ID_PREFIX}%")).all():
        runs = InspectorRun.query.filter_by(inspector_id=inspector.inspector_id, status="completed").all()
        inspector.completed_trips = len(runs)
        inspector.total_fines = sum(r.actual_fines or 0 for r in runs)
        inspector.last_assignment_completed_at = max((r.finished_at for r in runs), default=None)
    db.session.commit()

    print(f"Created {len(accounts)} accounts, password for all of them: {PASSWORD}\n")
    for username, role, name, extra in accounts:
        print(f"  {role:<9} {username:<15} {name:<14} {'manager code ' if role == 'manager' else 'inspector id '}{extra}")
    print("\nThey are offline with history only. `python -m tools.demo_data live` keeps some online; log in as an inspector to go online for real.")
    return 0


def _history(rng, pool, inspector_id, days, now):
    """Finished shifts, a break most days and the rides done in between; nothing that is still running."""
    skill = rng.uniform(0.6, 1.5)
    for ago in range(days, -1, -1):
        day = (now - timedelta(days=ago)).date()
        if day.weekday() == 5 or rng.random() < 0.2:   # Saturday and the odd day off
            continue
        start = datetime.combine(day, dtime(rng.randint(6, 9), rng.choice((0, 15, 30, 45))))
        end = start + timedelta(hours=rng.uniform(6, 9))
        if ago == 0:
            end = min(end, now - timedelta(minutes=20))
        if end - start < timedelta(hours=1.5):
            continue
        db.session.add(ShiftLog(inspector_id=inspector_id, started_at=start, ended_at=end))

        taken = []
        if end - start > timedelta(hours=5):
            minutes = rng.choice((30, 45, 60))
            b_start = start + timedelta(hours=rng.uniform(3.5, 4.5))
            if b_start + timedelta(minutes=minutes) < end:
                db.session.add(BreakLog(inspector_id=inspector_id, started_at=b_start, planned_minutes=minutes,
                                        extended_minutes=rng.choice((0, 0, 0, 10)), reason="lunch",
                                        ended_at=b_start + timedelta(minutes=minutes)))
                taken.append((b_start, b_start + timedelta(minutes=minutes + 10)))
        if rng.random() < 0.3:
            r_start = start + timedelta(hours=rng.uniform(1.5, 2.5))
            db.session.add(BreakLog(inspector_id=inspector_id, started_at=r_start, planned_minutes=15,
                                    reason=rng.choice(("rest", "other")), ended_at=r_start + timedelta(minutes=15)))
            taken.append((r_start, r_start + timedelta(minutes=15)))

        cursor = start + timedelta(minutes=rng.randint(10, 40))
        for _ in range(rng.randint(3, 7)):
            duration = timedelta(minutes=rng.randint(18, 40))
            for busy_from, busy_to in taken:
                if cursor < busy_to and cursor + duration > busy_from:
                    cursor = busy_to + timedelta(minutes=5)
            if cursor + duration > end:
                break
            spot = rng.choice(pool)
            potential = rng.randint(4, 14)
            fines = max(0, min(potential + 2, round(rng.gauss(potential * 0.55 * skill, 2.5))))
            run = InspectorRun(inspector_id=inspector_id, trip_id=rng.choice(spot["trips"]), stop_id=spot["stop_id"],
                               potential_fines=potential, actual_fines=fines, assigned_at=cursor - timedelta(minutes=4),
                               accepted_at=cursor - timedelta(minutes=3), finished_at=cursor + duration, status="completed")
            db.session.add(run)
            db.session.flush()
            for _ in range(fines):
                db.session.add(Fine(inspector_id=inspector_id, run_id=run.id, trip_id=run.trip_id, stop_id=run.stop_id, amount=FINE_AMOUNT,
                                    timestamp=cursor + timedelta(minutes=rng.randint(2, max(3, int(duration.total_seconds() // 60) - 2)))))
            cursor += duration + timedelta(minutes=rng.randint(8, 30))


def status():
    users = _demo_users()
    if not users:
        print("No demo data in this database.")
        return 0
    for user in sorted(users, key=lambda u: (u.role != "admin", u.username)):
        extra = f"manager code {user.manager_code}" if user.role == "admin" else f"{user.inspector_id}, team {user.manager_code}"
        print(f"  {user.role:<9} {user.username:<15} {user.full_name:<14} {extra}")
    ids = _demo_inspector_ids()
    print(f"\n{len(ids)} inspectors, {InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids)).count()} rides, "
          f"{Fine.query.filter(Fine.inspector_id.in_(ids)).count()} fines, password {PASSWORD}")
    return 0


def delete(assume_yes):
    users = _demo_users()
    ids = _demo_inspector_ids()
    codes = [u.manager_code for u in users if u.role == "admin" and u.manager_code]
    # Real inspectors attached to a demo manager would lose their team: refuse rather than orphan them.
    strays = User.query.filter(User.role == "inspector", User.manager_code.in_(codes or [""]), ~User.username.like(f"{USER_PREFIX}%")).count()
    if strays:
        print(f"{strays} real inspector(s) belong to a demo manager. Move or remove them first; nothing was deleted.")
        return 1
    counts = {
        "accounts": len(users), "inspectors": len(ids),
        "rides": InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids)).count(),
        "fines": Fine.query.filter(Fine.inspector_id.in_(ids)).count(),
        "shifts": ShiftLog.query.filter(ShiftLog.inspector_id.in_(ids)).count(),
        "breaks": BreakLog.query.filter(BreakLog.inspector_id.in_(ids)).count(),
        "team settings and audit entries": TeamSettings.query.filter(TeamSettings.admin_code.in_(codes)).count() + AuditLog.query.filter(AuditLog.admin_code.in_(codes)).count(),
    }
    if not users and not ids:
        print("No demo data in this database.")
        return 0
    print("This will delete: " + ", ".join(f"{n} {k}" for k, n in counts.items()))
    if not assume_yes and input("Type 'delete' to continue: ").strip() != "delete":
        print("Nothing deleted.")
        return 1
    Fine.query.filter(Fine.inspector_id.in_(ids)).delete(synchronize_session=False)
    InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids)).delete(synchronize_session=False)
    ShiftLog.query.filter(ShiftLog.inspector_id.in_(ids)).delete(synchronize_session=False)
    BreakLog.query.filter(BreakLog.inspector_id.in_(ids)).delete(synchronize_session=False)
    AuditLog.query.filter(AuditLog.admin_code.in_(codes)).delete(synchronize_session=False)
    TeamSettings.query.filter(TeamSettings.admin_code.in_(codes)).delete(synchronize_session=False)
    Inspector.query.filter(Inspector.inspector_id.in_(ids)).delete(synchronize_session=False)
    User.query.filter(User.username.like(f"{USER_PREFIX}%")).delete(synchronize_session=False)
    db.session.commit()
    print("Demo data removed.")
    return 0


def live(count=4):
    """Stand-in for phones: keep a few demo inspectors available with a fresh position until stopped."""
    ids = _demo_inspector_ids()[:count]
    if not ids:
        print("No demo inspectors. Run `create` first.")
        return 1
    gtfs = get_gtfs()
    pool = _stop_pool(gtfs) if gtfs is not None else []
    rng = random.Random()
    print(f"Keeping {', '.join(ids)} online. Ctrl-C to stop (they go offline again).")
    from app.services.shifts import close_shift, open_shift
    try:
        while True:
            for inspector in Inspector.query.filter(Inspector.inspector_id.in_(ids)).all():
                if not inspector.available:
                    inspector.available = True
                    open_shift(inspector.inspector_id)
                if pool and rng.random() < 0.15:
                    spot = rng.choice(pool)
                    inspector.latitude, inspector.longitude = spot["lat"], spot["lon"]
                inspector.location_updated_at = now_local()
            db.session.commit()
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        db.session.rollback()
        for inspector in Inspector.query.filter(Inspector.inspector_id.in_(ids)).all():
            inspector.available = False
            close_shift(inspector.inspector_id)
        db.session.commit()
        print("\nDemo inspectors are offline again.")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("create")
    make.add_argument("--days", type=int, default=45)
    sub.add_parser("status")
    sub.add_parser("live")
    remove = sub.add_parser("delete")
    remove.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Hebrew names on a Windows console

    app = create_app()
    with app.app_context():
        if args.command == "create":
            return create(max(7, min(args.days, 120)))
        if args.command == "status":
            return status()
        if args.command == "live":
            return live()
        return delete(args.yes)


if __name__ == "__main__":
    sys.exit(main())
