from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from app.models import db

class AdminUser(db.Model):
    __tablename__ = 'admin_users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, default='admin')
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), default='L&D Administrator')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Learner(db.Model):
    __tablename__ = 'learners'

    id = db.Column(db.Integer, primary_key=True)
    global_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(120), nullable=True)
    profile_picture = db.Column(db.String(255), nullable=True)
    department = db.Column(db.String(100), nullable=True, default='L&D')
    date_of_birth = db.Column(db.Date, nullable=True)
    designation = db.Column(db.String(120), nullable=True)
    location = db.Column(db.String(120), nullable=True)
    branch = db.Column(db.String(120), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=True, index=True)
    points = db.Column(db.Integer, nullable=False, default=0, index=True)
    current_streak = db.Column(db.Integer, nullable=False, default=0)
    last_active_date = db.Column(db.Date, nullable=True)
    theme = db.Column(db.String(50), nullable=False, default='navy')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    subordinates = db.relationship('Learner', backref=db.backref('manager', remote_side=[id]), lazy=True)
    enrollments = db.relationship('LearnerEnrollment', backref='learner', lazy=True, cascade='all, delete-orphan')
    attendances = db.relationship('Attendance', backref='learner', lazy=True, cascade='all, delete-orphan')
    certificates = db.relationship('Certificate', backref='learner', lazy=True, cascade='all, delete-orphan')
    badges = db.relationship('LearnerBadge', backref='learner', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<Learner {self.global_id} - {self.name}>'

