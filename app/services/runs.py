"""The life of an inspector's run: assigned -> accepted -> completed (or cancelled).

A run is one trip an inspector takes to check fares. It is created either by an admin assignment (`assigned`, the
inspector must accept) or by the inspector taking a recommendation (`accepted` straight away). Completing a run
records the fines issued and updates the inspector's totals, which is what analytics reads.
"""
from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
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
        "assigned_at": iso(run.assigned_at), "accepted_at": iso(run.accepted_at), "finished_at": iso(run.finished_at),
    }


def _non_negative_int(value, name):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise RunError(f"{name} must be a whole number") from None
    if number < 0:
        raise RunError(f"{name} cannot be negative")
    return number
