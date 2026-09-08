from datetime import datetime
from app.models import db

class Course(db.Model):
    __tablename__ = 'courses'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.String(20), unique=True, nullable=False, index=True) # CRS-000001
    name = db.Column(db.String(150), nullable=False)
    duration_hours = db.Column(db.Float, nullable=False, default=1.0)
    description = db.Column(db.Text, nullable=True)
    mode = db.Column(db.String(20), nullable=False, default='Live') # 'Self Paced', 'Live'
    pass_percentage = db.Column(db.Float, nullable=False, default=80.0)
    feedback_repo_id = db.Column(db.Integer, db.ForeignKey('feedback_repositories.id'), nullable=True)
    has_certificate = db.Column(db.Boolean, nullable=False, default=True)
    thumbnail_filename = db.Column(db.String(255), nullable=True)
    is_sequential = db.Column(db.Boolean, nullable=False, default=True) # Course-level sequential lesson access toggle
    completion_date = db.Column(db.DateTime, nullable=True) # Optional course target completion date
    is_archived = db.Column(db.Boolean, default=False, nullable=False) # Archived status flag
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assessments = db.relationship('CourseAssessment', backref='course', lazy=True, cascade='all, delete-orphan')
    materials = db.relationship('CourseMaterial', backref='course', lazy=True, cascade='all, delete-orphan')
    lessons = db.relationship('CourseLesson', backref='course', lazy=True, cascade='all, delete-orphan')
    classes = db.relationship('LiveClass', backref='course', lazy=True, cascade='all, delete-orphan')
    enrollments = db.relationship('LearnerEnrollment', backref='course', lazy=True, cascade='all, delete-orphan')
    feedback_repository = db.relationship('FeedbackRepository', backref='courses', lazy=True)

    @staticmethod
    def generate_course_id(mode='Self Paced'):
        prefix = 'CRS-SP-'
        if mode == 'Live Online':
            prefix = 'CRS-ON-'
        elif mode in ['Live In Person', 'Live']:
            prefix = 'CRS-IP-'

        all_courses = Course.query.filter(Course.course_id.like(f"{prefix}%")).all()
        max_num = 0
        for c in all_courses:
            parts = c.course_id.split(prefix)
            if len(parts) == 2 and parts[1].isdigit():
                num = int(parts[1])
                if num > max_num:
                    max_num = num

        return f"{prefix}{max_num + 1:03d}"

    def __repr__(self):
        return f'<Course {self.course_id} - {self.name}>'


class CourseAssessment(db.Model):
    __tablename__ = 'course_assessments'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    lesson_id = db.Column(db.Integer, db.ForeignKey('course_lessons.id'), nullable=True) # Optional link to specific lesson
    assessment_type = db.Column(db.String(30), nullable=False) # 'LESSON_PRE', 'LESSON_POST', 'COURSE_END', 'PRE', 'POST'
    serial_number = db.Column(db.Integer, nullable=False, default=1)
    question = db.Column(db.Text, nullable=False)
    option1 = db.Column(db.String(255), nullable=False)
    option2 = db.Column(db.String(255), nullable=False)
    option3 = db.Column(db.String(255), nullable=False)
    option4 = db.Column(db.String(255), nullable=False)
    option5 = db.Column(db.String(255), nullable=True)
    correct_option = db.Column(db.String(50), nullable=False)
    lesson_number = db.Column(db.Integer, nullable=True, default=1)

    def __repr__(self):
        return f'<Assessment Q{self.serial_number} for Course {self.course_id} ({self.assessment_type})>'


class CourseLesson(db.Model):
    __tablename__ = 'course_lessons'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    lesson_number = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(150), nullable=False)
    summary = db.Column(db.Text, nullable=True)
    content = db.Column(db.Text, nullable=True)
    _video_url = db.Column('video_url', db.String(500), nullable=True)

    @property
    def video_url(self):
        if self._video_url:
            return self._video_url
        for cw in self.courseware:
            if cw.courseware_type in ['Video', 'Video File'] and cw.filename:
                from flask import url_for
                return url_for('courses.get_courseware_raw_file', courseware_id=cw.id)
        return None

    @video_url.setter
    def video_url(self, value):
        self._video_url = value
    duration_hours = db.Column(db.Float, nullable=False, default=1.0)
    min_time_minutes = db.Column(db.Float, nullable=False, default=1.0) # Admin minimum required time on courseware
    deadline = db.Column(db.DateTime, nullable=True) # Optional lesson completion deadline
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    courseware = db.relationship('LessonCourseware', backref='lesson', lazy=True, cascade='all, delete-orphan')
    assessments = db.relationship('CourseAssessment', backref='lesson', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<CourseLesson {self.lesson_number}: {self.title}>'


class LessonCourseware(db.Model):
    __tablename__ = 'lesson_courseware'

    id = db.Column(db.Integer, primary_key=True)
    lesson_id = db.Column(db.Integer, db.ForeignKey('course_lessons.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    courseware_type = db.Column(db.String(80), nullable=False, default='Text') # 'Video', 'PDF', 'PPT', 'Text', 'SCORM', 'Google Drive (Google Slides (PPT))'
    filename = db.Column(db.String(255), nullable=True) # Non-downloadable file in uploads/materials
    external_url = db.Column(db.String(500), nullable=True)
    content_text = db.Column(db.Text, nullable=True)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    audio_tracks = db.relationship('CoursewareAudioTrack', backref='courseware', lazy=True, cascade='all, delete-orphan')

    def __repr__(self):
        return f'<LessonCourseware {self.title} ({self.courseware_type})>'


class CoursewareAudioTrack(db.Model):
    __tablename__ = 'courseware_audio_tracks'

    id = db.Column(db.Integer, primary_key=True)
    courseware_id = db.Column(db.Integer, db.ForeignKey('lesson_courseware.id'), nullable=False)
    language_label = db.Column(db.String(50), nullable=False) # e.g. "English", "Telugu", "Hindi", "Tamil"
    audio_filename = db.Column(db.String(255), nullable=False)
    is_default = db.Column(db.Boolean, default=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<CoursewareAudioTrack {self.language_label} for Courseware {self.courseware_id}>'


class CourseMaterial(db.Model):
    __tablename__ = 'course_materials'

    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    material_type = db.Column(db.String(50), nullable=False, default='PDF') # 'Google Drive', 'PDF', 'PPT', 'Video', 'Excel', 'SCORM', 'External Link', 'Document'
    filename = db.Column(db.String(255), nullable=True) # Filename in uploads/materials
    external_url = db.Column(db.String(500), nullable=True) # Optional Google Drive / External URL link
    file_size_str = db.Column(db.String(50), nullable=True, default='N/A')
    allow_download = db.Column(db.Boolean, default=True) # Admin permission toggle: True = Downloadable, False = View-only
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def get_gdrive_info(self):
        from app.services.gdrive_service import parse_gdrive_url
        if self.external_url:
            return parse_gdrive_url(self.external_url)
        return False, '', self.material_type, None

    def __repr__(self):
        return f'<CourseMaterial {self.title} ({self.material_type})>'


class RiseCoursewareVersion(db.Model):
    __tablename__ = 'rise_courseware_version'
    id = db.Column(db.Integer, primary_key=True)
    courseware_id = db.Column(db.Integer, db.ForeignKey('lesson_courseware.id'), nullable=False, index=True)
    version_number = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='Draft') # 'Draft', 'Published'
    blocks_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    courseware = db.relationship('LessonCourseware', backref=db.backref('versions', lazy=True, cascade='all, delete-orphan'))


class LearnerBlockProgress(db.Model):
    __tablename__ = 'learner_block_progress'
    id = db.Column(db.Integer, primary_key=True)
    learner_id = db.Column(db.Integer, db.ForeignKey('learners.id'), nullable=False, index=True)
    courseware_id = db.Column(db.Integer, db.ForeignKey('lesson_courseware.id'), nullable=False, index=True)
    block_id = db.Column(db.String(50), nullable=False)
    is_completed = db.Column(db.Boolean, default=False)
    attempts_count = db.Column(db.Integer, default=0)
    score = db.Column(db.Integer, nullable=True)
    time_spent_seconds = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('learner_id', 'courseware_id', 'block_id', name='uq_learner_block'),
    )

