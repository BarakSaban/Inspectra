from flask import Blueprint, render_template, redirect, url_for, session

from app.models.user import User
from app.models.inspector import Inspector
from utils.auth_helpers import logged_in, current_role
from app.db_status import DB_AVAILABLE

views_bp = Blueprint("views", __name__)

@views_bp.route('/')
def root():
    if logged_in():
        return redirect('/admin' if current_role() == 'admin' else '/inspect')
    return redirect(url_for('auth.login_get'))

@views_bp.route('/admin')
def admin_dashboard():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('auth.login_get'))
    # If DB is unavailable, clear session and redirect to login (prevents 500s)
    if not DB_AVAILABLE:
        session.pop('user', None)
        session.pop('role', None)
        session.pop('admin_code', None)
        return redirect(url_for('auth.login_get'))

    user = User.query.filter_by(username=session.get('user')).first()

    return render_template(
        'Admin_main_dashboard.html',
        show_sidebar=True,
        show_signout=True,
        user=user,
        admin_code=session.get('admin_code')
    )

@views_bp.route('/analytics')
def analytics_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('auth.login_get'))
    if not DB_AVAILABLE:
        session.pop('user', None)
        session.pop('role', None)
        session.pop('admin_code', None)
        return redirect(url_for('auth.login_get'))

    user = User.query.filter_by(username=session.get('user')).first()

    return render_template(
        'Analytics.html',
        show_sidebar=True,
        show_signout=True,
        user=user,
        admin_code=session.get('admin_code')
    )

@views_bp.route('/sidebar')
def sidebar():
    if "user" not in session:
        return "", 401
    return render_template("sidebar.html", user=session["user"])

@views_bp.route('/staff')
def staff_page():
    if not logged_in() or current_role() != 'admin':
        return redirect(url_for('auth.login_get'))
    if not DB_AVAILABLE:
        session.pop('user', None)
        session.pop('role', None)
        session.pop('admin_code', None)
        return redirect(url_for('auth.login_get'))

    user = User.query.filter_by(username=session.get('user')).first()

    return render_template(
        'staff_managment.html',
        show_sidebar=True,
        show_signout=True,
        user=user,
        admin_code=session.get('admin_code')
    )

@views_bp.route('/profile')
def profile_page():
    if not logged_in():
        return redirect(url_for('auth.login_get'))
    if not DB_AVAILABLE:
        session.pop('user', None)
        session.pop('role', None)
        session.pop('admin_code', None)
        return redirect(url_for('auth.login_get'))

    user = User.query.filter_by(username=session.get('user')).first()

    inspector = None
    if user and user.role == "inspector" and user.inspector_id:
        inspector = Inspector.query.filter_by(inspector_id=user.inspector_id).first()

    return render_template(
        'profile.html',
        show_sidebar=True,
        show_signout=True,
        user=user,
        inspector=inspector,
        role=user.role if user else None,
        inspector_id=user.inspector_id if user else None,
        admin_code=user.manager_code if user else None
    )


@views_bp.route('/inspect')
def inspect_page():
    if not logged_in() or current_role() != 'inspector':
        return redirect(url_for('auth.login_get'))
    if not DB_AVAILABLE:
        session.pop('user', None)
        session.pop('role', None)
        session.pop('inspector_id', None)
        return redirect(url_for('auth.login_get'))

    user = User.query.filter_by(username=session.get('user')).first()

    return render_template(
        'inspector_view.html',
        show_sidebar=False,
        show_signout=True,
        user=user,
        inspector_id=session.get('inspector_id')
    )