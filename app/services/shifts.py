"""Shift and break bookkeeping: when an inspector was really on the job. Feeds the stats pages."""
from app.extensions import db
from app.models import BreakLog, ShiftLog
from app.services.inspectors import is_connected
from app.utils.clock import now_local


def open_shift(inspector_id, at=None):
    if ShiftLog.query.filter_by(inspector_id=inspector_id, ended_at=None).first() is None:
        db.session.add(ShiftLog(inspector_id=inspector_id, started_at=at or now_local()))


def close_shift(inspector_id, at=None):
    for shift in ShiftLog.query.filter_by(inspector_id=inspector_id, ended_at=None).all():
        shift.ended_at = max(shift.started_at, at or now_local())


def reconcile(inspector):
    """Close a shift nobody ended cleanly (manager sent them offline, phone went dark) at the last time we heard from them."""
    if inspector is None:
        return
    running = ShiftLog.query.filter_by(inspector_id=inspector.inspector_id, ended_at=None).first()
    if running is None or is_connected(inspector):
        return
    # Between going online and the first report a shift is legitimately "not connected yet": give it the same grace as the state does.
    heard = inspector.location_updated_at
    if heard is None or heard < running.started_at:
        if inspector.available and (now_local() - running.started_at).total_seconds() <= 180:
            return
        heard = running.started_at
    close_shift(inspector.inspector_id, heard)
    db.session.commit()


def start_break_log(inspector_id, minutes, reason=None):
    end_break_log(inspector_id)
    db.session.add(BreakLog(inspector_id=inspector_id, planned_minutes=minutes, reason=reason if reason in ("lunch", "rest", "other") else None))


def end_break_log(inspector_id, at=None):
    for row in BreakLog.query.filter_by(inspector_id=inspector_id, ended_at=None).all():
        row.ended_at = max(row.started_at, at or now_local())


def current_break(inspector_id):
    return BreakLog.query.filter_by(inspector_id=inspector_id, ended_at=None).order_by(BreakLog.id.desc()).first()
