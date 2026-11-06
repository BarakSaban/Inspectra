"""An inspector's numbers over time: the same payload feeds the inspector's own stats page and the manager's view of them."""
import calendar
from datetime import date, datetime, time, timedelta

from app.models import BreakLog, InspectorRun, ShiftLog
from app.services.shifts import reconcile
from app.utils.clock import now_local

PERIODS = ("today", "week", "month", "year")
MAX_OFFSET = 60
RIDES_SHOWN = 30


def period_range(period, offset=0, today=None):
    """(start_date, end_date inclusive, bucket kind) for the period `offset` steps back from today (0 = current)."""
    today = today or now_local().date()
    if period == "today":
        day = today - timedelta(days=offset)
        return day, day, "hour"
    if period == "week":
        end = today - timedelta(days=7 * offset)
        return end - timedelta(days=6), end, "day"
    if period == "month":
        index = today.year * 12 + today.month - 1 - offset
        year, month = divmod(index, 12)
        month += 1
        return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1]), "day"
    if period == "year":
        year = today.year - offset
        return date(year, 1, 1), date(year, 12, 31), "month"
    raise ValueError("period must be one of today, week, month, year")


def previous_range(period, offset, today=None):
    return period_range(period, offset + 1, today)[:2]


def _bounds(start, end):
    return datetime.combine(start, time.min), datetime.combine(end + timedelta(days=1), time.min)


def _runs(inspector_id, start, end):
    lo, hi = _bounds(start, end)
    return InspectorRun.query.filter(
        InspectorRun.inspector_id == inspector_id, InspectorRun.status == "completed",
        InspectorRun.finished_at >= lo, InspectorRun.finished_at < hi,
    ).order_by(InspectorRun.finished_at.desc()).all()


def _overlap_hours(rows, lo, hi, now):
    total = 0.0
    for row in rows:
        a = row.started_at
        b = row.ended_at or now
        a, b = max(a, lo), min(b, hi)
        if b > a:
            total += (b - a).total_seconds()
    return total / 3600


def _bucket_keys(kind, start, end):
    if kind == "hour":
        return list(range(24))
    if kind == "month":
        return [f"{start.year}-{m:02d}" for m in range(1, 13)]
    return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def _bucket_of(kind, moment):
    if kind == "hour":
        return moment.hour
    if kind == "month":
        return f"{moment.year}-{moment.month:02d}"
    return moment.date().isoformat()


def _streak(inspector_id, today):
    """Consecutive days (ending today, or yesterday if today has no ride yet) with at least one finished ride."""
    since = today - timedelta(days=60)
    days = {r.finished_at.date() for r in _runs(inspector_id, since, today)}
    cursor = today if today in days else today - timedelta(days=1)
    count = 0
    while cursor in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


def inspector_stats(inspector, period="week", offset=0):
    """Totals, change against the previous period, a bucketed series, best moments and the rides of one period."""
    if period not in PERIODS:
        raise ValueError("period must be one of today, week, month, year")
    offset = max(0, min(int(offset), MAX_OFFSET))
    now = now_local()
    today = now.date()
    start, end, kind = period_range(period, offset, today)
    reconcile(inspector)
    runs = _runs(inspector.inspector_id, start, end)
    prev_start, prev_end = previous_range(period, offset, today)
    prev_runs = _runs(inspector.inspector_id, prev_start, prev_end)

    fines = sum(r.actual_fines or 0 for r in runs)
    prev_fines = sum(r.actual_fines or 0 for r in prev_runs)

    buckets = {k: {"key": k, "fines": 0, "rides": 0} for k in _bucket_keys(kind, start, end)}
    by_hour = {h: 0 for h in range(24)}
    for run in runs:
        bucket = buckets.get(_bucket_of(kind, run.finished_at))
        if bucket is not None:
            bucket["fines"] += run.actual_fines or 0
            bucket["rides"] += 1
        by_hour[run.finished_at.hour] += run.actual_fines or 0

    lo, hi = _bounds(start, end)
    shifts = ShiftLog.query.filter(ShiftLog.inspector_id == inspector.inspector_id, ShiftLog.started_at < hi).filter(
        (ShiftLog.ended_at.is_(None)) | (ShiftLog.ended_at > lo)).all()
    breaks = BreakLog.query.filter(BreakLog.inspector_id == inspector.inspector_id, BreakLog.started_at < hi).filter(
        (BreakLog.ended_at.is_(None)) | (BreakLog.ended_at > lo)).all()
    shift_hours = _overlap_hours(shifts, lo, hi, now)
    break_hours = _overlap_hours(breaks, lo, hi, now)

    series = list(buckets.values())
    best_bucket = max(series, key=lambda b: b["fines"], default=None)
    best_hour = max(by_hour, key=by_hour.get) if fines else None
    return {
        "period": period, "offset": offset,
        "range": {"start": start.isoformat(), "end": end.isoformat(), "kind": kind,
                  "previous_start": prev_start.isoformat(), "previous_end": prev_end.isoformat()},
        "totals": {
            "fines": fines, "rides": len(runs),
            "fines_per_ride": round(fines / len(runs), 1) if runs else None,
            "shift_hours": round(shift_hours, 1), "break_hours": round(break_hours, 1),
            "fines_per_hour": round(fines / shift_hours, 1) if shift_hours >= 0.25 else None,
        },
        "previous": {"fines": prev_fines, "rides": len(prev_runs)},
        "change_percent": round(100 * (fines - prev_fines) / prev_fines) if prev_fines else None,
        "series": series,
        "best": {"key": best_bucket["key"] if best_bucket and best_bucket["fines"] else None,
                 "fines": best_bucket["fines"] if best_bucket else 0, "hour": best_hour},
        "streak_days": _streak(inspector.inspector_id, today),
        "rides": [{"id": r.id, "trip_id": r.trip_id, "stop_id": r.stop_id, "fines": r.actual_fines or 0,
                   "finished_at": r.finished_at.isoformat() if r.finished_at else None} for r in runs[:RIDES_SHOWN]],
    }


def inspector_logs(inspector_id, period="week", offset=0):
    """The raw shifts and breaks of a period (for the manager's view of one inspector)."""
    start, end, _ = period_range(period, max(0, min(int(offset), MAX_OFFSET)))
    lo, hi = _bounds(start, end)
    iso = lambda v: v.isoformat() if v else None
    shifts = ShiftLog.query.filter(ShiftLog.inspector_id == inspector_id, ShiftLog.started_at < hi).filter(
        (ShiftLog.ended_at.is_(None)) | (ShiftLog.ended_at > lo)).order_by(ShiftLog.started_at.desc()).limit(30).all()
    breaks = BreakLog.query.filter(BreakLog.inspector_id == inspector_id, BreakLog.started_at < hi).filter(
        (BreakLog.ended_at.is_(None)) | (BreakLog.ended_at > lo)).order_by(BreakLog.started_at.desc()).limit(30).all()
    return {
        "shifts": [{"started_at": iso(r.started_at), "ended_at": iso(r.ended_at)} for r in shifts],
        "breaks": [{"started_at": iso(r.started_at), "ended_at": iso(r.ended_at), "planned_minutes": r.planned_minutes,
                    "extended_minutes": r.extended_minutes, "reason": r.reason} for r in breaks],
    }
