"""The manager's activity feed and an inspector's detail, both derived from the run history (no extra tables)."""
from datetime import timedelta

from sqlalchemy import func

from app.extensions import db
from app.models import Inspector, InspectorRun
from app.utils.clock import now_local


def recent_activity(inspector_ids, limit=30):
    """Latest events of the given inspectors, newest first.

    Each run yields up to three events: `offered` (the manager assigned it), `accepted`, and `completed`/`cancelled`.
    A run an inspector took straight from a recommendation has no separate offer.
    """
    if not inspector_ids:
        return []
    limit = max(1, min(int(limit), 100))
    since = now_local() - timedelta(days=3)
    runs = (
        InspectorRun.query.filter(InspectorRun.inspector_id.in_(inspector_ids), InspectorRun.assigned_at >= since)
        .order_by(InspectorRun.assigned_at.desc()).limit(200).all()
    )
    names = {i.inspector_id: i.name for i in Inspector.query.filter(Inspector.inspector_id.in_(inspector_ids)).all()}
    events = []

    def add(moment, kind, run, **extra):
        if moment is not None:
            events.append({"at": moment, "kind": kind, "run_id": run.id, "inspector_id": run.inspector_id,
                           "name": names.get(run.inspector_id, run.inspector_id), **extra})

    for run in runs:
        manager_assigned = run.accepted_at is None or run.accepted_at != run.assigned_at
        if manager_assigned:
            add(run.assigned_at, "offered", run)
        add(run.accepted_at, "accepted", run)
        if run.status == "completed":
            add(run.finished_at, "completed", run, fines=run.actual_fines or 0)
        elif run.status == "cancelled":
            add(run.finished_at, "cancelled", run, was_accepted=run.accepted_at is not None)

    events.sort(key=lambda e: e["at"], reverse=True)
    now = now_local()
    return [{**e, "at": e["at"].isoformat(), "seconds_ago": max(0, int((now - e["at"]).total_seconds()))} for e in events[:limit]]


def inspector_detail(inspector, days=14, limit=20):
    """Totals, fines per day and the latest runs of one inspector."""
    today = now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=days - 1)
    rows = (
        InspectorRun.query.filter(InspectorRun.inspector_id == inspector.inspector_id, InspectorRun.assigned_at >= since - timedelta(days=1))
        .order_by(InspectorRun.assigned_at.desc()).all()
    )
    per_day = {(since + timedelta(days=i)).date(): 0 for i in range(days)}
    for run in rows:
        if run.status == "completed" and run.finished_at and run.finished_at.date() in per_day:
            per_day[run.finished_at.date()] += run.actual_fines or 0
    totals = db.session.query(
        func.count(InspectorRun.id), func.coalesce(func.sum(InspectorRun.actual_fines), 0), func.coalesce(func.sum(InspectorRun.potential_fines), 0),
    ).filter(InspectorRun.inspector_id == inspector.inspector_id, InspectorRun.status == "completed").one()
    completed, fines, potential = int(totals[0]), int(totals[1]), int(totals[2])
    return {
        "days": [{"date": d.isoformat(), "fines": v} for d, v in per_day.items()],
        "completed_runs": completed,
        "total_fines": fines,
        "efficiency": round(100 * fines / potential) if potential else None,
        "runs": [
            {"id": r.id, "status": r.status, "trip_id": r.trip_id, "stop_id": r.stop_id, "potential_fines": r.potential_fines,
             "actual_fines": r.actual_fines, "assigned_at": r.assigned_at.isoformat() if r.assigned_at else None,
             "finished_at": r.finished_at.isoformat() if r.finished_at else None}
            for r in rows[:limit]
        ],
    }
