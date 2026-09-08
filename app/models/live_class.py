from datetime import datetime
from app.models import db

class LiveClass(db.Model):
    __tablename__ = 'live_classes'

    id = db.Column(db.Integer, primary_key=True)
    class_id = db.Column(db.String(30), unique=True, nullable=False, index=True) # CRS-CLS-000001
    class_name = db.Column(db.String(150), nullable=False) # COURSECODE-DD-MMM-YYYY-LOCATION-CAMPUS-SESSION
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    
    class_mode = db.Column(db.String(20), nullable=False, default='In Person') # 'In Person', 'Online'
    class_date = db.Column(db.Date, nullable=False)
    
    # In Person fields
    location = db.Column(db.String(100), nullable=True) # e.g. HYD
    branch = db.Column(db.String(100), nullable=True)   # e.g. KPHB
    session_time = db.Column(db.String(50), nullable=True, default='Morning') # 'Morning', 'Evening'
    
    # Online fields
    meet_link = db.Column(db.String(255), nullable=True)
    
    # Common fields
    # Relational facilitator fields
    facilitator_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=False)
    co_facilitator_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=True)
    
    # Legacy columns with defaults to satisfy database-level NOT NULL constraints
    facilitator_name = db.Column(db.String(120), nullable=True, default='')
    co_facilitator_name = db.Column(db.String(120), nullable=True, default='')
    duration_hours = db.Column(db.Float, nullable=False, default=1.0)
    expected_attendance = db.Column(db.Integer, nullable=False, default=30)
    feedback_repo_id = db.Column(db.Integer, db.ForeignKey('feedback_repositories.id'), nullable=True)

    # Class closure state
    is_locked = db.Column(db.Boolean, default=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    unlock_reason = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    facilitator = db.relationship('Learner', foreign_keys=[facilitator_id], backref='facilitated_classes')
    co_facilitator = db.relationship('Learner', foreign_keys=[co_facilitator_id], backref='co_facilitated_classes')
    attendances = db.relationship('Attendance', backref='live_class', lazy=True, cascade='all, delete-orphan')
    enrollments = db.relationship('LearnerEnrollment', backref='live_class', lazy=True)

    @staticmethod
    def generate_class_id():
        last_class = LiveClass.query.order_by(LiveClass.id.desc()).first()
        if not last_class:
            return "CRS-CLS-000001"
        last_num = int(last_class.class_id.split('-')[2])
        return f"CRS-CLS-{last_num + 1:06d}"

    def build_class_name(self, course_code):
        date_str = self.class_date.strftime('%d-%b-%Y').upper()
        if self.class_mode == 'Online':
            loc_str = "ONLINE"
            branch_str = "WEB"
            sess_str = "SESSION"
        else:
            loc_str = (self.location or "HYD").upper()
            branch_str = (self.branch or "MAIN").upper()
            sess_str = (self.session_time or "MORNING").upper()
        
        return f"{course_code.upper()}-{date_str}-{loc_str}-{branch_str}-{sess_str}"

    def __repr__(self):
        return f'<LiveClass {self.class_id} - {self.class_name}>'


class AuditLog(db.Model):
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(50), nullable=False) # 'LiveClass', 'Attendance', etc.
    entity_id = db.Column(db.String(50), nullable=False)
    action = db.Column(db.String(50), nullable=False) # 'UNLOCK', 'MANUAL_ATTENDANCE'
    reason = db.Column(db.Text, nullable=False)
    performed_by = db.Column(db.String(100), nullable=False, default='admin')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<AuditLog {self.action} on {self.entity_type} {self.entity_id}>'
