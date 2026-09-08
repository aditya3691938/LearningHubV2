import os
import re
from app.utils.decorators import admin_required
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
import pandas as pd
from app.models import db
from app.models.user import Learner
from app.models.course import Course, CourseAssessment, CourseLesson
from app.models.live_class import LiveClass
from app.models.enrollment import LearnerEnrollment, AssessmentAttempt, LessonReview
from app.models.attendance import Attendance
from app.models.feedback import FeedbackRepository, FeedbackQuestion, FeedbackResponse
from app.models.certificate import Certificate
from app.services.assessment_service import evaluate_assessment
from app.services.pdf_service import generate_certificate_pdf
from app.services.learning_wall_service import create_completion_post

learners_bp = Blueprint('learners', __name__)

# --- ADMIN LEARNER MANAGEMENT   ---

@learners_bp.route('/')
@admin_required
def list_learners():

    search_query = request.args.get('search', '').strip()
    page = request.args.get('page', 1, type=int)
    query = Learner.query

    if search_query:
        query = query.filter(
            (Learner.global_id.ilike(f'%{search_query}%')) |
            (Learner.name.ilike(f'%{search_query}%')) |
            (Learner.department.ilike(f'%{search_query}%'))
        )

    learners = query.order_by(Learner.id.desc()).paginate(page=page, per_page=50, error_out=False)
    courses = Course.query.all()
    return render_template('learners/list.html', learners=learners, courses=courses, search_query=search_query)


@learners_bp.route('/reset_attempts/<int:learner_id>', methods=['POST'])
@admin_required
def reset_learner_attempts(learner_id):
    """
    Admin Route: Reset assessment attempts for a learner for a specific course so they can retake the Course End Assessment.
    """

    learner = Learner.query.get_or_404(learner_id)
    course_id = request.form.get('course_id')
    
    if not course_id:
        flash("Please select a course to reset attempts for.", "danger")
        return redirect(request.referrer or url_for('learners.list_learners'))
        
    enrollments = LearnerEnrollment.query.filter_by(learner_id=learner.id, course_id=course_id).all()
    for en in enrollments:
        en.attempts_count = 0
        en.completion_status = 'Enrolled'
        en.final_score = None
        en.completion_date = None
        AssessmentAttempt.query.filter_by(enrollment_id=en.id).delete()

    db.session.commit()
    flash(f'Assessment attempts successfully reset for {learner.global_id} on the selected course.', 'success')
    return redirect(request.referrer or url_for('learners.list_learners'))


@learners_bp.route('/<int:learner_id>/detail')
@admin_required
def learner_detail(learner_id):
    """Admin Route: Full learner profile — enrollments, attendance, certs, assessment history."""

    from app.models.certificate import Certificate
    from app.models.attendance import Attendance

    learner = Learner.query.get_or_404(learner_id)
    enrollments = LearnerEnrollment.query.filter_by(learner_id=learner.id).order_by(LearnerEnrollment.assigned_at.desc()).all()
    attendances = Attendance.query.filter_by(learner_id=learner.id).order_by(Attendance.timestamp.desc()).all()
    certificates = Certificate.query.filter_by(learner_id=learner.id).order_by(Certificate.issue_date.desc()).all()
    attempts = AssessmentAttempt.query.join(LearnerEnrollment).filter(LearnerEnrollment.learner_id == learner.id).order_by(AssessmentAttempt.submitted_at.desc()).all()
    from app.models.enrollment import LessonReview
    from app.models.live_class import LiveClass

    # Build progress map: {enrollment_id: {'type': 'lessons'|'classes', 'done': int, 'total': int}}
    progress_map = {}
    for en in enrollments:
        if en.course.mode == 'Self Paced':
            total_lessons = len(en.course.lessons) if en.course.lessons else 0
            if total_lessons > 0:
                done_count = LessonReview.query.filter_by(enrollment_id=en.id).count()
            else:
                done_count = 0
            progress_map[en.id] = {'type': 'lessons', 'done': done_count, 'total': total_lessons}
        else:
            # Check Attendance
            has_attended = Attendance.query.join(LiveClass).filter(
                Attendance.learner_id == learner.id,
                LiveClass.course_id == en.course.id,
                Attendance.status == 'Present'
            ).first() is not None
            
            # Check Assessment
            has_passed_assessment = AssessmentAttempt.query.filter_by(
                enrollment_id=en.id,
                assessment_type='POST',
                passed=True
            ).first() is not None
            
            # Check Feedback
            from app.models.feedback import FeedbackResponse
            has_feedback = FeedbackResponse.query.join(LiveClass).filter(
                FeedbackResponse.learner_id == learner.id,
                LiveClass.course_id == en.course.id
            ).first() is not None

            progress_map[en.id] = {
                'type': 'live_status',
                'attended': has_attended,
                'assessment': has_passed_assessment,
                'feedback': has_feedback
            }

    return render_template(
        'learners/detail.html',
        learner=learner,
        enrollments=enrollments,
        attendances=attendances,
        certificates=certificates,
        attempts=attempts,
        progress_map=progress_map
    )



def parse_global_ids_from_input(global_ids_text, csv_file=None):
    parsed_ids = []
    seen = set()

    if global_ids_text:
        raw_tokens = re.split(r'[\r\n,;\s]+', str(global_ids_text))
        for token in raw_tokens:
            val = token.strip().strip('"').strip("'")
            if val.endswith('.0'):
                val = val[:-2]
            if val and val not in seen:
                seen.add(val)
                parsed_ids.append(val)

    if csv_file and getattr(csv_file, 'filename', None):
        try:
            df = pd.read_csv(csv_file.stream)
            if not df.empty:
                col_name = df.columns[0]
                for col in df.columns:
                    if 'global' in str(col).lower() or 'id' in str(col).lower():
                        col_name = col
                        break
                for val in df[col_name].dropna():
                    val_str = str(val).strip().strip('"').strip("'")
                    if val_str.endswith('.0'):
                        val_str = val_str[:-2]
                    if val_str and val_str not in seen:
                        seen.add(val_str)
                        parsed_ids.append(val_str)
        except Exception as e:
            pass

    return parsed_ids


@learners_bp.route('/assign', methods=['GET', 'POST'])
@admin_required
def assign_learners():

    courses = Course.query.filter_by(mode='Self Paced').all()

    if request.method == 'POST':
        is_ajax = (
            request.is_json
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

        course_id_raw = request.form.get('course_id') or (request.json.get('course_id') if request.is_json and request.json else None)
        try:
            course_id = int(course_id_raw)
            course = Course.query.get(course_id)
        except (TypeError, ValueError):
            course = None

        if not course:
            msg = "Invalid course selection."
            if is_ajax:
                return jsonify({'success': False, 'message': msg}), 400
            flash(msg, "danger")
            return redirect(url_for('learners.assign_learners'))

        assignment_mode = request.form.get('assignment_mode', 'manual')
        parsed_global_ids = []

        if assignment_mode == 'parameters':
            dept = request.form.get('filter_department', '').strip()
            desg = request.form.get('filter_designation', '').strip()
            loc = request.form.get('filter_location', '').strip()
            br = request.form.get('filter_branch', '').strip()

            query = Learner.query
            has_filters = False
            if dept:
                query = query.filter_by(department=dept)
                has_filters = True
            if desg:
                query = query.filter_by(designation=desg)
                has_filters = True
            if loc:
                query = query.filter_by(location=loc)
                has_filters = True
            if br:
                query = query.filter_by(branch=br)
                has_filters = True

            if not has_filters:
                msg = "Please select at least one parameter filter for batch assignment."
                if is_ajax:
                    return jsonify({'success': False, 'message': msg}), 400
                flash(msg, "warning")
                return redirect(url_for('courses.view_course', course_id=course.id))

            filtered_learners = query.all()
            parsed_global_ids = [learner.global_id for learner in filtered_learners]
        else:
            global_ids_text = request.form.get('global_ids', '').strip()
            csv_file = request.files.get('learner_csv')
            parsed_global_ids = parse_global_ids_from_input(global_ids_text, csv_file)

        if not parsed_global_ids:
            msg = "No matching learners found or no valid Global IDs provided."
            if is_ajax:
                return jsonify({'success': False, 'message': msg}), 400
            flash(msg, "warning")
            return redirect(url_for('courses.view_course', course_id=course.id))

        assigned_count = 0
        already_enrolled_count = 0
        invalid_ids = []

        from app.models.notification import LearnerNotification

        for gid in parsed_global_ids:
            learner = Learner.query.filter_by(global_id=gid).first()
            if not learner:
                invalid_ids.append(gid)
                continue

            # Check if enrollment already exists
            existing_en = LearnerEnrollment.query.filter_by(learner_id=learner.id, course_id=course.id).first()
            if not existing_en:
                en = LearnerEnrollment(
                    learner_id=learner.id,
                    course_id=course.id,
                    completion_status='Enrolled'
                )
                db.session.add(en)
                assigned_count += 1

                # Send Course Assignment notification to learner
                notif = LearnerNotification(
                    learner_id=learner.id,
                    course_id=course.id,
                    title=f"New Course Assigned: {course.name}",
                    message=f"You have been assigned to the self-paced course '{course.name}' ({course.course_id}). Start learning now!",
                    notification_type='COURSE_ASSIGNED'
                )
                db.session.add(notif)
            else:
                already_enrolled_count += 1

        db.session.commit()

        msg = f"Assignment Results for Course '{course.name}': {assigned_count} newly assigned."
        if already_enrolled_count > 0:
            msg += f" {already_enrolled_count} learner(s) were already enrolled."
        if invalid_ids:
            msg += f" {len(invalid_ids)} invalid/non-existing Global ID(s) could not be assigned: {', '.join(invalid_ids[:5])}{'...' if len(invalid_ids) > 5 else ''}."

        if is_ajax:
            is_error = (assigned_count == 0 and already_enrolled_count == 0 and len(invalid_ids) > 0)
            return jsonify({
                'success': not is_error,
                'message': msg,
                'assigned_count': assigned_count,
                'already_enrolled_count': already_enrolled_count,
                'invalid_ids': invalid_ids
            }), (400 if is_error else 200)

        if invalid_ids and assigned_count == 0 and already_enrolled_count == 0:
            flash(msg, "danger")
        elif invalid_ids:
            flash(msg, "warning")
        else:
            flash(msg, "success")

        return redirect(url_for('courses.view_course', course_id=course.id))

    # Fetch unique list values for parameter selectors
    departments = [r[0] for r in db.session.query(Learner.department).distinct() if r[0]]
    designations = [r[0] for r in db.session.query(Learner.designation).distinct() if r[0]]
    locations = [r[0] for r in db.session.query(Learner.location).distinct() if r[0]]
    branches = [r[0] for r in db.session.query(Learner.branch).distinct() if r[0]]

    return render_template(
        'learners/assign.html',
        courses=courses,
        departments=sorted(departments),
        designations=sorted(designations),
        locations=sorted(locations),
        branches=sorted(branches)
    )


# --- LEARNER PORTAL FLOWS ---

@learners_bp.route('/portal')
def my_portal():
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in with your Global ID.", "info")
        return redirect(url_for('auth.learner_login'))

    learner = Learner.query.get_or_404(learner_id)
    
    # Update active streak
    today = datetime.utcnow().date()
    if learner.last_active_date:
        delta = (today - learner.last_active_date).days
        if delta == 1:
            learner.current_streak += 1
            learner.last_active_date = today
            db.session.commit()
        elif delta > 1:
            learner.current_streak = 1
            learner.last_active_date = today
            db.session.commit()
    else:
        learner.current_streak = 1
        learner.last_active_date = today
        db.session.commit()

    enrollments = LearnerEnrollment.query.filter_by(learner_id=learner.id).all()
    
    from app.models.notification import LearnerNotification
    from app.models.certificate import Certificate
    notifications = LearnerNotification.query.filter_by(learner_id=learner.id).order_by(LearnerNotification.created_at.desc()).all()
    certificates = Certificate.query.filter_by(learner_id=learner.id).order_by(Certificate.issue_date.desc()).all()

    # Build lesson progress map: {enrollment_id: {done: int, total: int, pct: float, ...}}
    progress_map = {}
    from app.models.course import CourseAssessment
    from app.models.enrollment import AssessmentAttempt, LessonReview
    
    for en in enrollments:
        total_lessons = len(en.course.lessons) if en.course.lessons else 0
        
        # 1. Pre Assessment Status
        has_pre = CourseAssessment.query.filter_by(course_id=en.course.id, assessment_type='PRE').count() > 0
        pre_att = AssessmentAttempt.query.filter_by(enrollment_id=en.id, assessment_type='PRE').first()
        if not has_pre:
            pre_status = "N/A"
        elif pre_att:
            pre_status = "Completed"
        else:
            pre_status = "Pending"
            
        # 2. Lessons Status (done/total)
        reviewed_reviews = LessonReview.query.filter_by(enrollment_id=en.id).all()
        reviewed_lesson_ids = {r.lesson_id for r in reviewed_reviews}
        done_count = 0
        for les in en.course.lessons:
            has_les_post = CourseAssessment.query.filter_by(course_id=en.course.id, lesson_id=les.id, assessment_type='LESSON_POST').count() > 0
            if has_les_post:
                post_att = AssessmentAttempt.query.filter(
                    (AssessmentAttempt.enrollment_id == en.id) & 
                    (AssessmentAttempt.assessment_type.in_(['LESSON_POST', 'POST'])) & 
                    ((AssessmentAttempt.lesson_id == les.id) | (AssessmentAttempt.lesson_number == les.lesson_number)) & 
                    (AssessmentAttempt.passed == True)
                ).first()
                if post_att:
                    done_count += 1
            else:
                if les.id in reviewed_lesson_ids:
                    done_count += 1
        lessons_status = f"{done_count:02d}/{total_lessons:02d}"
        
        # 3. Post Assessment Status
        course_end_att = AssessmentAttempt.query.filter_by(enrollment_id=en.id, assessment_type='COURSE_END').order_by(AssessmentAttempt.id.desc()).first()
        if course_end_att and course_end_att.passed:
            post_status = "Passed"
        elif course_end_att and not course_end_att.passed:
            post_status = "Failed" if en.attempts_count >= 3 else "Pending"
        else:
            if total_lessons > 0 and done_count == total_lessons:
                post_status = "Pending"
            else:
                post_status = "Locked"
                
        # 4. Feedback Status (Strictly locked until Post Assessment is Passed)
        from app.models.feedback import FeedbackResponse, FeedbackRepository
        fb_repo = en.course.feedback_repository or FeedbackRepository.query.first()
        fb_resp = None
        if fb_repo:
            fb_resp = FeedbackResponse.query.filter_by(repo_id=fb_repo.id, learner_id=learner.id).first()
        
        if post_status == "Passed":
            feedback_status = "Submitted" if fb_resp else "Pending"
        else:
            feedback_status = "Locked"

        # Strict Database Completion Status Integrity Check:
        # A course CANNOT have completion_status = 'Completed' if Post Assessment is not Passed or Feedback is not Submitted!
        if en.completion_status == 'Completed':
            if post_status != 'Passed' or feedback_status != 'Submitted':
                en.completion_status = 'In Progress'
                db.session.commit()

        # Live Class parameters
        from app.models.attendance import Attendance
        att = Attendance.query.filter_by(class_id=en.class_id, learner_id=learner.id).first() if en.class_id else None
        attendance_status = "Present" if (att and att.status == 'Present') else "Pending"

        # Determine dynamic button text and URL
        btn_text = "Continue Learning"
        btn_url = url_for('learners.self_paced_flow', course_id_str=en.course.course_id)
        
        if en.course.mode != 'Self Paced':
            # Live Classes Button Text / URL
            cls_id = en.live_class.class_id if en.live_class else (en.course.classes[0].class_id if en.course.classes else '')
            if en.completion_status == 'Completed':
                from app.models.certificate import Certificate
                my_cert = Certificate.query.filter_by(learner_id=learner.id, course_id=en.course.id).first()
                if my_cert:
                    btn_text = "Download Certificate"
                    btn_url = url_for('certificates.download_certificate', cert_id_str=my_cert.certificate_id)
                else:
                    btn_text = "Course Completed"
                    btn_url = url_for('learners.class_flow', class_id_str=cls_id) if cls_id else "#"
            elif pre_status == "Pending":
                btn_text = "Take Pre Course Assessment"
                btn_url = url_for('learners.take_assessment', course_id=en.course.id, assessment_type='PRE')
            elif attendance_status == "Present" and post_status == "Passed" and feedback_status == "Pending":
                btn_text = "Submit Feedback"
                if fb_repo:
                    btn_url = url_for('learners.submit_feedback', repo_id=fb_repo.id) + '?course_id=' + str(en.course.id) + ('&class_id=' + str(en.class_id) if en.class_id else '')
            elif attendance_status == "Present" and post_status == "Pending":
                btn_text = "Take Course End Assessment"
                btn_url = url_for('learners.take_assessment', course_id=en.course.id, assessment_type='COURSE_END')
            elif cls_id:
                btn_text = "Go to Class Flow"
                btn_url = url_for('learners.class_flow', class_id_str=cls_id)
            else:
                btn_text = "Class Pending"
                btn_url = "#"
        else:
            # Self Paced Button Text / URL
            if en.completion_status == 'Completed':
                from app.models.certificate import Certificate
                my_cert = Certificate.query.filter_by(learner_id=learner.id, course_id=en.course.id).first()
                if my_cert:
                    btn_text = "Download Certificate"
                    btn_url = url_for('certificates.download_certificate', cert_id_str=my_cert.certificate_id)
                else:
                    btn_text = "Course Completed"
                    btn_url = url_for('learners.self_paced_flow', course_id_str=en.course.course_id)
            elif pre_status == "Pending":
                btn_text = "Take Pre Course Assessment"
                btn_url = url_for('learners.take_assessment', course_id=en.course.id, assessment_type='PRE')
            elif (total_lessons == 0 or done_count == total_lessons) and post_status == "Passed" and feedback_status == "Pending":
                btn_text = "Submit Feedback"
                if fb_repo:
                    btn_url = url_for('learners.submit_feedback', repo_id=fb_repo.id) + '?course_id=' + str(en.course.id)
            elif (total_lessons == 0 or done_count == total_lessons) and post_status == "Pending":
                btn_text = "Take Course End Assessment"
                btn_url = url_for('learners.take_assessment', course_id=en.course.id, assessment_type='COURSE_END')
            elif en.completion_status == 'Enrolled' and done_count == 0:
                btn_text = "Start Learning"
                btn_url = url_for('learners.self_paced_flow', course_id_str=en.course.course_id)
            else:
                btn_text = "Continue Learning"
                btn_url = url_for('learners.self_paced_flow', course_id_str=en.course.course_id)

        course_url = url_for('learners.self_paced_flow', course_id_str=en.course.course_id) if en.course.mode == 'Self Paced' else (url_for('learners.class_flow', class_id_str=cls_id) if cls_id else '#')

        progress_map[en.id] = {
            'done': done_count,
            'total': total_lessons,
            'pct': round(min(done_count / total_lessons, 1.0) * 100) if total_lessons > 0 else 0,
            'pre_status': pre_status,
            'lessons_status': lessons_status,
            'post_status': post_status,
            'feedback_status': feedback_status,
            'attendance_status': attendance_status,
            'btn_text': btn_text,
            'btn_url': btn_url,
            'course_url': course_url
        }

    # Check if this learner has subordinates (is a manager)
    subordinates = Learner.query.filter_by(manager_id=learner.id).all()
    is_manager = len(subordinates) > 0
    subordinate_data = []

    if is_manager:
        for sub in subordinates:
            sub_enrollments = LearnerEnrollment.query.filter_by(learner_id=sub.id).all()
            courses_info = []
            for sub_en in sub_enrollments:
                total_lessons = len(sub_en.course.lessons) if sub_en.course.lessons else 0
                if total_lessons > 0:
                    reviewed_reviews_sub = LessonReview.query.filter_by(enrollment_id=sub_en.id).all()
                    reviewed_lesson_ids_sub = {r.lesson_id for r in reviewed_reviews_sub}
                    
                    done_count = 0
                    for les in sub_en.course.lessons:
                        has_les_post = CourseAssessment.query.filter_by(course_id=sub_en.course.id, lesson_id=les.id, assessment_type='LESSON_POST').count() > 0
                        if has_les_post:
                            post_att = AssessmentAttempt.query.filter(
                                (AssessmentAttempt.enrollment_id == sub_en.id) & 
                                (AssessmentAttempt.assessment_type.in_(['LESSON_POST', 'POST'])) & 
                                ((AssessmentAttempt.lesson_id == les.id) | (AssessmentAttempt.lesson_number == les.lesson_number)) & 
                                (AssessmentAttempt.passed == True)
                            ).first()
                            if post_att:
                                done_count += 1
                        else:
                            if les.id in reviewed_lesson_ids_sub:
                                done_count += 1
                    pct = round(min(done_count / total_lessons, 1.0) * 100)
                else:
                    done_count = 0
                    pct = 100 if sub_en.completion_status == 'Completed' else 0

                # Expiry check
                sub_expired = False
                if sub_en.course.completion_date and sub_en.course.completion_date < datetime.utcnow():
                    sub_expired = True
                    if sub_en.extended_deadline and sub_en.extended_deadline >= datetime.utcnow():
                        sub_expired = False
                elif sub_en.class_id:
                    # Live class check
                    live_cl = LiveClass.query.get(sub_en.class_id)
                    if live_cl and ((live_cl.class_date < datetime.utcnow().date()) or live_cl.is_locked):
                        sub_expired = True
                        if sub_en.extended_deadline and sub_en.extended_deadline.date() >= datetime.utcnow().date():
                            sub_expired = False

                courses_info.append({
                    'enrollment_id': sub_en.id,
                    'course_name': sub_en.course.name,
                    'mode': sub_en.course.mode,
                    'pct': pct,
                    'status': sub_en.completion_status,
                    'is_expired': sub_expired,
                    'extended_deadline': sub_en.extended_deadline,
                    'extension_requested': sub_en.extension_requested
                })
            subordinate_data.append({
                'subordinate': sub,
                'courses': courses_info
            })

    # Leaderboard (Top 5 Learners)
    top_learners = Learner.query.order_by(Learner.points.desc()).limit(5).all()
    dept_top_learners = []
    if learner.department:
        dept_top_learners = Learner.query.filter_by(department=learner.department).order_by(Learner.points.desc()).limit(5).all()

    return render_template(
        'learner_portal/portal.html',
        learner=learner,
        enrollments=enrollments,
        notifications=notifications,
        certificates=certificates,
        progress_map=progress_map,
        is_manager=is_manager,
        subordinate_data=subordinate_data,
        top_learners=top_learners,
        dept_top_learners=dept_top_learners
    )


@learners_bp.route('/notifications/mark_read/<int:notif_id>', methods=['POST'])
def mark_notification_read(notif_id):
    learner_id = session.get('learner_id')
    if not learner_id:
        return jsonify({'status': 'error'}), 401
    
    from app.models.notification import LearnerNotification
    if notif_id == 0:
        # Mark all as read
        notifications = LearnerNotification.query.filter_by(learner_id=learner_id, is_read=False).all()
        for n in notifications:
            n.is_read = True
    else:
        notif = LearnerNotification.query.filter_by(id=notif_id, learner_id=learner_id).first()
        if notif:
            notif.is_read = True
    
    db.session.commit()
    return jsonify({'status': 'success'})


@learners_bp.route('/class_flow/<class_id_str>')
def class_flow(class_id_str):
    """
    LIVE COURSE FLOW:
    QR -> Login -> Attendance Auto-recorded -> Pre Assessment -> Training / Google Meet -> Post Assessment -> Downloads -> Feedback
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        return redirect(url_for('auth.learner_login', classId=class_id_str))

    learner = Learner.query.get_or_404(learner_id)
    live_class = LiveClass.query.filter_by(class_id=class_id_str).first_or_404()
    course = live_class.course

    # Find or create enrollment first to check extensions
    enrollment = LearnerEnrollment.query.filter_by(learner_id=learner.id, course_id=course.id, class_id=live_class.id).first()
    if not enrollment:
        enrollment = LearnerEnrollment(
            learner_id=learner.id,
            course_id=course.id,
            class_id=live_class.id,
            completion_status='In Progress'
        )
        db.session.add(enrollment)
        db.session.commit()

    is_expired = (live_class.class_date < datetime.utcnow().date()) or live_class.is_locked
    if is_expired and enrollment.extended_deadline:
        if enrollment.extended_deadline.date() >= datetime.utcnow().date():
            is_expired = False

    # 1. Automatic Attendance Recording upon scanning QR & logging in (only if class not expired)
    att = Attendance.query.filter_by(class_id=live_class.id, learner_id=learner.id).first()
    if not att and not is_expired:
        att = Attendance(
            class_id=live_class.id,
            learner_id=learner.id,
            status='Present',
            recorded_via='QR'
        )
        db.session.add(att)
        db.session.commit()

    # Pre and Post attempts & Pre questions check
    has_pre_questions = CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type.in_(['PRE', 'LESSON_PRE']))).count() > 0
    pre_attempt = AssessmentAttempt.query.filter((AssessmentAttempt.enrollment_id == enrollment.id) & (AssessmentAttempt.assessment_type.in_(['PRE', 'LESSON_PRE']))).order_by(AssessmentAttempt.id.desc()).first()
    post_attempt = AssessmentAttempt.query.filter((AssessmentAttempt.enrollment_id == enrollment.id) & (AssessmentAttempt.assessment_type.in_(['POST', 'LESSON_POST']))).order_by(AssessmentAttempt.id.desc()).first()
    feedback_resp = FeedbackResponse.query.filter_by(class_id=live_class.id, learner_id=learner.id).first()
    cert = Certificate.query.filter_by(learner_id=learner.id, course_id=course.id).first()

    return render_template(
        'learner_portal/class_flow.html',
        learner=learner,
        live_class=live_class,
        course=course,
        enrollment=enrollment,
        attendance=att,
        is_expired=is_expired,
        has_pre_questions=has_pre_questions,
        pre_attempt=pre_attempt,
        post_attempt=post_attempt,
        feedback_resp=feedback_resp,
        certificate=cert
    )


@learners_bp.route('/self_paced_flow/<course_id_str>')
def self_paced_flow(course_id_str):
    """
    SELF PACED COURSE FLOW:
    Pre Assessment (if created) -> Lessons & Courseware -> Course End Assessment -> Certificate
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        return redirect(url_for('auth.learner_login', courseId=course_id_str))

    learner = Learner.query.get_or_404(learner_id)
    course = Course.query.filter_by(course_id=course_id_str).first_or_404()

    enrollment = LearnerEnrollment.query.filter_by(learner_id=learner.id, course_id=course.id).first()
    if not enrollment:
        enrollment = LearnerEnrollment(
            learner_id=learner.id,
            course_id=course.id,
            completion_status='In Progress'
        )
        db.session.add(enrollment)
        db.session.commit()

    has_pre_questions = CourseAssessment.query.filter_by(course_id=course.id, assessment_type='PRE').count() > 0
    pre_attempt = AssessmentAttempt.query.filter_by(enrollment_id=enrollment.id, assessment_type='PRE').first()
    post_attempt = AssessmentAttempt.query.filter((AssessmentAttempt.enrollment_id == enrollment.id) & (AssessmentAttempt.assessment_type.in_(['POST', 'LESSON_POST']))).order_by(AssessmentAttempt.id.desc()).first()
    course_end_attempt = AssessmentAttempt.query.filter((AssessmentAttempt.enrollment_id == enrollment.id) & (AssessmentAttempt.assessment_type == 'COURSE_END')).order_by(AssessmentAttempt.id.desc()).first()

    all_attempts = AssessmentAttempt.query.filter_by(enrollment_id=enrollment.id).order_by(AssessmentAttempt.id.asc()).all()
    lesson_pre_attempts = {}
    lesson_post_attempts = {}
    for att in all_attempts:
        if att.assessment_type == 'LESSON_PRE':
            if att.lesson_id is not None:
                lesson_pre_attempts[att.lesson_id] = att
            elif att.lesson_number is not None:
                lesson_pre_attempts[att.lesson_number] = att
        elif att.assessment_type == 'LESSON_POST':
            if att.lesson_id is not None:
                lesson_post_attempts[att.lesson_id] = att
            elif att.lesson_number is not None:
                lesson_post_attempts[att.lesson_number] = att

    reviewed_reviews = LessonReview.query.filter_by(enrollment_id=enrollment.id).all()
    reviewed_lesson_ids = [r.lesson_id for r in reviewed_reviews]

    completed_lesson_ids = set()
    for les in course.lessons:
        has_les_post = CourseAssessment.query.filter_by(course_id=course.id, lesson_id=les.id, assessment_type='LESSON_POST').count() > 0
        post_att = lesson_post_attempts.get(les.id) or lesson_post_attempts.get(les.lesson_number)
        
        is_cw_reviewed = les.id in reviewed_lesson_ids
        if has_les_post:
            if post_att and post_att.passed:
                completed_lesson_ids.add(les.id)
        elif is_cw_reviewed:
            completed_lesson_ids.add(les.id)

    feedback_repo = course.feedback_repository or FeedbackRepository.query.first()
    feedback_resp = None
    if feedback_repo:
        feedback_resp = FeedbackResponse.query.filter_by(repo_id=feedback_repo.id, learner_id=learner.id).first()

    cert = Certificate.query.filter_by(learner_id=learner.id, course_id=course.id).first()

    is_course_expired = False
    if course.completion_date and course.completion_date < datetime.utcnow():
        is_course_expired = True
        if enrollment.extended_deadline and enrollment.extended_deadline >= datetime.utcnow():
            is_course_expired = False

    return render_template(
        'learner_portal/self_paced_flow.html',
        learner=learner,
        course=course,
        enrollment=enrollment,
        has_pre_questions=has_pre_questions,
        pre_attempt=pre_attempt,
        post_attempt=post_attempt,
        course_end_attempt=course_end_attempt,
        lesson_pre_attempts=lesson_pre_attempts,
        lesson_post_attempts=lesson_post_attempts,
        reviewed_lesson_ids=reviewed_lesson_ids,
        completed_lesson_ids=completed_lesson_ids,
        feedback_repo=feedback_repo,
        feedback_resp=feedback_resp,
        certificate=cert,
        is_course_expired=is_course_expired
    )


@learners_bp.route('/record_courseware_time/<int:lesson_id>', methods=['POST'])
def record_courseware_time(lesson_id):
    learner_id = session.get('learner_id')
    if not learner_id:
        return jsonify({'status': 'error', 'message': 'Not authenticated'}), 401

    lesson = CourseLesson.query.get_or_404(lesson_id)
    course = Course.query.get_or_404(lesson.course_id)
    enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=course.id).first()
    if enrollment:
        existing = LessonReview.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id).first()
        if not existing:
            review = LessonReview(enrollment_id=enrollment.id, lesson_id=lesson.id)
            db.session.add(review)
            db.session.commit()
        return jsonify({'status': 'success', 'unlocked': True, 'lesson_id': lesson_id})
    return jsonify({'status': 'error', 'message': 'Enrollment not found'}), 404


@learners_bp.route('/take_assessment/<course_id>/<assessment_type>', methods=['GET', 'POST'])
def take_assessment(course_id, assessment_type):
    learner_id = session.get('learner_id')
    if not learner_id:
        return redirect(url_for('auth.learner_login'))

    learner = Learner.query.get_or_404(learner_id)
    
    # Dual lookup: support both integer ID (e.g. 1) and public string course_id (e.g. CRS-000001)
    if str(course_id).isdigit():
        course = Course.query.get(int(course_id)) or Course.query.filter_by(course_id=str(course_id)).first_or_404()
    else:
        course = Course.query.filter_by(course_id=str(course_id)).first_or_404()
    
    class_id_str = request.args.get('class_id')
    lesson_id_param = request.args.get('lesson_id')
    live_class = LiveClass.query.filter_by(class_id=class_id_str).first() if class_id_str else None

    enrollment = LearnerEnrollment.query.filter_by(learner_id=learner.id, course_id=course.id).first()
    if not enrollment:
        enrollment = LearnerEnrollment(learner_id=learner.id, course_id=course.id, class_id=live_class.id if live_class else None)
        db.session.add(enrollment)
        db.session.commit()

    # Check if course is expired
    is_course_expired = False
    if course.completion_date and course.completion_date < datetime.utcnow():
        is_course_expired = True
        if enrollment.extended_deadline and enrollment.extended_deadline >= datetime.utcnow():
            is_course_expired = False

    if is_course_expired:
        flash("This course has expired. You cannot take assessments unless your manager grants an extension.", "danger")
        return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))

    # Determine if this is strictly the final Course End Assessment
    type_upper = assessment_type.upper()
    is_course_end = (type_upper == 'COURSE_END')

    # Check attempt limits and lesson completion strictly ONLY for Course End Assessment (max 3 attempts)
    if course.mode == 'Self Paced' and is_course_end:
        reviewed_reviews = LessonReview.query.filter_by(enrollment_id=enrollment.id).all()
        reviewed_lesson_ids = [r.lesson_id for r in reviewed_reviews]
        
        all_completed = True
        for les in course.lessons:
            has_les_post = CourseAssessment.query.filter_by(course_id=course.id, lesson_id=les.id, assessment_type='LESSON_POST').count() > 0
            post_att = AssessmentAttempt.query.filter((AssessmentAttempt.enrollment_id == enrollment.id) & (AssessmentAttempt.assessment_type.in_(['LESSON_POST', 'POST'])) & ((AssessmentAttempt.lesson_id == les.id) | (AssessmentAttempt.lesson_number == les.lesson_number)) & (AssessmentAttempt.passed == True)).first()
            is_cw_reviewed = les.id in reviewed_lesson_ids
            
            les_done = bool(post_att) if has_les_post else is_cw_reviewed
            if not les_done:
                all_completed = False
                break
                
        if not all_completed:
            flash("Course End Assessment is locked. You must complete all lessons and post-assessments first.", "warning")
            return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))

        if enrollment.attempts_count >= 3 and not (enrollment.final_score and enrollment.final_score >= course.pass_percentage):
            flash("Maximum attempt limit (3 attempts) reached for the Course End Assessment.", "danger")
            return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))

    # Ensure courseware is reviewed before taking Post-Assessment
    if 'POST' in type_upper:
        target_les_id = int(lesson_id_param) if lesson_id_param else (course.lessons[0].id if course.lessons else None)
        if target_les_id:
            rev = LessonReview.query.filter_by(enrollment_id=enrollment.id, lesson_id=target_les_id).first()
            if not rev:
                flash("You must review and complete the uploading courseware before attempting the Post-Assessment.", "warning")
                return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))

    # Query questions: filter by course_id and matching assessment_type
    query = CourseAssessment.query.filter_by(course_id=course.id)
    if lesson_id_param:
        query = query.filter_by(lesson_id=int(lesson_id_param))
        if 'PRE' in type_upper:
            query = query.filter(CourseAssessment.assessment_type.in_(['LESSON_PRE', 'PRE']))
        else:
            query = query.filter(CourseAssessment.assessment_type.in_(['LESSON_POST', 'POST']))
    else:
        if type_upper in ['PRE', 'LESSON_PRE']:
            # First try course-level PRE assessments
            pre_count = CourseAssessment.query.filter_by(course_id=course.id, assessment_type='PRE').count()
            if pre_count > 0:
                query = query.filter_by(assessment_type='PRE')
            else:
                # If only lesson-level PRE assessments exist, isolate first lesson to prevent multi-lesson duplicates
                first_lesson = CourseLesson.query.filter_by(course_id=course.id).order_by(CourseLesson.lesson_number.asc()).first()
                if first_lesson:
                    query = query.filter((CourseAssessment.lesson_id == first_lesson.id) & (CourseAssessment.assessment_type.in_(['PRE', 'LESSON_PRE'])))
                else:
                    query = query.filter(CourseAssessment.assessment_type.in_(['PRE', 'LESSON_PRE']))
        elif is_course_end:
            query = query.filter(CourseAssessment.assessment_type == 'COURSE_END')
        else:
            first_lesson = CourseLesson.query.filter_by(course_id=course.id).order_by(CourseLesson.lesson_number.asc()).first()
            if first_lesson:
                query = query.filter((CourseAssessment.lesson_id == first_lesson.id) & (CourseAssessment.assessment_type.in_(['POST', 'LESSON_POST'])))
            else:
                query = query.filter(CourseAssessment.assessment_type.in_(['POST', 'LESSON_POST']))

    raw_questions = query.order_by(CourseAssessment.serial_number.asc(), CourseAssessment.id.asc()).all()

    # Deduplicate questions by question text to ensure no repeated questions appear
    seen_texts = set()
    questions = []
    for q in raw_questions:
        norm_text = (q.question or '').strip().lower()
        if norm_text not in seen_texts:
            seen_texts.add(norm_text)
            questions.append(q)

    # Fallback: if specific lesson query yielded no questions, filter broadly by type without mixing types
    if not questions:
        if type_upper in ['PRE', 'LESSON_PRE']:
            raw_fallback = CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type.in_(['PRE', 'LESSON_PRE']))).order_by(CourseAssessment.serial_number.asc()).all()
        elif is_course_end:
            raw_fallback = CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type.in_(['COURSE_END', 'POST']))).order_by(CourseAssessment.serial_number.asc()).all()
        else:
            raw_fallback = []
        
        seen_texts_fb = set()
        for q in raw_fallback:
            norm_text = (q.question or '').strip().lower()
            if norm_text not in seen_texts_fb:
                seen_texts_fb.add(norm_text)
                questions.append(q)

    if request.method == 'POST':
        user_answers = request.form.to_dict()
        score_pct, passed, total, correct = evaluate_assessment(questions, user_answers, pass_percentage=course.pass_percentage)

        if type_upper in ['PRE', 'LESSON_PRE']:
            passed = True

        if is_course_end:
            enrollment.attempts_count += 1
            attempt_num = enrollment.attempts_count
        else:
            attempt_num = AssessmentAttempt.query.filter_by(enrollment_id=enrollment.id, assessment_type=type_upper).count() + 1

        les_id_val = int(lesson_id_param) if lesson_id_param and str(lesson_id_param).isdigit() else None
        les_obj_val = CourseLesson.query.get(les_id_val) if les_id_val else None
        les_num_val = les_obj_val.lesson_number if les_obj_val else 1

        attempt = AssessmentAttempt(
            enrollment_id=enrollment.id,
            assessment_type=type_upper,
            score_percentage=score_pct,
            passed=passed,
            attempt_number=attempt_num,
            lesson_id=les_id_val,
            lesson_number=les_num_val
        )
        db.session.add(attempt)

        if is_course_end:
            enrollment.final_score = score_pct
            if not passed:
                if enrollment.attempts_count >= 3:
                    enrollment.completion_status = 'Failed'

        db.session.commit()

        # Redirect to result page instead of a plain flash message
        if is_course_end:
            if passed:
                flash(f"Congratulations! You passed the Course-End Assessment with {score_pct}%. Please submit the Course Feedback form below to complete your course and receive your certificate!", "success")
            else:
                flash(f"Course-End Assessment score: {score_pct}% ({correct}/{total}). Pass mark is {course.pass_percentage}%. Attempts remaining: {max(0, 3 - enrollment.attempts_count)}.", "warning" if enrollment.attempts_count < 3 else "danger")
            if live_class:
                return redirect(url_for('learners.class_flow', class_id_str=live_class.class_id))
            else:
                return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))
        else:
            # Show per-question result breakdown
            return render_template(
                'learner_portal/assessment_result.html',
                course=course,
                live_class=live_class,
                assessment_type=type_upper,
                questions=questions,
                user_answers=user_answers,
                score_pct=score_pct,
                passed=passed,
                correct=correct,
                total=total
            )

    return render_template(
        'learner_portal/assessment.html',
        course=course,
        assessment_type=assessment_type,
        questions=questions,
        live_class=live_class
    )


@learners_bp.route('/submit_feedback/<int:repo_id>', methods=['GET', 'POST'])
def submit_feedback(repo_id):
    learner_id = session.get('learner_id')
    if not learner_id:
        return redirect(url_for('auth.learner_login'))

    repo = FeedbackRepository.query.get_or_404(repo_id)
    class_id_str = request.args.get('class_id')
    course_id_param = request.args.get('course_id')

    live_class = None
    if class_id_str:
        if str(class_id_str).isdigit():
            live_class = LiveClass.query.get(int(class_id_str))
        if not live_class:
            live_class = LiveClass.query.filter_by(class_id=class_id_str).first()

    course = None
    enrollment = None

    if live_class:
        course = live_class.course
        enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=course.id, class_id=live_class.id).first()
        if not enrollment:
            enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=course.id).first()
    elif course_id_param:
        if str(course_id_param).isdigit():
            course = Course.query.get(int(course_id_param))
        if not course:
            course = Course.query.filter_by(course_id=course_id_param).first()
        if course:
            enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=course.id).first()
    else:
        # Fallback to course linked to repo
        course = Course.query.filter_by(feedback_repo_id=repo.id).first()
        if course:
            enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=course.id).first()

    # Auto-seed default feedback questions if repo has no questions defined
    questions = FeedbackQuestion.query.filter_by(repo_id=repo.id).all()
    if not questions:
        q1 = FeedbackQuestion(repo_id=repo.id, question_text='How would you rate the overall quality of the course content?', question_type='MCQ', options_json=json.dumps(["Excellent", "Good", "Average", "Poor"]))
        q2 = FeedbackQuestion(repo_id=repo.id, question_text='Was the trainer / facilitation clear and engaging?', question_type='MCQ', options_json=json.dumps(["Strongly Agree", "Agree", "Neutral", "Disagree"]))
        q3 = FeedbackQuestion(repo_id=repo.id, question_text='Please share any additional comments or suggestions for improvement.', question_type='Text')
        db.session.add_all([q1, q2, q3])
        db.session.commit()
        questions = [q1, q2, q3]

    if request.method == 'POST':
        resp_dict = request.form.to_dict()

        existing_resp = FeedbackResponse.query.filter_by(
            repo_id=repo.id,
            learner_id=learner_id,
            class_id=live_class.id if live_class else None
        ).first()

        if existing_resp:
            existing_resp.responses_json = json.dumps(resp_dict)
            existing_resp.submitted_at = datetime.utcnow()
        else:
            fb_resp = FeedbackResponse(
                repo_id=repo.id,
                class_id=live_class.id if live_class else None,
                learner_id=learner_id,
                responses_json=json.dumps(resp_dict)
            )
            db.session.add(fb_resp)

        # Trigger Course Completion & Certificate Generation ONLY ON FEEDBACK SUBMISSION
        if enrollment and enrollment.completion_status != 'Completed':
            enrollment.completion_status = 'Completed'
            enrollment.completion_date = datetime.utcnow()
            
            # Gamification: Award 100 points for completing a course
            from app.utils.gamification import award_points
            award_points(learner_id, 100, f"Completing course '{course.name if course else ''}'")

            # Trigger automated Learning Wall post for course completion
            if course:
                try:
                    create_completion_post(learner_id, course.id, final_score=enrollment.final_score)
                except Exception:
                    pass

            # Check if certificate exists/is enabled for this course
            has_cert = getattr(course, 'has_certificate', True) if course else True
            if has_cert and course:
                existing_cert = Certificate.query.filter_by(learner_id=learner_id, course_id=course.id).first()
                if not existing_cert:
                    cert_id = Certificate.generate_certificate_id()
                    cert_filename = f"cert_{cert_id}.pdf"
                    import tempfile
                    from app.services.storage_service import StorageService

                    learner_obj = Learner.query.get(learner_id)
                    date_str = datetime.now().strftime('%d-%b-%Y')
                    
                    try:
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
                            tmp_path = tmp_file.name
                        generate_certificate_pdf(learner_obj.name, course.name, date_str, cert_id, tmp_path)
                        
                        # Upload to StorageService
                        with open(tmp_path, 'rb') as f_obj:
                            class MockFileObj:
                                def __init__(self, f_obj, c_type):
                                    self.f = f_obj
                                    self.content_type = c_type
                                def read(self, *args): return self.f.read(*args)
                                def seek(self, *args): return self.f.seek(*args)
                                def save(self, path):
                                    with open(path, 'wb') as out:
                                        out.write(self.f.read())
                            mock_file = MockFileObj(f_obj, 'application/pdf')
                            StorageService.upload_file(mock_file, cert_filename, folder='certificates')
                        os.unlink(tmp_path)
                    except Exception:
                        pass

                    cert = Certificate(
                        certificate_id=cert_id,
                        learner_id=learner_id,
                        course_id=course.id,
                        pdf_filename=cert_filename
                    )
                    db.session.add(cert)
                    
                    from app.utils.gamification import award_points
                    award_points(learner_id, 100, "Earning a Course Certificate")
                    
                    flash("Thank you! Feedback recorded. Your course is marked as COMPLETED and Certificate generated!", "success")
                else:
                    flash("Thank you! Feedback recorded. Your course is marked as COMPLETED!", "success")
            else:
                flash("Thank you! Feedback recorded. Your course is marked as COMPLETED!", "success")

        db.session.commit()

        if live_class:
            return redirect(url_for('learners.class_flow', class_id_str=live_class.class_id))
        elif course:
            return redirect(url_for('learners.self_paced_flow', course_id_str=course.course_id))
        else:
            return redirect(url_for('learners.my_portal'))

    existing_resp = FeedbackResponse.query.filter_by(
        repo_id=repo.id,
        learner_id=learner_id,
        class_id=live_class.id if live_class else None
    ).first()

    saved_responses = {}
    if existing_resp and existing_resp.responses_json:
        try:
            saved_responses = json.loads(existing_resp.responses_json)
        except Exception:
            saved_responses = {}

    return render_template(
        'learner_portal/feedback.html',
        repo=repo,
        questions=questions,
        live_class=live_class,
        course=course,
        saved_responses=saved_responses,
        is_submitted=bool(existing_resp)
    )


from app import csrf

@learners_bp.route('/scorm/progress', methods=['POST'])
@csrf.exempt
def save_scorm_progress():
    learner_id = session.get('learner_id')
    if not learner_id:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    data = request.get_json() or {}
    lesson_id = data.get('lesson_id')
    status = data.get('status', '').lower() # 'completed', 'passed', 'failed'

    if not lesson_id:
        return jsonify({'status': 'error', 'message': 'Missing lesson_id'}), 400

    lesson = CourseLesson.query.get_or_404(lesson_id)

    if status in ['completed', 'passed']:
        # Find the learner's enrollment for this course
        enrollment = LearnerEnrollment.query.filter_by(learner_id=learner_id, course_id=lesson.course_id).first()
        if enrollment:
            rev = LessonReview.query.filter_by(enrollment_id=enrollment.id, lesson_id=lesson.id).first()
            if not rev:
                rev = LessonReview(
                    enrollment_id=enrollment.id,
                    lesson_id=lesson.id
                )
                db.session.add(rev)
                db.session.commit()

    return jsonify({'status': 'success', 'lesson_id': lesson.id, 'scorm_status': status})


@learners_bp.route('/grant_extension/<int:enrollment_id>', methods=['POST'])
def grant_extension(enrollment_id):
    """
    Learner Portal: Route for managers to grant an extension to their subordinates.
    """
    manager_learner_id = session.get('learner_id')
    if not manager_learner_id:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    manager = Learner.query.get_or_404(manager_learner_id)
    enrollment = LearnerEnrollment.query.get_or_404(enrollment_id)
    subordinate = enrollment.learner

    # Verify relationship: subordinate must report to manager
    if subordinate.manager_id != manager.id:
        return jsonify({'status': 'error', 'message': 'Permission denied. This learner does not report to you.'}), 403

    extension_date_str = request.form.get('extension_date')
    if not extension_date_str:
        return jsonify({'status': 'error', 'message': 'Please select a valid extension date.'}), 400

    try:
        ext_date = datetime.strptime(extension_date_str, '%Y-%m-%d')
        # Set to end of day
        ext_datetime = datetime(ext_date.year, ext_date.month, ext_date.day, 23, 59, 59)
    except ValueError:
        return jsonify({'status': 'error', 'message': 'Invalid date format.'}), 400

    enrollment.extended_deadline = ext_datetime
    enrollment.extension_requested = False # Clear the request flag

    # Create a notification for the learner
    from app.models.notification import LearnerNotification
    notif = LearnerNotification(
        learner_id=subordinate.id,
        course_id=enrollment.course_id,
        title=f"Course Extension Granted: {enrollment.course.name}",
        message=f"Your manager {manager.name} has granted you an extension for '{enrollment.course.name}' until {ext_date.strftime('%d-%b-%Y')}.",
        notification_type='LESSON_UPDATED'
    )
    db.session.add(notif)
    db.session.commit()

    flash(f"Granted course extension to {subordinate.name} until {ext_date.strftime('%d-%b-%Y')}.", "success")
    return redirect(url_for('learners.my_portal'))


@learners_bp.route('/reject_extension/<int:enrollment_id>', methods=['POST'])
def reject_extension(enrollment_id):
    """
    Learner Portal: Route for managers to reject an extension request from their subordinates.
    """
    manager_learner_id = session.get('learner_id')
    if not manager_learner_id:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401

    manager = Learner.query.get_or_404(manager_learner_id)
    enrollment = LearnerEnrollment.query.get_or_404(enrollment_id)
    subordinate = enrollment.learner

    # Verify relationship
    if subordinate.manager_id != manager.id:
        return jsonify({'status': 'error', 'message': 'Permission denied. This learner does not report to you.'}), 403

    enrollment.extension_requested = False # Clear the request flag
    
    # Create a notification for the learner
    from app.models.notification import LearnerNotification
    notif = LearnerNotification(
        learner_id=subordinate.id,
        course_id=enrollment.course_id,
        title=f"Extension Request Declined: {enrollment.course.name}",
        message=f"Your manager {manager.name} has declined your extension request for '{enrollment.course.name}'.",
        notification_type='LESSON_UPDATED'
    )
    db.session.add(notif)
    db.session.commit()

    flash(f"Declined extension request for {subordinate.name}.", "info")
    return redirect(url_for('learners.my_portal'))


@learners_bp.route('/request_extension/<int:enrollment_id>', methods=['POST'])
def request_extension(enrollment_id):
    """
    Learner Portal: Route for learners to request an extension from their reporting manager.
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to request an extension.", "danger")
        return redirect(url_for('auth.learner_login'))

    learner = Learner.query.get_or_404(learner_id)
    enrollment = LearnerEnrollment.query.get_or_404(enrollment_id)

    if enrollment.learner_id != learner.id:
        flash("You are not authorized to make this request.", "danger")
        return redirect(url_for('learners.my_portal'))

    if not learner.manager_id:
        enrollment.extension_requested = True
        from app.models.issue import LmsIssue
        issue = LmsIssue(
            learner_id=learner.id,
            category='Technical',
            description=f"[Escalation] Extension requested for course '{enrollment.course.name}' (Enrollment ID: {enrollment.id}) by learner {learner.name} (Global ID: {learner.global_id}) due to no mapped manager.",
            status='Open'
        )
        db.session.add(issue)
        db.session.commit()
        flash(f"Extension request for '{enrollment.course.name}' has been escalated to the L&D Administrator because you do not have a reporting manager mapped.", "success")
        return redirect(url_for('learners.my_portal'))

    enrollment.extension_requested = True

    # Create a notification for the manager
    from app.models.notification import LearnerNotification
    notif = LearnerNotification(
        learner_id=learner.manager_id,
        course_id=enrollment.course_id,
        title="Course Extension Requested",
        message=f"{learner.name} has requested a deadline extension for '{enrollment.course.name}'.",
        notification_type='LESSON_UPDATED'
    )
    db.session.add(notif)
    db.session.commit()

    flash(f"Extension request for '{enrollment.course.name}' sent to your manager {learner.manager.name}.", "success")
    return redirect(url_for('learners.my_portal'))


@learners_bp.route('/complete_flashcards/<int:course_id>', methods=['POST'])
def complete_flashcards(course_id):
    """
    Learner Portal: Route to mark flashcards completed, award points and badge.
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        return jsonify({'status': 'error', 'message': 'Not logged in'}), 401
        
    from app.utils.gamification import award_points, award_badge
    
    # Award points and the "Flashcard Pro" badge
    award_points(learner_id, 20, "Completing Course Flashcards Set")
    award_badge(learner_id, "Flashcard Pro 🗂️", "fa-clone", "Completed study flashcards review!")
    
    return jsonify({
        'status': 'success',
        'message': 'Congratulations! You earned 20 points and unlocked the Flashcard Pro badge!'
    })


@learners_bp.route('/set_theme', methods=['POST'])
def set_theme():
    """
    Learner Portal: Route to save layout theme choice.
    """
    theme = request.json.get('theme', 'navy').strip()
    valid_themes = ['navy', 'emerald', 'sunset', 'purple', 'dark']
    if theme not in valid_themes:
        return jsonify({'status': 'error', 'message': 'Invalid theme selection'}), 400
        
    session['learner_theme'] = theme
    
    learner_id = session.get('learner_id')
    if learner_id:
        learner = Learner.query.get(learner_id)
        if learner:
            learner.theme = theme
            db.session.commit()
            
    return jsonify({'status': 'success', 'theme': theme})
    return jsonify({'status': 'error', 'message': 'Learner not found'}), 404


@learners_bp.route('/raise_issue', methods=['POST'])
def raise_issue():
    """
    Learner Portal: Submit a technical or content support issue.
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to submit an issue.", "danger")
        return redirect(url_for('auth.learner_login'))
        
    category = request.form.get('category', 'Technical').strip()
    description = request.form.get('description', '').strip()
    
    if not description:
        flash("Description is required.", "danger")
        return redirect(url_for('learners.my_portal'))
        
    from app.models.issue import LmsIssue
    issue = LmsIssue(
        learner_id=learner_id,
        category=category,
        description=description,
        status='Open'
    )
    db.session.add(issue)
    db.session.commit()
    
    flash("Your support ticket has been submitted successfully. L&D Admin has been notified!", "success")
    return redirect(url_for('learners.my_portal'))


@learners_bp.route('/tag_suggestions')
def tag_suggestions():
    """
    Returns autocomplete suggestions for learner names,
    prioritizing colleagues from the same department/team.
    """
    query = request.args.get('q', '').strip().lower()
    if not query:
        return jsonify([])
        
    current_learner_id = session.get('learner_id')
    current_dept = None
    if current_learner_id:
        current_learner = Learner.query.get(current_learner_id)
        if current_learner:
            current_dept = current_learner.department
            
    # Fetch matching learners
    matches = Learner.query.filter(Learner.name.ilike(f'%{query}%')).all()
    
    # Sort: same department first, then alphabetical
    def sort_key(learner):
        is_same_dept = (current_dept and learner.department == current_dept)
        return (0 if is_same_dept else 1, learner.name.lower())
        
    matches.sort(key=sort_key)
    
    results = []
    for l in matches:
        results.append({
            'global_id': l.global_id,
            'name': l.name,
            'department': l.department or 'L&D'
        })
        
    return jsonify(results)


@learners_bp.route('/catalog')
def catalog():
    """
    Learner Portal: Standalone Course Catalog page with search & filters.
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to view the Course Catalog.", "warning")
        return redirect(url_for('auth.learner_login'))
        
    learner = Learner.query.get_or_404(learner_id)
    search_query = request.args.get('search', '').strip().lower()
    mode_filter = request.args.get('mode', 'ALL').strip()
    
    # Retrieve all non-archived courses
    query = Course.query.filter_by(is_archived=False)
    if mode_filter and mode_filter != 'ALL':
        query = query.filter_by(mode=mode_filter)
        
    courses = query.order_by(Course.name).all()
    
    # Filter by search string in python for simplicity
    filtered_courses = []
    for c in courses:
        if search_query:
            if search_query not in c.name.lower() and (c.description and search_query not in c.description.lower()):
                continue
        filtered_courses.append(c)
        
    # Get active enrollments to flag "Enrolled" courses
    from app.models.enrollment import LearnerEnrollment
    enrolls = LearnerEnrollment.query.filter_by(learner_id=learner_id).all()
    enrolled_course_ids = {e.course_id for e in enrolls}
    
    return render_template(
        'learner_portal/catalog.html',
        learner=learner,
        courses=filtered_courses,
        enrolled_course_ids=enrolled_course_ids,
        search_query=search_query,
        mode_filter=mode_filter
    )


@learners_bp.route('/profile', methods=['GET', 'POST'])
def view_learner_profile():
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to view your profile.", "danger")
        return redirect(url_for('auth.learner_login'))
        
    learner = Learner.query.get_or_404(learner_id)
    
    if request.method == 'POST':
        dob_str = request.form.get('date_of_birth')
        profile_pic = request.files.get('profile_picture')
        
        updated = False
        
        if dob_str:
            try:
                learner.date_of_birth = datetime.strptime(dob_str, '%Y-%m-%d').date()
                updated = True
                # Check if it's their birthday today to trigger the post
                from app.services.learning_wall_service import check_and_generate_birthday_posts
                check_and_generate_birthday_posts()
            except ValueError:
                flash("Invalid Date Format. Please try again.", "danger")
                
        if profile_pic and profile_pic.filename:
            from werkzeug.utils import secure_filename
            import uuid
            import os
            from flask import current_app
            
            ext = os.path.splitext(profile_pic.filename)[1]
            pic_filename = f"profile_{learner.id}_{uuid.uuid4().hex[:8]}{ext}"
            from app.services.storage_service import StorageService
            StorageService.upload_file(profile_pic, pic_filename, folder='profiles')
            learner.profile_picture = pic_filename
            updated = True

        if updated:
            db.session.commit()
            flash("Your profile has been updated!", "success")
            
        return redirect(url_for('learners.view_learner_profile'))
    
    # Get active/completed enrollments count
    total_enrollments = LearnerEnrollment.query.filter_by(learner_id=learner.id).count()
    completed_enrollments = LearnerEnrollment.query.filter_by(learner_id=learner.id, completion_status='Completed').count()    
    
    return render_template(
        'learner_portal/profile.html',
        learner=learner,
        total_enrollments=total_enrollments,
        completed_enrollments=completed_enrollments,
        certificates=certificates,
        recent_activities=recent_activities,
        learner_theme=learner_theme
    )


@learners_bp.route('/profile_picture/<filename>')
def download_profile_pic(filename):
    from app.services.storage_service import StorageService
    url = StorageService.get_file_url(filename, 'profiles')
    if url:
        return redirect(url)
    # Local fallback
    from flask import send_from_directory, current_app
    import os
    upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'profiles')
    return send_from_directory(upload_dir, filename)
