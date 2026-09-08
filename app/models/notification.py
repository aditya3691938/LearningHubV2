from datetime import datetime
from app.models import db

class LearnerNotification(db.Model):
    __tablename__ = 'learner_notifications'

    id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=False)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('course_lessons.id'), nullable=True)

    title = db.Column(db.String(255), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=False, default='COURSE_ASSIGNED') # 'COURSE_ASSIGNED', 'LESSON_UPDATED', 'ASSESSMENT_UNLOCKED'
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    image_path = db.Column(db.String(255), nullable=True)

    learner = db.relationship('Learner', backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))
    course = db.relationship('Course', backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))
    lesson = db.relationship('CourseLesson', backref=db.backref('notifications', lazy=True, cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<LearnerNotification {self.notification_type} for Learner {self.learner_id}>'
