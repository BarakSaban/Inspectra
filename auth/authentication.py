from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template
import random

from app.extensions import db
from app.models.user import User
from app.models.inspector import Inspector

from utils.auth_helpers import logged_in, current_role, get_request_data, is_api_request, generate_manager_code

auth_bp = Blueprint("auth", __name__)


# ---------------- Auth routes ----------------
@auth_bp.route('/login', methods=['GET'])
def login_get():
    return render_template('login.html', show_sidebar=False, show_signout=False, error=None)

@auth_bp.route('/signup', methods=['GET'])
def signup_get():
    return render_template('signup.html', show_sidebar=False, show_signout=False, error=None)

# JSON API login
@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    data = get_request_data() or {}
    contact = (data.get('contact') or data.get('username') or "").strip()
    password = data.get('password')

    if not contact or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    try:
        user = User.query.filter_by(username=contact).first()
        if not user:
            user = User.query.filter_by(inspector_id=contact).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"success": False, "message": "Invalid password"}), 401

        session.clear()
        session['user'] = user.username
        session['role'] = user.role
        session['inspector_id'] = user.inspector_id
        session['admin_code'] = user.manager_code
        session.permanent = False

        redirect_target = '/admin' if user.role == 'admin' else '/inspect'
        return jsonify({"success": True, "redirect": redirect_target})
    except Exception as e:
        print("⚠️ api_login error:", e)
        return jsonify({"success": False, "message": "Server error"}), 500

@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    return _register_common()

@auth_bp.route('/register', methods=['POST'])
def register_form():
    return _register_common(allow_redirect=True)

def _register_common(allow_redirect=False):
    data = get_request_data() or {}
    name = (data.get('name') or data.get('full_name') or "").strip()
    email = (data.get('email') or "").strip()
    phone = (data.get('phone') or data.get('phone_number') or "").strip()
    role = (data.get('role') or 'inspector').lower()
    password = data.get('password')
    manager_code_input = data.get("manager_code") or data.get("manager_code_input")

    if not password or not (email or phone or name):
        if allow_redirect and not is_api_request():
            return redirect(url_for('auth.signup_get'))
        return jsonify({"success": False, "message": "Missing required fields"}), 400

    username_candidate = (email or phone or name).strip()
    unique_username = username_candidate
    suffix_try = 0

    try:
        while User.query.filter_by(username=unique_username).first() is not None:
            suffix_try += 1
            unique_username = f"{username_candidate}_{suffix_try}"
            if suffix_try > 200:
                if allow_redirect and not is_api_request():
                    return redirect(url_for('auth.signup_get'))
                return jsonify({"success": False, "message": "Unable to generate username"}), 500

        linked_inspector_id = None

        if role == 'inspector':
            if manager_code_input:
                parent_admin = User.query.filter_by(manager_code=manager_code_input, role='admin').first()
                if not parent_admin:
                    if allow_redirect and not is_api_request():
                        return redirect(url_for('auth.signup_get'))
                    return jsonify({"success": False, "message": "Invalid manager code"}), 400

            if phone and phone.upper().startswith('I'):
                candidate = phone.upper()
                if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                    linked_inspector_id = candidate

            if not linked_inspector_id:
                for _ in range(500):
                    candidate = f"I{random.randint(1000,9999)}"
                    if Inspector.query.filter_by(inspector_id=candidate).first() is None:
                        linked_inspector_id = candidate
                        break

            try:
                if linked_inspector_id and not Inspector.query.filter_by(inspector_id=linked_inspector_id).first():
                    new_ins = Inspector(
                        inspector_id=linked_inspector_id,
                        name=name or unique_username,
                        latitude=32.0853,
                        longitude=34.7818,
                        available=True
                    )
                    if hasattr(Inspector, 'total_fines'):
                        setattr(new_ins, 'total_fines', 0)
                    if hasattr(Inspector, 'completed_trips'):
                        setattr(new_ins, 'completed_trips', 0)
                    db.session.add(new_ins)
                    db.session.commit()
            except Exception as ei:
                print("⚠️ inspector create failed:", ei)
                db.session.rollback()

            new_user = User(
                username=unique_username,
                role=role,
                inspector_id=linked_inspector_id,
                manager_code=manager_code_input,
                full_name=name or unique_username
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

        else:
            for _ in range(500):
                generated_code = generate_manager_code()
                if User.query.filter_by(manager_code=generated_code).first() is None:
                    break

            new_user = User(
                username=unique_username,
                role=role,
                manager_code=generated_code,
                full_name=name or unique_username
            )
            new_user.set_password(password)
            db.session.add(new_user)
            db.session.commit()

            session['admin_code'] = generated_code

        session.clear()
        session['user'] = new_user.username
        session['role'] = new_user.role
        session['inspector_id'] = new_user.inspector_id
        session['admin_code'] = new_user.manager_code
        session.permanent = False

        redirect_target = '/admin' if new_user.role == 'admin' else '/inspect'

        if allow_redirect and not is_api_request():
            return redirect(redirect_target)

        return jsonify({"success": True, "redirect": redirect_target})

    except Exception as e:
        print("⚠️ api_register error:", e)
        db.session.rollback()
        if allow_redirect and not is_api_request():
            return redirect(url_for('auth.signup_get'))
        return jsonify({"success": False, "message": "Server error"}), 500

@auth_bp.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "redirect": "/login"})

@auth_bp.route('/logout')
def logout_page():
    session.clear()
    return redirect(url_for('auth.login_get'))
