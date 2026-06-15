from flask import Blueprint, request, session, redirect, url_for, jsonify, render_template
import random
import string

from app.extensions import db
from app.models.user import User
from app.models.organization import Organization
from app.models.team import Team
from app.models.inspector import Inspector
from utils.auth_helpers import logged_in, get_request_data, is_api_request

auth_bp = Blueprint("auth", __name__)

def generate_code(length=6):
    """Generate a random alphanumeric code."""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length)).upper()


# -------- Auth Routes --------
@auth_bp.route('/login', methods=['GET'])
@auth_bp.route('/access', methods=['GET'])
def login_get():
    """Serve the login/access page."""
    return render_template('acces.html')

@auth_bp.route('/api/login', methods=['POST'])
def api_login():
    """
    Login endpoint. Expects:
      - contact: username or email
      - password: password
    Returns JSON with success, redirect target, and session is set via cookie.
    """
    data = get_request_data() or {}
    contact = (data.get('contact') or data.get('username') or "").strip()
    password = data.get('password')

    if not contact or not password:
        return jsonify({"success": False, "message": "Missing credentials"}), 400

    try:
        user = User.query.filter_by(username=contact).first()
        if not user:
            user = User.query.filter_by(email=contact).first()
        if not user:
            return jsonify({"success": False, "message": "User not found"}), 404

        if not user.check_password(password):
            return jsonify({"success": False, "message": "Invalid password"}), 401

        # Set session
        session.clear()
        session['user'] = user.username
        session['user_id'] = user.id
        session['role'] = user.role
        session['full_name'] = user.full_name or user.username

        # Determine redirect based on role and capture org/team scope
        if user.role == 'org_admin':
            if user.organization_id:
                session['org_id'] = user.organization_id
                org = Organization.query.get(user.organization_id)
                if org:
                    session['org_code'] = org.code
                    session['admin_code'] = org.code
            redirect_target = '/admin'

        elif user.role == 'team_admin':
            teams = user.managed_teams
            if teams:
                team = teams[0]
                session['org_id'] = team.organization_id
                session['org_code'] = team.organization.code
                session['team_id'] = team.id
                session['team_code'] = team.id
                session['admin_code'] = team.organization.code
            redirect_target = '/admin'

        elif user.role == 'inspector':
            if user.teams:
                team = user.teams[0]
                session['org_id'] = team.organization_id
                session['org_code'] = team.organization.code
                session['team_id'] = team.id
                session['team_code'] = team.id
                session['admin_code'] = team.organization.code
            redirect_target = '/inspect'
        else:
            redirect_target = '/'

        session.permanent = False
        if not is_api_request():
            return redirect(redirect_target)
        return jsonify({"success": True, "redirect": redirect_target})
    except Exception as e:
        print("⚠️ api_login error:", e)
        if not is_api_request():
            return redirect(url_for('auth.login_get'))
        return jsonify({"success": False, "message": "Server error"}), 500

@auth_bp.route('/api/register', methods=['POST'])
def api_register():
    """
    Register endpoint. Supports three flows:
      - Create organization: role='org_admin', org_name provided
      - Create team admin inside org: role='team_admin', org_code provided, team_name provided  
      - Join team as inspector: role='inspector', team_code provided
    """
    data = get_request_data() or {}
    email = (data.get('email') or data.get('contact') or "").strip()
    full_name = (data.get('name') or data.get('full_name') or "").strip()
    password = data.get('password')
    role = (data.get('role') or 'inspector').lower()
    
    if not password or not email:
        return jsonify({"success": False, "message": "Missing email or password"}), 400
    
    if len(password) < 6:
        return jsonify({"success": False, "message": "Password must be at least 6 characters"}), 400

    try:
        # Generate unique username from email
        username_base = email.split('@')[0] if '@' in email else email
        username = username_base
        counter = 1
        while User.query.filter_by(username=username).first():
            username = f"{username_base}{counter}"
            counter += 1

        if role == 'org_admin':
            # Create new organization
            org_name = (data.get('org_name') or data.get('organization_name') or "").strip()
            if not org_name:
                return jsonify({"success": False, "message": "Organization name required"}), 400
            
            org_code = generate_code()
            # Ensure code is unique
            for _ in range(100):
                if not Organization.query.filter_by(code=org_code).first():
                    break
                org_code = generate_code()

            # Create org admin user
            user = User(
                username=username,
                email=email,
                full_name=full_name or username,
                role='org_admin',
                manager_code=org_code
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()  # Get user.id

            # Create organization
            org = Organization(
                name=org_name,
                code=org_code,
                admin_id=user.id
            )
            user.organization_id = org.id
            db.session.add(org)
            db.session.commit()

            # Set session
            session.clear()
            session['user'] = user.username
            session['user_id'] = user.id
            session['role'] = 'org_admin'
            session['org_id'] = org.id
            session['org_code'] = org_code
            session['admin_code'] = org_code
            session['full_name'] = user.full_name
            session.permanent = False

            if not is_api_request():
                return redirect('/admin')
            return jsonify({
                "success": True,
                "redirect": "/admin",
                "org_code": org_code
            })

        elif role == 'team_admin':
            # Create team admin in existing org
            org_code = (data.get('org_code') or data.get('manager_code') or "").strip().upper()
            team_name = (data.get('team_name') or "").strip()
            
            if not org_code or not team_name:
                return jsonify({"success": False, "message": "Organization code and team name required"}), 400

            org = Organization.query.filter_by(code=org_code).first()
            if not org:
                return jsonify({"success": False, "message": "Organization not found"}), 404

            # Create team admin user
            user = User(
                username=username,
                email=email,
                full_name=full_name or username,
                role='team_admin',
                manager_code=org.code
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            # Create team
            team = Team(
                name=team_name,
                organization_id=org.id,
                team_admin_id=user.id
            )
            db.session.add(team)
            db.session.commit()

            # Set session
            session.clear()
            session['user'] = user.username
            session['user_id'] = user.id
            session['role'] = 'team_admin'
            session['org_id'] = org.id
            session['org_code'] = org.code
            session['team_id'] = team.id
            session['team_code'] = team.id
            session['admin_code'] = org.code
            session['full_name'] = user.full_name
            session.permanent = False

            if not is_api_request():
                return redirect('/admin')
            return jsonify({
                "success": True,
                "redirect": "/admin",
                "team_code": team.id,
                "org_code": org.code
            })

        elif role == 'inspector':
            # Join team as inspector
            team_code = (data.get('team_code') or data.get('manager_code') or "").strip()
            
            if not team_code:
                return jsonify({"success": False, "message": "Team code required to join"}), 400

            # For now, treat team_code as team ID (simplified)
            team = None
            if team_code.isdigit():
                team = Team.query.filter_by(id=int(team_code)).first()
            
            if not team:
                return jsonify({"success": False, "message": "Team not found"}), 404

            # Create inspector user
            user = User(
                username=username,
                email=email,
                full_name=full_name or username,
                role='inspector'
            )
            user.set_password(password)
            db.session.add(user)
            db.session.flush()

            # Create Inspector record
            inspector_id = f"I{random.randint(1000, 9999)}"
            for _ in range(100):
                if not Inspector.query.filter_by(inspector_id=inspector_id).first():
                    break
                inspector_id = f"I{random.randint(1000, 9999)}"

            inspector = Inspector(
                inspector_id=inspector_id,
                name=full_name or username,
                latitude=32.0853,
                longitude=34.7818,
                available=True
            )
            user.inspector_id = inspector_id
            user.manager_code = team.organization.code
            db.session.add(inspector)

            # Add user to team
            team.users.append(user)
            db.session.commit()

            # Set session
            session.clear()
            session['user'] = user.username
            session['user_id'] = user.id
            session['role'] = 'inspector'
            session['org_id'] = team.organization_id
            session['org_code'] = team.organization.code
            session['team_id'] = team.id
            session['team_code'] = team.id
            session['admin_code'] = team.organization.code
            session['full_name'] = user.full_name
            session.permanent = False

            if not is_api_request():
                return redirect('/inspect')
            return jsonify({
                "success": True,
                "redirect": "/inspect"
            })

        else:
            return jsonify({"success": False, "message": "Invalid role"}), 400

    except Exception as e:
        print("⚠️ api_register error:", e)
        db.session.rollback()
        return jsonify({"success": False, "message": f"Error: {str(e)}"}), 500

@auth_bp.route('/api/logout', methods=['GET', 'POST'])
def api_logout():
    session.clear()
    return jsonify({"success": True, "redirect": "/access"})

@auth_bp.route('/logout', methods=['GET'])
def logout_page():
    session.clear()
    return redirect('/access')
