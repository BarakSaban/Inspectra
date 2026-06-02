from app.extensions import db
from datetime import datetime

class Organization(db.Model):
    __tablename__ = "organizations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    code = db.Column(db.String(20), unique=True, nullable=False)  # unique org identifier
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)  # org admin (nullable initially)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    admin = db.relationship('User', foreign_keys=[admin_id], backref='owned_organizations')
    teams = db.relationship('Team', backref='organization', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Organization {self.code}>'
