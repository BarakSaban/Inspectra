"""Web Push: wakes an inspector's phone for a new offer or the end of a break, even with the app closed.

Needs a VAPID key pair (`python -m tools.vapid` prints one for `.env`). Without keys push is simply off and the app keeps
its in-page sound and vibration.
"""
import json
import logging
import threading

from app import config
from app.extensions import db
from app.models import PushSubscription, User

logger = logging.getLogger(__name__)

LANGUAGES = ("he", "en", "ar", "ru")
# kind -> language -> (title, body)
MESSAGES = {
    "offer": {
        "he": ("שיבוץ חדש", "פתחו את Inspectra כדי לאשר"),
        "en": ("New assignment", "Open Inspectra to accept it"),
        "ar": ("مهمة جديدة", "افتح Inspectra للموافقة"),
        "ru": ("Новое задание", "Откройте Inspectra, чтобы принять"),
    },
    "break": {
        "he": ("ההפסקה הסתיימה", "חוזרים לעבודה כשאתם מוכנים"),
        "en": ("Break is over", "Back to work when you are ready"),
        "ar": ("انتهت الاستراحة", "عد إلى العمل عندما تكون جاهزاً"),
        "ru": ("Перерыв закончился", "Возвращайтесь к работе, когда будете готовы"),
    },
}


def enabled():
    return bool(config.VAPID_PUBLIC_KEY and config.VAPID_PRIVATE_KEY)


def save_subscription(username, subscription, lang="he"):
    """Remember (or refresh) one browser's push address for this account. Returns False when the data is unusable."""
    endpoint = (subscription or {}).get("endpoint")
    keys = (subscription or {}).get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 600:
        return False
    if not keys.get("p256dh") or not keys.get("auth"):
        return False
    row = PushSubscription.query.filter_by(endpoint=endpoint).first() or PushSubscription(endpoint=endpoint)
    row.username, row.p256dh, row.auth = username, str(keys["p256dh"])[:200], str(keys["auth"])[:100]
    row.lang = lang if lang in LANGUAGES else "he"
    db.session.add(row)
    db.session.commit()
    return True


def remove_subscription(endpoint):
    PushSubscription.query.filter_by(endpoint=endpoint).delete()
    db.session.commit()


def _send(subscriptions, payload_for):
    """Deliver to each subscription; returns the endpoints the push service says are gone."""
    from pywebpush import WebPushException, webpush
    gone = []
    for sub in subscriptions:
        try:
            webpush(
                subscription_info={"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                data=json.dumps(payload_for(sub["lang"])), vapid_private_key=config.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": config.VAPID_SUBJECT}, ttl=120,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                gone.append(sub["endpoint"])
            else:
                logger.warning("push failed (%s): %s", status, exc)
        except Exception:
            logger.exception("push failed")
    return gone


def notify_inspector(inspector_id, kind, url="/inspect"):
    """Push a notification (`offer` or `break`) in each device's language to the person behind `inspector_id`. Never blocks the request."""
    if not enabled() or not inspector_id:
        return
    user = User.query.filter_by(inspector_id=inspector_id).first()
    if user is None:
        return
    subs = [{"endpoint": s.endpoint, "p256dh": s.p256dh, "auth": s.auth, "lang": s.lang or "he"}
            for s in PushSubscription.query.filter_by(username=user.username).all()]
    if not subs:
        return
    def payload_for(lang):
        title, body = MESSAGES[kind][lang if lang in LANGUAGES else "he"]
        return {"title": title, "body": body, "url": url, "tag": kind}

    app = _current_app()

    def work():
        gone = _send(subs, payload_for)
        if gone:
            with app.app_context():
                PushSubscription.query.filter(PushSubscription.endpoint.in_(gone)).delete(synchronize_session=False)
                db.session.commit()

    threading.Thread(target=work, name="push", daemon=True).start()


def schedule_break_end(inspector_id, minutes):
    """Push when a break runs out. A break that was ended or lengthened meanwhile stays quiet (the new end schedules its own)."""
    if not enabled():
        return
    app = _current_app()

    def fire():
        from datetime import timedelta

        from app.models import Inspector
        from app.utils.clock import now_local
        with app.app_context():
            row = Inspector.query.filter_by(inspector_id=inspector_id).first()
            if row is None or row.break_until is None or row.break_until > now_local() + timedelta(seconds=5):
                return
            notify_inspector(inspector_id, "break")

    timer = threading.Timer(max(1, minutes) * 60, fire)
    timer.daemon = True
    timer.start()


def _current_app():
    from flask import current_app
    return current_app._get_current_object()
