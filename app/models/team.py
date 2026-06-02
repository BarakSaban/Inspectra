from app.extensions import db
from datetime import datetime

class Team(db.Model):
    __tablename__ = "teams"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    organization_id = db.Column(db.Integer, db.ForeignKey('organizations.id'), nullable=False)
    team_admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # team admin
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    team_admin = db.relationship('User', foreign_keys=[team_admin_id], backref='managed_teams')
    users = db.relationship('User', secondary='team_members', backref='teams')

    def __repr__(self):
        return f'<Team {self.name}>'

# Association table for team members
team_members = db.Table(
    'team_members',
    db.Column('team_id', db.Integer, db.ForeignKey('teams.id'), primary_key=True),
    db.Column('user_id', db.Integer, db.ForeignKey('users.id'), primary_key=True)
)
