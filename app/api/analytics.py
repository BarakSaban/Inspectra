import logging
from datetime import date, datetime, time, timedelta

from flask import Blueprint, jsonify, request, session
from sqlalchemy import func

from app.extensions import db
from app.models import Fine, Inspector, InspectorRun
from app.services.inspectors import (
    get_admin_inspector_users,
    get_inspector_ids,
    get_inspectors_by_id,
)
from app.services.runs import ACTIVE_STATUSES
from app.utils.auth import admin_required_api
from app.utils.clock import now_local

logger = logging.getLogger(__name__)

analytics_api = Blueprint("analytics_api", __name__)


@analytics_api.route('/api/analytics')
@admin_required_api
def api_analytics():
    """Summary analytics for the current admin's inspectors only."""
    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400

        users = get_admin_inspector_users(admin_code)
        ids = get_inspector_ids(users)
        inspectors = get_inspectors_by_id(ids)
        now = now_local()
        seven_days_ago = now - timedelta(days=7)

        total_fines = weekly_total = active_inspectors = assigned_inspectors = 0
        avg_completion_min = None
        total_actual = total_potential = 0
        if ids:
            total_fines = db.session.query(func.count(Fine.id)).filter(
                Fine.inspector_id.in_(ids), func.date(Fine.timestamp) == now.date().isoformat()
            ).scalar() or 0
            weekly_total = db.session.query(func.count(Fine.id)).filter(
                Fine.inspector_id.in_(ids), Fine.timestamp >= seven_days_ago
            ).scalar() or 0
            active_inspectors = Inspector.query.filter(Inspector.inspector_id.in_(ids), Inspector.available.is_(True)).count()
            total_actual, total_potential = db.session.query(
                func.coalesce(func.sum(InspectorRun.actual_fines), 0),
                func.coalesce(func.sum(InspectorRun.potential_fines), 0),
            ).filter(InspectorRun.inspector_id.in_(ids)).one()
            assigned_inspectors = db.session.query(func.count(func.distinct(InspectorRun.inspector_id))).filter(
                InspectorRun.inspector_id.in_(ids), InspectorRun.status.in_(ACTIVE_STATUSES)
            ).scalar() or 0
            finished_today = db.session.query(InspectorRun.accepted_at, InspectorRun.finished_at).filter(
                InspectorRun.inspector_id.in_(ids), InspectorRun.status == "completed",
                InspectorRun.accepted_at.isnot(None), func.date(InspectorRun.finished_at) == now.date().isoformat(),
            ).all()
            if finished_today:
                minutes = [(done - started).total_seconds() / 60 for started, done in finished_today]
                avg_completion_min = round(sum(minutes) / len(minutes), 1)

        avg_efficiency = int(total_actual / total_potential * 100) if total_potential > 0 else 0

        inspectors_summary = []
        for user in users:
            inspector = inspectors.get(user.inspector_id)
            inspectors_summary.append({
                "inspector_id": user.inspector_id,
                "name": inspector.name if inspector else (user.full_name or user.username),
                "latitude": inspector.latitude if inspector else None,
                "longitude": inspector.longitude if inspector else None,
                "available": inspector.available if inspector else True,
                "total_fines": inspector.total_fines if inspector else 0,
                "completed_trips": inspector.completed_trips if inspector else 0,
            })

        return jsonify({
            "totalFines": total_fines,
            "weeklyTotal": weekly_total,
            "activeInspectors": active_inspectors,
            "assignedInspectors": assigned_inspectors,
            "unassignedInspectors": len(ids) - assigned_inspectors,
            "avgCompletionMin": avg_completion_min,
            "avgEfficiency": avg_efficiency,
            "inspectors": inspectors_summary,
        })
    except Exception:
        logger.exception("api_analytics failed")
        return jsonify({"error": "server error"}), 500


GRANULARITIES = ("day", "month", "quarter", "year")
MAX_RANGE_DAYS = 366 * 5


def _bucket(day, granularity):
    if granularity == "day":
        return day.isoformat()
    if granularity == "month":
        return f"{day.year}-{day.month:02d}"
    if granularity == "quarter":
        return f"{day.year}-Q{(day.month - 1) // 3 + 1}"
    return str(day.year)


def _bucket_keys(start, end, granularity):
    """Every bucket between two dates, in order, so empty periods show as zero instead of disappearing."""
    keys, cursor = [], start
    while cursor <= end:
        key = _bucket(cursor, granularity)
        if not keys or keys[-1] != key:
            keys.append(key)
        if granularity == "day":
            cursor += timedelta(days=1)
        else:
            step = {"month": 1, "quarter": 3, "year": 12}[granularity]
            month_index = cursor.year * 12 + cursor.month - 1
            if granularity != "month":
                month_index -= (cursor.month - 1) % step  # snap to the start of the quarter/year
            month_index += step
            cursor = date(month_index // 12, month_index % 12 + 1, 1)
    return keys


def _parse_day(value, default):
    if not value:
        return default
    return datetime.strptime(value, "%Y-%m-%d").date()


@analytics_api.route('/api/analytics/report')
@admin_required_api
def api_analytics_report():
    """Fines of the current admin's inspectors between two dates, grouped by hour, weekday and period."""
    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400

        today = now_local().date()
        granularity = request.args.get("granularity", "month")
        try:
            end = _parse_day(request.args.get("end"), today)
            start = _parse_day(request.args.get("start"), end - timedelta(days=89))
        except ValueError:
            return jsonify({"error": "invalid date range"}), 400
        if granularity not in GRANULARITIES or start > end or (end - start).days > MAX_RANGE_DAYS:
            return jsonify({"error": "invalid date range"}), 400

        users = get_admin_inspector_users(admin_code)
        ids = get_inspector_ids(users)
        stamps, per_inspector = [], {}
        if ids:
            rows = db.session.query(Fine.timestamp, Fine.inspector_id).filter(
                Fine.inspector_id.in_(ids),
                Fine.timestamp >= datetime.combine(start, time.min),
                Fine.timestamp < datetime.combine(end + timedelta(days=1), time.min),
            ).all()
            stamps = [row[0] for row in rows if row[0] is not None]
            for stamp, inspector_id in rows:
                if stamp is not None:
                    per_inspector[inspector_id] = per_inspector.get(inspector_id, 0) + 1
        names = {u.inspector_id: (u.full_name or u.username) for u in users}
        leaderboard = sorted(
            ({"inspector_id": i, "name": names.get(i, i), "fines": per_inspector.get(i, 0)} for i in ids),
            key=lambda row: (-row["fines"], row["name"]),
        )

        hourly = [0] * 24
        weekday = [0] * 7  # Sunday first, like the Israeli week
        timeline = dict.fromkeys(_bucket_keys(start, end, granularity), 0)
        for stamp in stamps:
            hourly[stamp.hour] += 1
            weekday[(stamp.weekday() + 1) % 7] += 1
            timeline[_bucket(stamp.date(), granularity)] += 1

        active = Inspector.query.filter(Inspector.inspector_id.in_(ids), Inspector.available.is_(True)).count() if ids else 0
        return jsonify({
            "range": {"start": start.isoformat(), "end": end.isoformat(), "granularity": granularity},
            "totals": {"fines": len(stamps), "inspectors": len(ids), "activeInspectors": active},
            "hourly": hourly,
            "weekday": weekday,
            "timeline": [{"period": key, "fines": count} for key, count in timeline.items()],
            "leaderboard": leaderboard,
        })
    except Exception:
        logger.exception("api_analytics_report failed")
        return jsonify({"error": "server error"}), 500


@analytics_api.route('/api/analytics/insights')
@admin_required_api
def api_analytics_insights():
    """Where and on which lines fines happen, and how this period compares with the one before it."""
    try:
        admin_code = session.get('admin_code')
        if not admin_code:
            return jsonify({"error": "no admin code in session"}), 400
        today = now_local().date()
        try:
            end = _parse_day(request.args.get("end"), today)
            start = _parse_day(request.args.get("start"), end - timedelta(days=29))
        except ValueError:
            return jsonify({"error": "invalid date range"}), 400
        if start > end or (end - start).days > MAX_RANGE_DAYS:
            return jsonify({"error": "invalid date range"}), 400

        ids = get_inspector_ids(get_admin_inspector_users(admin_code))
        span = (end - start).days + 1
        prev_start, prev_end = start - timedelta(days=span), start - timedelta(days=1)

        def window(a, b):
            lo, hi = datetime.combine(a, time.min), datetime.combine(b + timedelta(days=1), time.min)
            return Fine.query.filter(Fine.inspector_id.in_(ids), Fine.timestamp >= lo, Fine.timestamp < hi) if ids else None

        current, previous = window(start, end), window(prev_start, prev_end)
        fines_now = current.count() if current is not None else 0
        fines_before = previous.count() if previous is not None else 0

        by_stop, by_line = {}, {}
        if current is not None:
            for trip_id, stop_id in current.with_entities(Fine.trip_id, Fine.stop_id).all():
                if stop_id:
                    by_stop[str(stop_id)] = by_stop.get(str(stop_id), 0) + 1
                if trip_id:
                    by_line[str(trip_id)] = by_line.get(str(trip_id), 0) + 1

        from app.services.routing import get_engine
        engine = get_engine()
        stops, lines = [], {}
        if engine is not None:
            for stop_id, count in sorted(by_stop.items(), key=lambda kv: -kv[1])[:30]:
                props = ((engine.gtfs.stop_lookup.get(stop_id) or {}).get("properties")) or {}
                if props.get("stop_lat") is not None:
                    stops.append({"stop_id": stop_id, "name": props.get("stop_name"), "latitude": props["stop_lat"],
                                  "longitude": props["stop_lon"], "fines": count})
            for trip_id, count in by_line.items():
                try:
                    label = engine.gtfs.route_label(engine.gtfs.route_id_of(trip_id))
                except Exception:
                    label = None
                if label:
                    lines[str(label)] = lines.get(str(label), 0) + count
        return jsonify({
            "range": {"start": start.isoformat(), "end": end.isoformat(), "previous_start": prev_start.isoformat(), "previous_end": prev_end.isoformat()},
            "fines": fines_now, "previous_fines": fines_before,
            "change_percent": round(100 * (fines_now - fines_before) / fines_before) if fines_before else None,
            "stops": stops, "lines": [{"line": k, "fines": v} for k, v in sorted(lines.items(), key=lambda kv: -kv[1])[:10]],
        })
    except Exception:
        logger.exception("api_analytics_insights failed")
        return jsonify({"error": "server error"}), 500


@analytics_api.route('/api/analytics/people')
@admin_required_api
def api_analytics_people():
    """Per inspector over a date range: fines, rides, hours on shift, hours on break and fines per hour."""
    try:
        admin_code = session.get('admin_code')
        users = get_admin_inspector_users(admin_code)
        ids = get_inspector_ids(users)
        today = now_local().date()
        try:
            end = _parse_day(request.args.get("end"), today)
            start = _parse_day(request.args.get("start"), end - timedelta(days=29))
        except ValueError:
            return jsonify({"error": "invalid date range"}), 400
        if start > end or (end - start).days > MAX_RANGE_DAYS:
            return jsonify({"error": "invalid date range"}), 400
        if not ids:
            return jsonify({"people": []})

        from app.models import BreakLog, ShiftLog
        from app.services.shifts import reconcile
        from app.services.stats import _bounds, _overlap_hours
        lo, hi = _bounds(start, end)
        now = now_local()
        people = get_inspectors_by_id(ids)
        for person in people.values():
            reconcile(person)
        runs = InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids), InspectorRun.status == "completed",
                                         InspectorRun.finished_at >= lo, InspectorRun.finished_at < hi).all()
        shifts = ShiftLog.query.filter(ShiftLog.inspector_id.in_(ids), ShiftLog.started_at < hi).filter(
            (ShiftLog.ended_at.is_(None)) | (ShiftLog.ended_at > lo)).all()
        breaks = BreakLog.query.filter(BreakLog.inspector_id.in_(ids), BreakLog.started_at < hi).filter(
            (BreakLog.ended_at.is_(None)) | (BreakLog.ended_at > lo)).all()
        out = []
        for iid in ids:
            mine_runs = [r for r in runs if r.inspector_id == iid]
            mine_breaks = [b for b in breaks if b.inspector_id == iid]
            fines = sum(r.actual_fines or 0 for r in mine_runs)
            hours = _overlap_hours([s for s in shifts if s.inspector_id == iid], lo, hi, now)
            out.append({
                "inspector_id": iid, "name": people[iid].name if iid in people else iid,
                "fines": fines, "rides": len(mine_runs), "shift_hours": round(hours, 1),
                "break_hours": round(_overlap_hours(mine_breaks, lo, hi, now), 1), "breaks": len(mine_breaks),
                "fines_per_hour": round(fines / hours, 1) if hours >= 0.25 else None,
            })
        out.sort(key=lambda r: -r["fines"])
        return jsonify({"people": out, "range": {"start": start.isoformat(), "end": end.isoformat()}})
    except Exception:
        logger.exception("api_analytics_people failed")
        return jsonify({"error": "server error"}), 500
