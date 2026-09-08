import os
import datetime
import random
from datetime import timedelta
from app.models import db
from app.models.user import AdminUser, Learner
from app.models.issue import LmsIssue
from app.models.course import Course, CourseAssessment, CourseMaterial, CourseLesson
from app.models.live_class import LiveClass
from app.models.enrollment import LearnerEnrollment
from app.models.feedback import FeedbackRepository, FeedbackQuestion

def init_db_and_seed(app):
    """Initializes database tables, executes schema migrations if required, and seeds initial demo data."""
    with app.app_context():
        try:
            db.create_all()
        except Exception as e:
            db.session.rollback()
            print(f"db.create_all notice: {e}")

        # Safe schema column additions for SQLite compatibility
        alter_statements = [
            "ALTER TABLE learners ADD COLUMN email VARCHAR(120);",
            "ALTER TABLE learners ADD COLUMN profile_picture VARCHAR(255);",
            "ALTER TABLE learners ADD COLUMN date_of_birth DATE;",
            "ALTER TABLE course_lessons ADD COLUMN duration_hours FLOAT DEFAULT 1.0;",
            "ALTER TABLE course_lessons ADD COLUMN min_time_minutes FLOAT DEFAULT 1.0;",
            "ALTER TABLE courses ADD COLUMN feedback_repo_id INTEGER;",
            "ALTER TABLE courses ADD COLUMN has_certificate BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE courses ADD COLUMN thumbnail_filename VARCHAR(255);",
            "ALTER TABLE courses ADD COLUMN is_sequential BOOLEAN DEFAULT TRUE;",
            "ALTER TABLE courses ADD COLUMN completion_date DATETIME;",
            "ALTER TABLE course_lessons ADD COLUMN deadline DATETIME;",
            "ALTER TABLE course_materials ADD COLUMN description TEXT;",
            "ALTER TABLE learners ADD COLUMN manager_id INTEGER;",
            "ALTER TABLE learner_enrollments ADD COLUMN extended_deadline DATETIME;",
            "ALTER TABLE learner_enrollments ADD COLUMN extension_requested BOOLEAN DEFAULT FALSE;",
            "ALTER TABLE live_classes ADD COLUMN facilitator_id INTEGER;",
            "ALTER TABLE live_classes ADD COLUMN co_facilitator_id INTEGER;",
            "ALTER TABLE learners ADD COLUMN points INTEGER DEFAULT 0;",
            "ALTER TABLE learners ADD COLUMN current_streak INTEGER DEFAULT 0;",
            "ALTER TABLE learners ADD COLUMN last_active_date DATE;",
            "ALTER TABLE learners ADD COLUMN designation VARCHAR(120);",
            "ALTER TABLE learners ADD COLUMN location VARCHAR(120);",
            "ALTER TABLE learners ADD COLUMN branch VARCHAR(120);",
            "ALTER TABLE learner_notifications ADD COLUMN course_id INTEGER;",
            "ALTER TABLE learner_notifications ADD COLUMN lesson_id INTEGER;",
            "ALTER TABLE learning_wall_posts ALTER COLUMN badge_color TYPE VARCHAR(255);",
            "ALTER TABLE learners ADD COLUMN theme VARCHAR(50) DEFAULT 'navy';",
            "ALTER TABLE courses ADD COLUMN is_archived BOOLEAN DEFAULT FALSE;"
        ]

        for stmt in alter_statements:
            try:
                db.session.execute(db.text(stmt))
                db.session.commit()
            except Exception:
                db.session.rollback()

        os.makedirs(os.path.join(app.root_path, '..', 'uploads', 'thumbnails'), exist_ok=True)

        admin = AdminUser.query.filter_by(username='admin').first()
        
        # Clear existing data if requested or if seeding brand new
        if not admin or Learner.query.count() < 10:
            print("Database missing initial seed. Seeding initial data...")
            
            # Reset tables cleanly
            try:
                LmsIssue.query.delete()
                LearnerEnrollment.query.delete()
                LiveClass.query.delete()
                CourseMaterial.query.delete()
                CourseAssessment.query.delete()
                CourseLesson.query.delete()
                Course.query.delete()
                FeedbackQuestion.query.delete()
                FeedbackRepository.query.delete()
                Learner.query.delete()
                AdminUser.query.delete()
                db.session.commit()
            except Exception as reset_err:
                db.session.rollback()
                print(f"Clean notice: {reset_err}")

            if not admin:
                admin = AdminUser(username='admin')
                admin.set_password('admin')
                db.session.add(admin)

            # 1. Seed 120 Learner Records
            departments = ['L&D Academics', 'Mathematics Faculty', 'Physics Department', 'Chemistry Department', 'L&D Operations', 'Computer Science Faculty', 'Engineering Faculty']
            locations = ['Hyderabad', 'Bangalore', 'Chennai', 'Pune']
            branches = {
                'Hyderabad': ['Madhapur', 'Nallagandla', 'Kondapur', 'Gachibowli'],
                'Bangalore': ['Whitefield', 'Electronic City', 'Koramangala'],
                'Chennai': ['Adyar', 'Velachery', 'OMR'],
                'Pune': ['Hinjewadi', 'Viman Nagar']
            }
            designations = ['Lecturer', 'Senior Lecturer', 'Assistant Professor', 'Associate Professor', 'Manager', 'Academic Coordinator', 'Instructional Designer']

            first_names = ['Rajesh', 'Priya', 'Anil', 'Sneha', 'Vikram', 'Amit', 'Sunita', 'Rohan', 'Karan', 'Neha', 'Deepak', 'Divya', 'Sanjay', 'Meera', 'Vijay', 'Aarav', 'Ananya', 'Rahul', 'Kavita', 'Siddharth']
            last_names = ['Kumar', 'Sharma', 'Reddy', 'Patel', 'Verma', 'Gupta', 'Rao', 'Singh', 'Nair', 'Iyer', 'Joshi', 'Chawla', 'Deshmukh', 'Pillai', 'Bose', 'Sen', 'Mehta', 'Prasad']

            # Learner 1 (Rajesh Kumar, global_id='10001', the manager)
            manager_learner = Learner(
                global_id='10001',
                name='Rajesh Kumar',
                department='L&D Academics',
                designation='Academic Director',
                location='Hyderabad',
                branch='Madhapur',
                points=150,
                current_streak=5,
                last_active_date=datetime.date.today(),
                theme='navy'
            )
            db.session.add(manager_learner)
            db.session.commit()

            learners = [manager_learner]
            for i in range(2, 121):
                loc = random.choice(locations)
                br = random.choice(branches[loc])
                global_id = str(10000 + i)
                name = f"{random.choice(first_names)} {random.choice(last_names)}"
                
                # About 40% of learners report to Learner 1
                manager_id = manager_learner.id if random.random() < 0.4 else None
                
                l = Learner(
                    global_id=global_id,
                    name=name,
                    department=random.choice(departments),
                    designation=random.choice(designations),
                    location=loc,
                    branch=br,
                    manager_id=manager_id,
                    points=random.randint(10, 500),
                    current_streak=random.randint(0, 10),
                    last_active_date=datetime.date.today() - timedelta(days=random.randint(0, 5)),
                    theme='navy'
                )
                db.session.add(l)
                learners.append(l)
            db.session.commit()
            print(f"Successfully seeded {len(learners)} learner records.")

            # 2. Setup standard feedback survey
            fb_repo = FeedbackRepository(title='Standard L&D Session Feedback Survey', description='Facilitation & Course Quality Feedback')
            db.session.add(fb_repo)
            db.session.commit()

            q1 = FeedbackQuestion(repo_id=fb_repo.id, question_text='How would you rate the course content quality?', question_type='MCQ', options_json='["Excellent", "Good", "Average", "Poor"]')
            q2 = FeedbackQuestion(repo_id=fb_repo.id, question_text='Was the facilitator engaging and clear?', question_type='MCQ', options_json='["Strongly Agree", "Agree", "Neutral", "Disagree"]')
            q3 = FeedbackQuestion(repo_id=fb_repo.id, question_text='What key learnings will you apply in your role?', question_type='Text')
            db.session.add_all([q1, q2, q3])
            db.session.commit()

            # 3. Seed 10 Self-Paced Courses with Youtube content
            self_paced_courses = [
                ("Python Basics & Programming Fundamentals", "Learn variables, loops, lists, dictionary and basic scripting using Python 3.", "https://www.youtube.com/embed/kqtD5dpn9C8"),
                ("Data Structures & Algorithms with Python", "Covering sorting, searching, binary search trees, and dynamic programming.", "https://www.youtube.com/embed/8hly31xKjhc"),
                ("Web Development Fundamentals (HTML & CSS)", "Build modern responsive websites using semantic elements and flexbox.", "https://www.youtube.com/embed/DpSp2Tkh7tA"),
                ("Modern JavaScript Masterclass (ES6+)", "Understand callbacks, promises, async/await, closures and modern arrow expressions.", "https://www.youtube.com/embed/W6NZfCO5SIk"),
                ("Introduction to SQL & Databases", "Write queries, execute inner/outer joins, and perform transactional aggregates.", "https://www.youtube.com/embed/HXV3zeQKqGY"),
                ("Git & GitHub Version Control Essentials", "Learn commit logs, branch structures, pull requests, merge conflict resolutions.", "https://www.youtube.com/embed/RGOj5yH7evk"),
                ("Cybersecurity & OWASP Top 10 Security Risks", "Protect applications from SQL Injection, XSS, CSRF, and authentication flaws.", "https://www.youtube.com/embed/nLU_0Bf1Ulg"),
                ("Docker Containers for Beginners", "Write Dockerfiles, build images, configure ports, and orchestrate with Docker Compose.", "https://www.youtube.com/embed/fqMOX6JJhGo"),
                ("REST API Design with Flask", "Build robust APIs, configure route blueprints, parse inputs, and output JSON.", "https://www.youtube.com/embed/qbLc5a9JDgA"),
                ("Introduction to Machine Learning & Data Science", "Data preprocessing, linear regression, decision trees, and model evaluation.", "https://www.youtube.com/embed/GwIo3gDZUtQ")
            ]

            seeded_sp_courses = []
            for idx, (title, desc, yt_url) in enumerate(self_paced_courses, 1):
                course_id = f"CRS-SP-{idx:03d}"
                c = Course(
                    course_id=course_id,
                    name=title,
                    duration_hours=float(random.randint(3, 8)),
                    description=desc,
                    mode="Self Paced",
                    pass_percentage=80.0,
                    feedback_repo_id=fb_repo.id,
                    has_certificate=True
                )
                db.session.add(c)
                db.session.commit()
                seeded_sp_courses.append(c)

                # Seed 3 lessons per course
                les1 = CourseLesson(course_id=c.id, lesson_number=1, title="Introduction & Getting Started", video_url=yt_url, duration_hours=1.0)
                les2 = CourseLesson(course_id=c.id, lesson_number=2, title="Deep Dive & Core Concepts", video_url="https://www.youtube.com/embed/kqtD5dpn9C8", duration_hours=1.0)
                les3 = CourseLesson(course_id=c.id, lesson_number=3, title="Advanced Hands-on Exercises", video_url="https://www.youtube.com/embed/8hly31xKjhc", duration_hours=1.0)
                db.session.add_all([les1, les2, les3])
                db.session.commit()

                # Add assessments: Pre (PRE), Lesson 3 Post (LESSON_POST), Course End (COURSE_END)
                pre_ass = CourseAssessment(
                    course_id=c.id, assessment_type='PRE', serial_number=1,
                    question=f"Which option represents the core focus of {title}?",
                    option1="Primary goal", option2="Secondary goal", option3="Unrelated topic", option4="None of the above",
                    correct_option="Option1"
                )
                
                les3_post = CourseAssessment(
                    course_id=c.id, lesson_id=les3.id, assessment_type='LESSON_POST', serial_number=1,
                    question="Which mitigation or practice solves the core hands-on exercise?",
                    option1="Data escaping", option2="Rebooting host", option3="Leaving open access", option4="None",
                    correct_option="Option1"
                )
                
                end_ass1 = CourseAssessment(
                    course_id=c.id, assessment_type='COURSE_END', serial_number=1,
                    question="What is the general best practice recommended at the end of the course?",
                    option1="Continuous monitoring", option2="Complete deletion", option3="Manual backups only", option4="Ignorance",
                    correct_option="Option1"
                )
                end_ass2 = CourseAssessment(
                    course_id=c.id, assessment_type='COURSE_END', serial_number=2,
                    question="Which layer evaluates the final completion matrix?",
                    option1="Core logic validation", option2="Presentation shell", option3="Database log", option4="None",
                    correct_option="Option1"
                )
                db.session.add_all([pre_ass, les3_post, end_ass1, end_ass2])
                db.session.commit()

            print("Successfully seeded 10 self-paced courses with lessons and assessments.")

            # 4. Seed Live Online Courses (3 total)
            live_online_courses = [
                ("Microservices & Cloud Native Architectures", "Live online class focusing on distributed systems design."),
                ("Advanced Android App Design with Jetpack Compose", "Virtual workshop for composing reactive layouts."),
                ("React 19 & Next.js App Router Masterclass", "Live coding sessions covering SSR, ISR, and dynamic streaming.")
            ]

            seeded_online_courses = []
            for idx, (title, desc) in enumerate(live_online_courses, 1):
                course_id = f"CRS-ON-{idx:03d}"
                c = Course(
                    course_id=course_id,
                    name=title,
                    duration_hours=6.0,
                    description=desc,
                    mode="Live Online",
                    pass_percentage=80.0,
                    feedback_repo_id=fb_repo.id,
                    has_certificate=True
                )
                db.session.add(c)
                db.session.commit()
                seeded_online_courses.append(c)

                # Create live class session scheduled for future days
                cls_date = datetime.date.today() + timedelta(days=idx + 1)
                cls = LiveClass(
                    class_id=f"CLS-ONL-{idx:03d}",
                    class_name=f"{course_id}-{cls_date.strftime('%d-%b-%Y')}-VIRTUAL",
                    course_id=c.id,
                    class_mode="Online",
                    class_date=cls_date,
                    location="Online Virtual",
                    branch="Google Meet",
                    session_time="Evening",
                    meet_link=f"https://meet.google.com/abc-def{idx}-hij",
                    facilitator_id=manager_learner.id,
                    duration_hours=4.0,
                    expected_attendance=30,
                    feedback_repo_id=fb_repo.id
                )
                db.session.add(cls)
                db.session.commit()

                # Add Pre/Post assessments
                pre = CourseAssessment(course_id=c.id, assessment_type='PRE', serial_number=1, question="State primary requirement for this virtual course?", option1="Internet", option2="Pencil", option3="Hammer", option4="None", correct_option="Option1")
                post = CourseAssessment(course_id=c.id, assessment_type='POST', serial_number=1, question="Which command validates successful build completion?", option1="npm run build", option2="npm start", option3="npm install", option4="npm test", correct_option="Option1")
                db.session.add_all([pre, post])
                db.session.commit()

            print("Successfully seeded 3 live online courses.")

            # 5. Seed Live In-Person Courses (3 total)
            live_inperson_courses = [
                ("Advanced Facilitation Skills for Educators", "In-person interactive laboratory to learn group mentoring dynamics."),
                ("Physical Network Security & Hardware Configurations", "Hands-on routers, switches, and wiring laboratory diagnostics."),
                ("Agile L&D Operations & Scalable Frameworks", "Interactive group planning exercises for training administrators.")
            ]

            seeded_inperson_courses = []
            for idx, (title, desc) in enumerate(live_inperson_courses, 1):
                course_id = f"CRS-IP-{idx:03d}"
                c = Course(
                    course_id=course_id,
                    name=title,
                    duration_hours=8.0,
                    description=desc,
                    mode="Live In Person",
                    pass_percentage=80.0,
                    feedback_repo_id=fb_repo.id,
                    has_certificate=True
                )
                db.session.add(c)
                db.session.commit()
                seeded_inperson_courses.append(c)

                # Create live class session scheduled for future days
                cls_date = datetime.date.today() + timedelta(days=idx + 2)
                cls = LiveClass(
                    class_id=f"CLS-INP-{idx:03d}",
                    class_name=f"{course_id}-{cls_date.strftime('%d-%b-%Y')}-HYD-MADHAPUR",
                    course_id=c.id,
                    class_mode="In Person",
                    class_date=cls_date,
                    location="HYD",
                    branch="Madhapur Campus",
                    session_time="Morning",
                    facilitator_id=manager_learner.id,
                    duration_hours=6.0,
                    expected_attendance=25,
                    feedback_repo_id=fb_repo.id
                )
                db.session.add(cls)
                db.session.commit()

                # Add Pre/Post assessments
                pre = CourseAssessment(course_id=c.id, assessment_type='PRE', serial_number=1, question="What is critical for campus laboratory operations?", option1="Safety protocols", option2="Sleeping", option3="Games", option4="None", correct_option="Option1")
                post = CourseAssessment(course_id=c.id, assessment_type='POST', serial_number=1, question="How is student performance graded?", option1="Pass/Fail Matrix", option2="No grades", option3="Quiz only", option4="None", correct_option="Option1")
                db.session.add_all([pre, post])
                db.session.commit()

            print("Successfully seeded 3 live in-person courses.")

            # 6. Enroll Rajesh Kumar (Learner 1) in some courses to view immediately
            en1 = LearnerEnrollment(learner_id=manager_learner.id, course_id=seeded_sp_courses[0].id, completion_status='In Progress')
            en2 = LearnerEnrollment(learner_id=manager_learner.id, course_id=seeded_sp_courses[1].id, completion_status='Enrolled')
            en3 = LearnerEnrollment(learner_id=manager_learner.id, course_id=seeded_online_courses[0].id, class_id=1, completion_status='Enrolled')
            en4 = LearnerEnrollment(learner_id=manager_learner.id, course_id=seeded_inperson_courses[0].id, class_id=2, completion_status='Enrolled')
            db.session.add_all([en1, en2, en3, en4])
            db.session.commit()

            # Seed mock helpdesk support tickets
            issue1 = LmsIssue(learner_id=manager_learner.id, category='Technical', description='Cannot load flashcards for Python course. Page shows blank white card.', status='Open')
            issue2 = LmsIssue(learner_id=learners[1].id, category='Content', description='The lesson slides for ML models has typo on slide 5: learning rate parameter was spelled wrong.', status='Open')
            issue3 = LmsIssue(learner_id=learners[2].id, category='Certificate', description=f'[Escalation] Extension requested for course. Enrollment ID: {en1.id}', status='Open')
            db.session.add_all([issue1, issue2, issue3])
            db.session.commit()

            print("Database initialized successfully!")
