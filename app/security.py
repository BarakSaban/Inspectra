"""Request guards that apply to every route: same-origin check for state changes, live session validation,
forced password change, security headers and JSON error bodies for the API."""
from urllib.parse import urlparse

from flask import g, jsonify, redirect, request, session

from app import config
from app.models import User

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}
# What a person who must still change a temporary password may reach.
PASSWORD_CHANGE_OK = ("/profile", "/api/profile", "/api/logout", "/logout", "/static/", "/api/login")

CSP = "; ".join([
    "default-src 'self'",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' data: https://fonts.gstatic.com",
    "img-src 'self' data: blob: https:",
    "connect-src 'self' https://*.tile.openstreetmap.org",
    "worker-src 'self'",
    "manifest-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])


def is_deactivated(user):
    """Deactivated inspectors keep their history but are detached from their manager."""
    return user.role == "inspector" and user.manager_code is None and user.former_manager_code is not None


def session_valid(user):
    """A cookie is only as good as the account behind it: changes made on the server end old sessions at once."""
    if user is None or session.get("role") != user.role:
        return False
    if session.get("sv", 0) != (user.session_version or 0):
        return False
    return user.approved is not False and not is_deactivated(user)


def same_origin():
    """Browsers always send Origin on cross-site writes; refuse the ones that do not come from this site."""
    origin = request.headers.get("Origin")
    if origin:
        if urlparse(origin).netloc == request.host:
            return True
        return origin in config.CORS_ORIGINS
    return request.headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")


def init_security(app):
    @app.before_request
    def guard():
        if request.method in MUTATING and not same_origin():
            return jsonify({"error": "cross-site request refused"}), 403

        g.user = None
        username = session.get("user")
        if not username or request.path.startswith("/static/"):
            return None
        user = User.query.filter_by(username=username).first()
        if not session_valid(user):
            session.clear()
            return None
        g.user = user
        if session.get("admin_code") != user.manager_code:
            session["admin_code"] = user.manager_code   # e.g. after the manager replaced the invite code
        if user.must_change and not request.path.startswith(PASSWORD_CHANGE_OK):
            if request.path.startswith("/api/"):
                return jsonify({"error": "password_change_required"}), 403
            return redirect("/profile")
        return None

    @app.after_request
    def headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(self), camera=(), microphone=()")
        if response.mimetype == "text/html":
            response.headers.setdefault("Content-Security-Policy", CSP)
        if request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response
