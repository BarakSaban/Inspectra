from app.extensions import db
from werkzeug.security import generate_password_hash, check_password_hash

class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # 'org_admin', 'team_admin', 'inspector'
    inspector_id = db.Column(db.String(100), nullable=True)
    full_name = db.Column(db.String(200), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    
    # Backward compat: manager_code stored for orgs created before redesign
    manager_code = db.Column(db.String(20), nullable=True)
    
    # New: explicit org reference for org admins
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=True)
    
    def set_password(self, raw):
        self.password_hash = generate_password_hash(raw)

    def check_password(self, raw):
        return check_password_hash(self.password_hash, raw)

    def __repr__(self):
        return f'<User {self.username} ({self.role})>'
