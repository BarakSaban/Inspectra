import os
import sys
from run import app
from app.extensions import db
from app.models import User
from seeds import seed_fake_data, seed_inspectors
from utils.auth_helpers import generate_manager_code


def init_db():
    with app.app_context():
        try:
            db.create_all()

            if not User.query.filter_by(username='admin').first():
                admin_user = User(
                    username='admin',
                    role='admin',
                    manager_code=generate_manager_code(),
                    full_name='Admin'
                )
                admin_user.set_password(
                    os.environ.get('INSPECTRA_ADMIN_PW', 'admin')
                )
                db.session.add(admin_user)
                db.session.commit()
                print('✅ Default admin user created (username=admin).')

            seed_inspectors()
            seed_fake_data()
            print('✅ Database initialization complete.')
        except Exception as exc:
            print('⚠️ Database initialization failed:', exc)
            db.session.rollback()
            sys.exit(1)


if __name__ == '__main__':
    init_db()
