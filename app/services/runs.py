"""The life of an inspector's run: assigned -> accepted -> completed (or cancelled).

A run is one trip an inspector takes to check fares. It is created either by an admin assignment (`assigned`, the
inspector must accept) or by the inspector taking a recommendation (`accepted` straight away). Completing a run
records the fines issued and updates the inspector's totals, which is what analytics reads.
"""
from datetime import timedelta

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
from app.services import shifts
from app.services.team import break_cap
from app.utils.clock import now_local

ACTIVE_STATUSES = ("assigned", "accepted")
MAX_FINES_PER_RUN = 500


class RunError(Exception):
    """A rejected run operation; `status` is the HTTP status the API should answer with."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def get_active_run(inspector_id):
    return (
        InspectorRun.query.filter(InspectorRun.inspector_id == inspector_id, InspectorRun.status.in_(ACTIVE_STATUSES))
        .order_by(InspectorRun.assigned_at.desc()).first()
    )


def start_run(inspector_id, trip_id=None, stop_id=None, potential_fines=0):
    """The inspector takes a recommended trip: a new run that is already accepted."""
    if not trip_id:
        raise RunError("trip_id is required")
    fines = _non_negative_int(potential_fines, "potential_fines")
    if get_active_run(inspector_id) is not None:
        raise RunError("finish or cancel your current run first", 409)

    now = now_local()
    run = InspectorRun(
        inspector_id=inspector_id, trip_id=str(trip_id), stop_id=str(stop_id) if stop_id is not None else None,
        potential_fines=fines, assigned_at=now, accepted_at=now, status="accepted",
    )
    db.session.add(run)
    db.session.commit()
    return run


def accept_run(run):
    if run.status != "assigned":
        raise RunError(f"a {run.status} run cannot be accepted", 409)
    run.status = "accepted"
    run.accepted_at = now_local()
    db.session.commit()
    return run


def cancel_run(run):
    if run.status not in ACTIVE_STATUSES:
        raise RunError(f"a {run.status} run cannot be cancelled", 409)
    run.status = "cancelled"
    run.finished_at = now_local()
    db.session.commit()
    return run


def update_progress(run, fines=0):
    """Save the inspector's running fine count so it survives a reload; only an accepted run can change."""
    if run.status != "accepted":
        raise RunError(f"a {run.status} run cannot be updated", 409)
    count = _non_negative_int(fines, "fines")
    if count > MAX_FINES_PER_RUN:
        raise RunError(f"fines cannot exceed {MAX_FINES_PER_RUN}")
    run.fines_in_progress = count
    db.session.commit()
    return run


def complete_run(run, actual_fines=0):
    """Finish an accepted run: store the fines (one Fine row each) and update the inspector's totals."""
    if run.status == "assigned":
        raise RunError("accept the run before completing it", 409)
    if run.status != "accepted":
        raise RunError(f"a {run.status} run cannot be completed", 409)
    fines = _non_negative_int(actual_fines, "actual_fines")
    if fines > MAX_FINES_PER_RUN:
        raise RunError(f"actual_fines cannot exceed {MAX_FINES_PER_RUN}")

    now = now_local()
    run.status = "completed"
    run.actual_fines = fines
    run.finished_at = now
    db.session.add_all(
        Fine(inspector_id=run.inspector_id, run_id=run.id, trip_id=run.trip_id, stop_id=run.stop_id, timestamp=now)
        for _ in range(fines)
    )
    inspector = Inspector.query.filter_by(inspector_id=run.inspector_id).first()
    if inspector is not None:
        inspector.completed_trips = (inspector.completed_trips or 0) + 1
        inspector.total_fines = (inspector.total_fines or 0) + fines
        inspector.last_assignment_completed_at = now
    db.session.commit()
    return run


def serialize_run(run):
    def iso(value):
        return value.isoformat() if value else None

    return {
        "id": run.id, "inspector_id": run.inspector_id, "trip_id": run.trip_id, "stop_id": run.stop_id,
        "potential_fines": run.potential_fines, "actual_fines": run.actual_fines, "status": run.status,
        "fines_in_progress": run.fines_in_progress or 0,
        "assigned_at": iso(run.assigned_at), "accepted_at": iso(run.accepted_at), "finished_at": iso(run.finished_at),
    }


MIN_BREAK_MINUTES = 5
MAX_EXTEND_MINUTES = 60


def _break_state(inspector):
    """(on_break, break_until). An expired break is closed here: the inspector becomes available again."""
    until = inspector.break_until
    if until is None:
        return False, None
    if until > now_local():
        return True, until
    inspector.break_until = None
    inspector.available = True
    shifts.end_break_log(inspector.inspector_id, until)
    shifts.open_shift(inspector.inspector_id, until)
    db.session.commit()
    return False, None


def set_break(inspector, minutes=None, reason=None, extend=None):
    """Start a break of any length from 5 minutes up to the manager's limit, end it (0), or lengthen the running one (`extend`).

    A break makes the inspector unavailable for assignments and is logged for the stats pages.
    """
    iid = inspector.inspector_id
    cap = break_cap(iid)
    if extend is not None:
        try:
            extend = int(extend)
        except (TypeError, ValueError):
            raise RunError("break_extend must be a number")
        log = shifts.current_break(iid)
        if inspector.break_until is None or log is None:     # (a break that just ran out can still be lengthened until the phone returns to work)
            raise RunError("you are not on a break", 409)
        if not 1 <= extend <= MAX_EXTEND_MINUTES:
            raise RunError("break_extend must be between 1 and 60")
        if log.planned_minutes + log.extended_minutes + extend > cap:
            raise RunError("break is longer than your manager allows")
        log.extended_minutes += extend
        inspector.break_until = max(inspector.break_until, now_local()) + timedelta(minutes=extend)
        db.session.commit()
        return inspector
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        raise RunError("break_minutes must be a number")
    if minutes == 0:
        inspector.break_until = None
        inspector.available = True
        shifts.end_break_log(iid)
        shifts.open_shift(iid)
    else:
        if minutes < MIN_BREAK_MINUTES:
            raise RunError("a break must be at least 5 minutes")
        if minutes > cap:
            raise RunError("break is longer than your manager allows")
        if get_active_run(iid) is not None:
            raise RunError("finish or cancel your current run before taking a break", 409)
        shifts.close_shift(iid)
        shifts.start_break_log(iid, minutes, reason)
        inspector.break_until = now_local() + timedelta(minutes=minutes)
        inspector.available = False
    db.session.commit()
    return inspector


def serialize_inspector_summary(inspector):
    """Identity, availability and today's completed runs/fines (local calendar day)."""
    on_break, break_until = _break_state(inspector)
    start_of_day = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    today = InspectorRun.query.filter(
        InspectorRun.inspector_id == inspector.inspector_id,
        InspectorRun.status == "completed",
        InspectorRun.finished_at >= start_of_day,
    ).all()
    return {
        "inspector_id": inspector.inspector_id,
        "name": inspector.name,
        "available": bool(inspector.available),
        "on_break": on_break,
        "break_until": break_until.isoformat() if break_until else None,
        "break_seconds_left": max(0, int((break_until - now_local()).total_seconds())) if break_until else 0,
        "break_planned_minutes": (lambda b: b.planned_minutes + b.extended_minutes if b else None)(shifts.current_break(inspector.inspector_id)) if break_until else None,
        "break_reason": (lambda b: b.reason if b else None)(shifts.current_break(inspector.inspector_id)) if break_until else None,
        "max_break_minutes": break_cap(inspector.inspector_id),
        "today_runs": len(today),
        "today_fines": sum(run.actual_fines or 0 for run in today),
        "total_runs": inspector.completed_trips or 0,
        "total_fines": inspector.total_fines or 0,
    }


def inspector_history(inspector_id, days=7, limit=15):
    """The inspector's own recent work: fines per day for the last `days` days (oldest first) and the latest completed runs."""
    days = max(1, min(int(days), 31))
    today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=days - 1)
    runs_in_range = InspectorRun.query.filter(
        InspectorRun.inspector_id == inspector_id, InspectorRun.status == "completed", InspectorRun.finished_at >= since,
    ).order_by(InspectorRun.finished_at.desc()).all()

    per_day = {(since + timedelta(days=i)).date(): {"rides": 0, "fines": 0} for i in range(days)}
    for run in runs_in_range:
        bucket = per_day.get(run.finished_at.date())
        if bucket is not None:
            bucket["rides"] += 1
            bucket["fines"] += run.actual_fines or 0
    return {
        "days": [{"date": d.isoformat(), **v} for d, v in per_day.items()],
        "rides": [
            {"id": r.id, "trip_id": r.trip_id, "stop_id": r.stop_id, "fines": r.actual_fines or 0,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in runs_in_range[:max(1, min(int(limit), 50))]
        ],
    }


def _non_negative_int(value, name):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise RunError(f"{name} must be a whole number") from None
    if number < 0:
        raise RunError(f"{name} cannot be negative")
    return number
