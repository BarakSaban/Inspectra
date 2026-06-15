import os
import sys
import random
from flask import Flask
from app.extensions import db
from app.models import User, Organization, Team, Inspector
from seeds import seed_fake_data, seed_inspectors

def init_db(app=None):
    if app is None:
        # Create a minimal Flask app for standalone initialization
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get("DATABASE_URL", "sqlite:///inspectra.db")
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
    
    with app.app_context():
        try:
            # Drop all and create fresh with new schema
            db.drop_all()
            db.create_all()

            print("Initializing database with new org/team/inspector hierarchy...")

            # Create a test organization with org_admin
            test_org = Organization(
                name="Egged Transport",
                code="EGGED"
            )
            db.session.add(test_org)
            db.session.flush()  # Get org.id

            # Create org admin user
            org_admin = User(
                username="org_admin@egged.com",
                email="org_admin@egged.com",
                full_name="Egged Organization Admin",
                role="org_admin",
                organization_id=test_org.id
            )
            org_admin.set_password("orgadmin123")
            test_org.admin_id = org_admin.id
            db.session.add(org_admin)
            db.session.flush()

            # Create a team admin for the org
            team_admin = User(
                username="team_admin@egged.com",
                email="team_admin@egged.com",
                full_name="Team Admin - Tel Aviv",
                role="team_admin"
            )
            team_admin.set_password("teamadmin123")
            db.session.add(team_admin)
            db.session.flush()

            # Create a team
            team = Team(
                name="Tel Aviv Inspection Team",
                organization_id=test_org.id,
                team_admin_id=team_admin.id
            )
            db.session.add(team)
            db.session.flush()

            # Create sample inspectors in the team
            for i in range(3):
                inspector_user = User(
                    username=f"inspector{i+1}@egged.com",
                    email=f"inspector{i+1}@egged.com",
                    full_name=f"Inspector {i+1}",
                    role="inspector"
                )
                inspector_user.set_password("inspector123")
                db.session.add(inspector_user)
                db.session.flush()

                # Create Inspector record
                inspector_id = f"I{9000 + i}"
                inspector = Inspector(
                    inspector_id=inspector_id,
                    name=f"Inspector {i+1}",
                    latitude=32.0853 + (i * 0.01),
                    longitude=34.7818 + (i * 0.01),
                    available=True
                )
                inspector_user.inspector_id = inspector_id
                db.session.add(inspector)

                # Add user to team
                team.users.append(inspector_user)

            db.session.commit()

            print("[OK] Database initialized with test data:")
            print("   Organization: EGGED (Egged Transport)")
            print("   Org Admin:")
            print("     - Username: org_admin@egged.com")
            print("     - Password: orgadmin123")
            print("   Team: Tel Aviv Inspection Team")
            print("   Team Admin:")
            print("     - Username: team_admin@egged.com")
            print("     - Password: teamadmin123")
            print("   Inspectors:")
            for i in range(3):
                print(f"     - Username: inspector{i+1}@egged.com")
                print(f"       Password: inspector123")

        except Exception as exc:
            print("[ERROR] Database initialization failed:", exc)
            import traceback
            traceback.print_exc()
            db.session.rollback()
            sys.exit(1)


if __name__ == '__main__':
    init_db()
