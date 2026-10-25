"""HTML pages. Data for these pages is loaded client-side from the JSON endpoints in `app.api`."""
from flask import Blueprint, redirect, render_template, session, url_for

from app.models import Inspector, User
from app.utils.auth import current_role, logged_in

views_bp = Blueprint("views", __name__)


def _current_user():
    return User.query.filter_by(username=session.get('user')).first()


def _login_redirect():
    return redirect(url_for('views.login_get'))


def _admin_page(template):
    if not logged_in() or current_role() != 'admin':
        return _login_redirect()
    return render_template(template, show_sidebar=True, show_signout=True, user=_current_user(),
                           admin_code=session.get('admin_code'))


@views_bp.route('/')
def root():
    if logged_in():
        return redirect('/admin' if current_role() == 'admin' else '/inspect')
    return _login_redirect()


@views_bp.route('/login')
def login_get():
    return render_template('login.html', show_sidebar=False, show_signout=False, error=None)


@views_bp.route('/signup')
def signup_get():
    return render_template('signup.html', show_sidebar=False, show_signout=False, error=None)


@views_bp.route('/logout')
def logout_page():
    session.clear()
    return _login_redirect()


@views_bp.route('/admin')
def admin_dashboard():
    return _admin_page('admin_dashboard.html')


@views_bp.route('/analytics')
def analytics_page():
    return _admin_page('analytics.html')


@views_bp.route('/staff')
def staff_page():
    return _admin_page('staff_management.html')


@views_bp.route('/profile')
def profile_page():
    if not logged_in():
        return _login_redirect()

    user = _current_user()
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
        admin_code=user.manager_code if user else None,
    )


@views_bp.route('/inspect')
def inspect_page():
    if not logged_in() or current_role() != 'inspector':
        return _login_redirect()
    return render_template('inspector_view.html', show_sidebar=False, show_signout=True,
                           user=_current_user(), inspector_id=session.get('inspector_id'))
