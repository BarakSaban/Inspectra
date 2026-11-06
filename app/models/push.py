from app.extensions import db
from app.utils.clock import now_local


class PushSubscription(db.Model):
    """One browser or phone that agreed to receive push notifications for an account."""
    __tablename__ = "push_subscriptions"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), nullable=False, index=True)
    endpoint = db.Column(db.String(600), unique=True, nullable=False)
    p256dh = db.Column(db.String(200), nullable=False)
    auth = db.Column(db.String(100), nullable=False)
    lang = db.Column(db.String(5), nullable=False, default="he")
    created_at = db.Column(db.DateTime, default=now_local)
