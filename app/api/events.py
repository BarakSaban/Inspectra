"""Server-sent events: a tiny "something changed" signal so pages refresh at once instead of waiting for the next poll.

The stream carries no data, only the news that the caller's picture (a manager's team, an inspector's run) changed;
the page then re-reads the normal JSON endpoints. Pages keep their polling as a fallback, so a dropped stream costs nothing.
Each open stream holds one worker thread: run the app with a threaded server (the dev server and gunicorn `--worker-class gthread` are).
"""
import hashlib
import threading
import time

from flask import Blueprint, Response, jsonify, request, session, stream_with_context

from app.extensions import db
from app.models import Inspector, InspectorRun
from app.services.inspectors import get_admin_inspector_users, get_inspector_ids
from app.utils.auth import current_inspector_id, current_role, logged_in

events_api = Blueprint("events_api", __name__)

POLL_SECONDS = 2.0        # how often the server looks for a change
KEEPALIVE_SECONDS = 15.0  # comment lines keep proxies from closing an idle stream
MAX_STREAMS_PER_USER = 4  # one per open tab; stops a runaway page from tying up every worker thread
_open_streams = {}
_streams_lock = threading.Lock()
MAX_STREAM_SECONDS = 55   # the browser reconnects by itself; short streams free threads and pick up deploys


def signature(role, inspector_id=None, admin_code=None):
    """A short fingerprint of everything the caller's pages show; it changes whenever any of it does."""
    db.session.expire_all()
    if role == "admin":
        ids = get_inspector_ids(get_admin_inspector_users(admin_code))
    else:
        ids = [inspector_id] if inspector_id else []
    if not ids:
        return "empty"
    runs = (InspectorRun.query.filter(InspectorRun.inspector_id.in_(ids))
            .order_by(InspectorRun.id.desc()).limit(30).all())
    people = Inspector.query.filter(Inspector.inspector_id.in_(ids)).order_by(Inspector.inspector_id).all()
    parts = [f"{r.id}:{r.status}:{r.fines_in_progress}" for r in runs]
    parts += [f"{p.inspector_id}:{p.available}:{p.break_until}:{p.location_updated_at}" for p in people]
    return hashlib.md5("|".join(parts).encode()).hexdigest()


@events_api.route('/api/events')
def events():
    if not logged_in() or current_role() not in ("admin", "inspector"):
        return jsonify({"error": "unauthorized"}), 401
    role, inspector_id, admin_code = current_role(), current_inspector_id(), session.get('admin_code')
    try:
        limit = min(float(request.args.get("max_seconds", MAX_STREAM_SECONDS)), MAX_STREAM_SECONDS)
    except ValueError:
        return jsonify({"error": "max_seconds must be a number"}), 400

    who = session.get('user')
    with _streams_lock:
        if _open_streams.get(who, 0) >= MAX_STREAMS_PER_USER:
            return jsonify({"error": "too many requests"}), 429
        _open_streams[who] = _open_streams.get(who, 0) + 1

    @stream_with_context
    def stream():
        try:
            yield "retry: 3000\n\n"
            last = signature(role, inspector_id, admin_code)
            started = last_beat = time.monotonic()
            while time.monotonic() - started < limit:
                time.sleep(min(POLL_SECONDS, max(0.01, limit)))
                current = signature(role, inspector_id, admin_code)
                if current != last:
                    last = current
                    yield "event: change\ndata: 1\n\n"
                elif time.monotonic() - last_beat > KEEPALIVE_SECONDS:
                    last_beat = time.monotonic()
                    yield ": keepalive\n\n"
        finally:
            with _streams_lock:
                _open_streams[who] = max(0, _open_streams.get(who, 1) - 1)

    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
