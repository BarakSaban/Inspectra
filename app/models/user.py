from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(50), nullable=False)
    inspector_id = db.Column(db.String(100), nullable=True)
    manager_code = db.Column(db.String(20), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    former_manager_code = db.Column(db.String(20), nullable=True)  # set while an inspector is deactivated, so the manager can reactivate them

    session_version = db.Column(db.Integer, nullable=False, default=0)   # raised to end every open session of this account
    approved = db.Column(db.Boolean, nullable=False, default=True)       # new managers wait here until the owner approves them
    must_change = db.Column(db.Boolean, nullable=False, default=False)   # a temporary password must be replaced at first use

    @property
    def is_owner(self):
        return self.role == "admin" and self.username == "admin"

    def end_sessions(self):
        self.session_version = (self.session_version or 0) + 1

    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)
