import os
from datetime import datetime
from app.utils.decorators import admin_required
import uuid
import json
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session, send_file, current_app, send_from_directory
from app.models import db
from app.models.course import Course, CourseAssessment, CourseMaterial, CourseLesson, LessonCourseware, CoursewareAudioTrack, RiseCoursewareVersion, LearnerBlockProgress
from app.models.live_class import LiveClass
from app.services.assessment_service import parse_assessment_csv
from app.services.report_service import generate_course_analytics_csv, generate_class_attendance_csv
from app.utils.pptx_parser import parse_pptx_slides
from app.utils.slide_renderer import render_pdf_to_slide_images

courses_bp = Blueprint('courses', __name__)

def format_youtube_embed(url):
    if not url:
        return url
    if 'youtube.com/watch?v=' in url:
        video_id = url.split('v=')[1].split('&')[0]
        return f"https://www.youtube.com/embed/{video_id}"
    elif 'youtu.be/' in url:
        video_id = url.split('youtu.be/')[1].split('?')[0]
        return f"https://www.youtube.com/embed/{video_id}"
    return url

@courses_bp.route('/')
@admin_required
def list_courses():

    search_query = request.args.get('search', '').strip()
    mode_filter = request.args.get('mode', '').strip()
    page = request.args.get('page', 1, type=int)

    show_archived = request.args.get('show_archived', '0') == '1'
    query = Course.query.filter_by(is_archived=show_archived)

    if search_query:
        query = query.filter(
            (Course.name.ilike(f'%{search_query}%')) |
            (Course.course_id.ilike(f'%{search_query}%')) |
            (Course.description.ilike(f'%{search_query}%')) |
            (Course.mode.ilike(f'%{search_query}%'))
        )

    if mode_filter and mode_filter != 'ALL':
        query = query.filter_by(mode=mode_filter)

    courses = query.order_by(Course.id.desc()).paginate(page=page, per_page=20, error_out=False)
    return render_template('courses/list.html', courses=courses, search_query=search_query, mode_filter=mode_filter, show_archived=show_archived)


@courses_bp.route('/create', methods=['GET', 'POST'])
@admin_required
def create_course():

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        mode = request.form.get('mode', 'Live').strip()
        pass_percentage = float(request.form.get('pass_percentage', 80.0))
        fb_id = request.form.get('feedback_repo_id')
        feedback_repo_id = int(fb_id) if fb_id else None
        has_certificate = (request.form.get('has_certificate', '1') == '1')
        is_sequential = (request.form.get('is_sequential', '1') == '1')
        comp_date_str = request.form.get('completion_date', '').strip()
        completion_date = None
        if comp_date_str:
            try:
                completion_date = datetime.strptime(comp_date_str, '%Y-%m-%d')
            except Exception:
                completion_date = None

        if not name:
            flash('Course Name is required.', 'danger')
            return redirect(url_for('courses.create_course'))

        course_id = Course.generate_course_id(mode)
        new_course = Course(
            course_id=course_id,
            name=name,
            duration_hours=0.0, # Auto-calculated when lessons are added
            description=description,
            mode=mode,
            pass_percentage=pass_percentage,
            feedback_repo_id=feedback_repo_id,
            has_certificate=has_certificate,
            is_sequential=is_sequential,
            completion_date=completion_date
        )
        db.session.add(new_course)
        db.session.commit()

        # Handle Thumbnail Upload
        thumb_file = request.files.get('thumbnail_file')
        if thumb_file and thumb_file.filename:
            ext = os.path.splitext(thumb_file.filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                thumb_filename = f"thumb_{new_course.course_id}_{uuid.uuid4().hex[:8]}{ext}"
                thumb_dir = os.path.join(current_app.root_path, '..', 'uploads', 'thumbnails')
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_file.save(os.path.join(thumb_dir, thumb_filename))
                new_course.thumbnail_filename = thumb_filename

        # Live Online & Live In Person duration set directly by admin at course level
        if mode in ['Live Online', 'Live In Person']:
            try:
                new_course.duration_hours = float(request.form.get('duration_hours', 1.0))
            except Exception:
                new_course.duration_hours = 1.0

        # Handle CSV uploads enforcing mode-based assessment availability
        summative_file = request.files.get('summative_assessment_csv') or request.files.get('course_end_assessment_csv')
        pre_file = request.files.get('pre_assessment_csv')
        post_file = request.files.get('post_assessment_csv')

        summative_errs, pre_errs, post_errs = [], [], []

        # 1. Course End Assessment (Available for all course modes)
        if summative_file and summative_file.filename:
            q_list, errs = parse_assessment_csv(summative_file.stream, filename=summative_file.filename)
            if errs:
                summative_errs = errs
            else:
                for q in q_list:
                    assessment = CourseAssessment(
                        course_id=new_course.id,
                        assessment_type='COURSE_END',
                        serial_number=q['serial_number'],
                        question=q['question'],
                        option1=q['option1'],
                        option2=q['option2'],
                        option3=q['option3'],
                        option4=q['option4'],
                        correct_option=q['correct_option']
                    )
                    db.session.add(assessment)

        # 2. Pre Course Assessment (Available for all course modes)
        if pre_file and pre_file.filename:
            q_list, errs = parse_assessment_csv(pre_file.stream, filename=pre_file.filename)
            if errs:
                pre_errs = errs
            else:
                for q in q_list:
                    assessment = CourseAssessment(
                        course_id=new_course.id,
                        assessment_type='PRE',
                        serial_number=q['serial_number'],
                        question=q['question'],
                        option1=q['option1'],
                        option2=q['option2'],
                        option3=q['option3'],
                        option4=q['option4'],
                        correct_option=q['correct_option']
                    )
                    db.session.add(assessment)

            if post_file and post_file.filename:
                q_list, errs = parse_assessment_csv(post_file.stream, filename=post_file.filename)
                if errs:
                    post_errs = errs
                else:
                    for q in q_list:
                        assessment = CourseAssessment(
                            course_id=new_course.id,
                            assessment_type='POST',
                            serial_number=q['serial_number'],
                            question=q['question'],
                            option1=q['option1'],
                            option2=q['option2'],
                            option3=q['option3'],
                            option4=q['option4'],
                            correct_option=q['correct_option']
                        )
                        db.session.add(assessment)

        db.session.commit()

        if summative_errs or pre_errs or post_errs:
            flash(f"Course created ({course_id}), but CSV had errors: Summative ({len(summative_errs)}), Pre ({len(pre_errs)}), Post ({len(post_errs)}).", "warning")
        else:
            flash(f"Course {course_id} - {name} created successfully!", "success")

        return redirect(url_for('courses.view_course', course_id=new_course.id))

    from app.models.feedback import FeedbackRepository
    feedback_repos = FeedbackRepository.query.all()
    auto_id = Course.generate_course_id('Self Paced')
    return render_template('courses/create_edit.html', auto_id=auto_id, course=None, feedback_repos=feedback_repos)


@courses_bp.route('/generate_id')
@admin_required
def generate_course_id_api():
    mode = request.args.get('mode', 'Self Paced').strip()
    return jsonify({'course_id': Course.generate_course_id(mode)})


@courses_bp.route('/<int:course_id>')
@admin_required
def view_course(course_id):

    course = Course.query.get_or_404(course_id)
    pre_questions = CourseAssessment.query.filter_by(course_id=course.id, assessment_type='PRE').order_by(CourseAssessment.serial_number.asc()).all()
    post_questions = CourseAssessment.query.filter_by(course_id=course.id, assessment_type='POST').order_by(CourseAssessment.serial_number.asc()).all()
    course_end_questions = CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type == 'COURSE_END')).order_by(CourseAssessment.serial_number.asc()).all()
    
    # Lessons created inside this course
    lessons = CourseLesson.query.filter_by(course_id=course.id).order_by(CourseLesson.lesson_number.asc()).all()

    # Classes created inside this course
    from app.models.live_class import LiveClass
    from app.models.feedback import FeedbackRepository
    from app.services.qr_service import generate_class_qr

    live_classes = LiveClass.query.filter_by(course_id=course.id).order_by(LiveClass.class_date.desc()).all()
    
    for cls in live_classes:
        generate_class_qr(cls.class_id)

    from app.models.user import Learner
    feedback_repos = FeedbackRepository.query.all()
    learners = Learner.query.order_by(Learner.name.asc()).all()

    return render_template(
        'courses/detail.html',
        course=course,
        pre_questions=pre_questions,
        post_questions=post_questions,
        course_end_questions=course_end_questions,
        lessons=lessons,
        live_classes=live_classes,
        feedback_repos=feedback_repos,
        learners=learners
    )


def recalculate_course_duration(course_id):
    course = Course.query.get(course_id)
    if course and course.mode != 'Live Online':
        lessons = CourseLesson.query.filter_by(course_id=course.id).all()
        if lessons:
            course.duration_hours = round(sum(l.duration_hours for l in lessons if l.duration_hours is not None), 2)
        else:
            course.duration_hours = 0.0
        db.session.commit()


@courses_bp.route('/thumbnail/<filename>')
def download_thumbnail(filename):
    thumb_dir = os.path.join(current_app.root_path, '..', 'uploads', 'thumbnails')
    file_path = os.path.join(thumb_dir, filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    return redirect(url_for('static', filename='images/default_course_thumb.png'))


@courses_bp.route('/<int:course_id>/add_lesson', methods=['POST'])
@admin_required
def add_lesson(course_id):
    """
    Add a new Lesson / Module directly inside a Course in a single step,
    including optional Lesson Pre-Assessment CSV, Non-Downloadable Courseware, and Post-Assessment CSV.
    """

    course = Course.query.get_or_404(course_id)
    title = request.form.get('title', '').strip()
    summary = request.form.get('summary', '').strip()
    content = request.form.get('content', '').strip()
    video_url = request.form.get('video_url', '').strip()
    lesson_number = int(request.form.get('lesson_number', len(course.lessons) + 1))
    duration_hours = float(request.form.get('duration_hours', 1.0))
    min_time_minutes = float(request.form.get('min_time_minutes', 1.0))
    deadline_str = request.form.get('deadline', '').strip()
    deadline = None
    if deadline_str:
        try:
            deadline = datetime.strptime(deadline_str, '%Y-%m-%d')
        except Exception:
            deadline = None

    if not title:
        flash("Lesson title is required.", "danger")
        return redirect(url_for('courses.view_course', course_id=course.id))

    cw_type = request.form.get('courseware_type', 'Video URL').strip()
    external_url = request.form.get('external_url', '').strip() or request.form.get('video_url', '').strip()
    if external_url:
        from app.services.gdrive_service import parse_gdrive_url
        is_gd, emb_url, g_type, file_id = parse_gdrive_url(external_url)
        if is_gd:
            external_url = emb_url
            if cw_type in ['Auto', 'Video URL', 'Google Drive', '']:
                cw_type = f"Google Drive ({g_type})"
        else:
            external_url = format_youtube_embed(external_url)

    lesson = CourseLesson(
        course_id=course.id,
        lesson_number=lesson_number,
        title=title,
        summary=summary,
        content=content,
        video_url=None,
        duration_hours=duration_hours,
        min_time_minutes=min_time_minutes,
        deadline=deadline
    )
    db.session.add(lesson)
    db.session.flush() # Generate lesson.id

    # 1. Handle Lesson Pre-Assessment CSV
    pre_csv = request.files.get('pre_assessment_csv')
    if pre_csv and pre_csv.filename:
        q_list, errs = parse_assessment_csv(pre_csv.stream, filename=pre_csv.filename)
        if not errs:
            for q in q_list:
                ass = CourseAssessment(
                    course_id=course.id,
                    lesson_id=lesson.id,
                    assessment_type='LESSON_PRE',
                    serial_number=q['serial_number'],
                    question=q['question'],
                    option1=q['option1'],
                    option2=q['option2'],
                    option3=q['option3'],
                    option4=q['option4'],
                    correct_option=q['correct_option'],
                    lesson_number=lesson_number
                )
                db.session.add(ass)

    # 2. Handle Non-Downloadable Lesson Courseware File / Text / Video URL
    cw_file = request.files.get('courseware_file')
    cw_title = request.form.get('courseware_title', '').strip() or f"{title} Courseware"
    cw_text = request.form.get('courseware_text', '').strip()

    filename = None
    if cw_file and cw_file.filename:
        ext = os.path.splitext(cw_file.filename)[1].lower()
        short_id = uuid.uuid4().hex[:8]
        filename = f"cw_{lesson.id}_{short_id}{ext}"
        save_path = os.path.join(current_app.config['MATERIALS_FOLDER'], filename)
        cw_file.save(save_path)

        mat = CourseMaterial(
            course_id=course.id,
            title=f"[Lesson {lesson_number}] {cw_title}",
            material_type='Video' if ext in ['.mp4', '.webm'] else ('PDF' if ext == '.pdf' else 'PPT'),
            filename=filename,
            allow_download=False # Non-downloadable
        )
        db.session.add(mat)

    if filename or cw_text or external_url:
        cw = LessonCourseware(
            lesson_id=lesson.id,
            title=cw_title,
            courseware_type=cw_type,
            filename=filename,
            external_url=external_url if external_url else None,
            content_text=cw_text if cw_text else None
        )
        db.session.add(cw)

    # 3. Handle Lesson Post-Assessment CSV
    post_csv = request.files.get('post_assessment_csv')
    if post_csv and post_csv.filename:
        q_list, errs = parse_assessment_csv(post_csv.stream, filename=post_csv.filename)
        if not errs:
            for q in q_list:
                ass = CourseAssessment(
                    course_id=course.id,
                    lesson_id=lesson.id,
                    assessment_type='LESSON_POST',
                    serial_number=q['serial_number'],
                    question=q['question'],
                    option1=q['option1'],
                    option2=q['option2'],
                    option3=q['option3'],
                    option4=q['option4'],
                    correct_option=q['correct_option'],
                    lesson_number=lesson_number
                )
                db.session.add(ass)

    # Notify enrolled learners about new/updated lesson
    from app.models.notification import LearnerNotification
    for en in course.enrollments:
        notif = LearnerNotification(
            learner_id=en.learner_id,
            course_id=course.id,
            lesson_id=lesson.id,
            title=f"Lesson Updated: {title}",
            message=f"Lesson #{lesson_number} '{title}' has been added/updated in '{course.name}'.",
            notification_type='LESSON_UPDATED'
        )
        db.session.add(notif)

    db.session.commit()
    recalculate_course_duration(course.id)

    flash(f"Lesson #{lesson_number} '{title}' ({duration_hours} hrs) created and course total duration auto-updated!", "success")
    return redirect(url_for('courses.view_course', course_id=course.id))


@courses_bp.route('/<int:course_id>/clear_lessons', methods=['POST'])
@admin_required
def clear_lessons(course_id):
    """
    Admin Route: Remove all existing lessons for a course.
    """

    course = Course.query.get_or_404(course_id)
    # Remove all lessons (cascades courseware & lesson assessments)
    CourseLesson.query.filter_by(course_id=course.id).delete()
    db.session.commit()
    recalculate_course_duration(course.id)

    flash(f"All existing lessons cleared for course '{course.name}'.", "info")
    return redirect(url_for('courses.view_course', course_id=course.id))


@courses_bp.route('/lesson/<int:lesson_id>/delete', methods=['POST'])
@admin_required
def delete_lesson(lesson_id):
    """
    Admin Route: Delete an individual lesson and all its attached courseware & assessments.
    """

    lesson = CourseLesson.query.get_or_404(lesson_id)
    course_id = lesson.course_id
    lesson_title = lesson.title
    
    # Delete linked assessments and courseware
    CourseAssessment.query.filter_by(lesson_id=lesson.id).delete()
    LessonCourseware.query.filter_by(lesson_id=lesson.id).delete()
    db.session.delete(lesson)
    db.session.commit()
    recalculate_course_duration(course_id)

    flash(f"Lesson '{lesson_title}' deleted and course total duration auto-updated.", "success")
    return redirect(url_for('courses.view_course', course_id=course_id))


@courses_bp.route('/lesson/<int:lesson_id>/add_courseware', methods=['POST'])
@admin_required
def add_lesson_courseware(lesson_id):
    """
    Attach Non-Downloadable Courseware (Video, PDF view, PPT slides, SCORM, Text) to a Lesson.
    """

    lesson = CourseLesson.query.get_or_404(lesson_id)
    title = request.form.get('title', '').strip()
    c_type = request.form.get('courseware_type', 'Video URL').strip()
    external_url = request.form.get('external_url', '').strip()
    if external_url:
        from app.services.gdrive_service import parse_gdrive_url
        is_gd, emb_url, g_type, file_id = parse_gdrive_url(external_url)
        if is_gd:
            external_url = emb_url
            if c_type in ['Auto', 'Video URL', '']:
                c_type = f"Google Drive ({g_type})"
        else:
            external_url = format_youtube_embed(external_url)
    content_text = request.form.get('content_text', '').strip()
    file_obj = request.files.get('courseware_file')

    if not title:
        flash("Courseware title is required.", "danger")
        return redirect(url_for('courses.view_course', course_id=lesson.course_id))

    filename = None
    if file_obj and file_obj.filename:
        ext = os.path.splitext(file_obj.filename)[1].lower()
        short_id = uuid.uuid4().hex[:8]
        filename = f"cw_{lesson.id}_{short_id}{ext}"
        
        if c_type == 'SCORM' or ext == '.zip':
            from app.services.scorm_service import process_scorm_package
            scorm_id_str = f"scorm_{short_id}"
            upload_base_folder = os.path.abspath(os.path.join(current_app.root_path, '..', 'uploads'))
            launch_href, err_msg = process_scorm_package(file_obj, scorm_id_str, upload_base_folder)
            if err_msg:
                flash(err_msg, "danger")
                return redirect(url_for('courses.view_course', course_id=lesson.course_id))
            filename = scorm_id_str
            external_url = launch_href
            c_type = 'SCORM'
        else:
            save_path = os.path.join(current_app.config['MATERIALS_FOLDER'], filename)
            file_obj.save(save_path)
            
            # Also create a non-downloadable CourseMaterial record for inline viewing
            mat = CourseMaterial(
                course_id=lesson.course_id,
                title=f"[Lesson {lesson.lesson_number} Courseware] {title}",
                material_type='Video' if ext in ['.mp4', '.webm'] else ('PDF' if ext == '.pdf' else 'PPT'),
                filename=filename,
                allow_download=False # NON-DOWNLOADABLE as required!
            )
            db.session.add(mat)

    cw = LessonCourseware(
        lesson_id=lesson.id,
        title=title,
        courseware_type=c_type,
        filename=filename,
        external_url=external_url if external_url else None,
        content_text=content_text if content_text else None
    )
    db.session.add(cw)
    db.session.commit()

    flash(f"Non-downloadable courseware '{title}' attached to Lesson #{lesson.lesson_number}.", "success")
    return redirect(url_for('courses.view_course', course_id=lesson.course_id))


@courses_bp.route('/courseware/<int:courseware_id>/add_audio_track', methods=['POST'])
@admin_required
def add_audio_track(courseware_id):
    cw = LessonCourseware.query.get_or_404(courseware_id)
    language_label = request.form.get('language_label', '').strip()
    audio_file = request.files.get('audio_file')
    make_default = request.form.get('make_default') == '1' or len(cw.audio_tracks) == 0

    if not language_label:
        flash("Audio track language label is required (e.g. Telugu, Hindi, Tamil).", "danger")
        return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))

    if not audio_file or not audio_file.filename:
        flash("Please select an audio file (.mp3, .m4a, .aac, .wav).", "danger")
        return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))

    ext = os.path.splitext(audio_file.filename)[1].lower()
    if ext not in ['.mp3', '.m4a', '.aac', '.wav', '.ogg', '.opus', '.flac']:
        flash("Invalid audio format. Please upload an MP3, M4A, AAC, or WAV file.", "danger")
        return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))

    short_id = uuid.uuid4().hex[:8]
    filename = f"audio_{cw.id}_{short_id}{ext}"
    materials_folder = current_app.config['MATERIALS_FOLDER']
    os.makedirs(materials_folder, exist_ok=True)
    file_path = os.path.join(materials_folder, filename)
    audio_file.save(file_path)

    if make_default:
        for t in cw.audio_tracks:
            t.is_default = False

    track = CoursewareAudioTrack(
        courseware_id=cw.id,
        language_label=language_label,
        audio_filename=filename,
        is_default=make_default
    )
    db.session.add(track)
    db.session.commit()

    flash(f"Audio track '{language_label}' added to '{cw.title}'" + (" (Set as Default Audio)." if make_default else "."), "success")
    return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))


@courses_bp.route('/courseware/audio/<int:track_id>/set_default', methods=['POST'])
@admin_required
def set_default_audio_track(track_id):
    if track_id == 0:
        cw_id = request.form.get('courseware_id', type=int)
        cw = LessonCourseware.query.get_or_404(cw_id)
        for t in cw.audio_tracks:
            t.is_default = False
        db.session.commit()
        flash(f"Default audio reset to Original Video Audio for '{cw.title}'.", "success")
        return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))

    track = CoursewareAudioTrack.query.get_or_404(track_id)
    cw = track.courseware
    for t in cw.audio_tracks:
        t.is_default = (t.id == track.id)
    db.session.commit()
    flash(f"'{track.language_label}' set as Default Audio Track for '{cw.title}'.", "success")
    return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))


@courses_bp.route('/courseware/audio/<int:track_id>')
def stream_audio_track(track_id):
    track = CoursewareAudioTrack.query.get_or_404(track_id)
    materials_folder = current_app.config['MATERIALS_FOLDER']
    file_path = os.path.join(materials_folder, track.audio_filename)
    if os.path.exists(file_path):
        ext = os.path.splitext(track.audio_filename)[1].lower()
        mimetypes = {'.mp3': 'audio/mpeg', '.m4a': 'audio/mp4', '.aac': 'audio/aac', '.wav': 'audio/wav', '.ogg': 'audio/ogg'}
        return send_file(file_path, mimetype=mimetypes.get(ext, 'audio/mpeg'))
    return jsonify({'error': 'Audio track file not found'}), 404


@courses_bp.route('/courseware/audio/<int:track_id>/delete', methods=['POST'])
@admin_required
def delete_audio_track(track_id):
    track = CoursewareAudioTrack.query.get_or_404(track_id)
    course_id = track.courseware.lesson.course_id
    materials_folder = current_app.config['MATERIALS_FOLDER']
    file_path = os.path.join(materials_folder, track.audio_filename)
    if os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
    db.session.delete(track)
    db.session.commit()
    flash("Audio track deleted successfully.", "info")
    return redirect(url_for('courses.view_course', course_id=course_id))


@courses_bp.route('/lesson/<int:lesson_id>/upload_assessment', methods=['POST'])
@admin_required
def upload_lesson_assessment(lesson_id):
    """
    Upload CSV questions specifically for a Lesson's Pre-Assessment or Post-Assessment.
    """

    lesson = CourseLesson.query.get_or_404(lesson_id)
    assessment_type = request.form.get('assessment_type', 'LESSON_PRE').strip() # 'LESSON_PRE' or 'LESSON_POST'
    csv_file = request.files.get('assessment_csv')

    if not csv_file or not csv_file.filename:
        flash("Please select a CSV file.", "danger")
        return redirect(url_for('courses.view_course', course_id=lesson.course_id))

    q_list, errs = parse_assessment_csv(csv_file.stream, filename=csv_file.filename)
    if errs:
        flash(f"CSV Errors: {', '.join(errs[:3])}", "danger")
        return redirect(url_for('courses.view_course', course_id=lesson.course_id))

    # Delete existing questions for this lesson & type
    CourseAssessment.query.filter_by(lesson_id=lesson.id, assessment_type=assessment_type).delete()

    for q in q_list:
        assessment = CourseAssessment(
            course_id=lesson.course_id,
            lesson_id=lesson.id,
            assessment_type=assessment_type,
            serial_number=q['serial_number'],
            question=q['question'],
            option1=q['option1'],
            option2=q['option2'],
            option3=q['option3'],
            option4=q['option4'],
            correct_option=q['correct_option'],
            lesson_number=lesson.lesson_number
        )
        db.session.add(assessment)

    db.session.commit()
    flash(f"Successfully uploaded {len(q_list)} questions for Lesson #{lesson.lesson_number} {assessment_type}.", "success")
    return redirect(url_for('courses.view_course', course_id=lesson.course_id))


@courses_bp.route('/<int:course_id>/upload_course_end_assessment', methods=['POST'])
@admin_required
def upload_course_end_assessment(course_id):
    """
    Upload CSV questions for the Course End Assessment.
    """

    course = Course.query.get_or_404(course_id)
    csv_file = request.files.get('assessment_csv')

    if not csv_file or not csv_file.filename:
        flash("Please select a CSV file.", "danger")
        return redirect(url_for('courses.view_course', course_id=course.id))

    q_list, errs = parse_assessment_csv(csv_file.stream, filename=csv_file.filename)
    if errs:
        flash(f"CSV Errors: {', '.join(errs[:3])}", "danger")
        return redirect(url_for('courses.view_course', course_id=course.id))

    CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type.in_(['COURSE_END', 'POST'])) & (CourseAssessment.lesson_id == None)).delete()

    for q in q_list:
        assessment = CourseAssessment(
            course_id=course.id,
            lesson_id=None,
            assessment_type='COURSE_END',
            serial_number=q['serial_number'],
            question=q['question'],
            option1=q['option1'],
            option2=q['option2'],
            option3=q['option3'],
            option4=q['option4'],
            correct_option=q['correct_option']
        )
        db.session.add(assessment)

    from app.models.notification import LearnerNotification
    from app.models.enrollment import AssessmentAttempt
    for en in course.enrollments:
        passed_att = AssessmentAttempt.query.filter_by(enrollment_id=en.id, assessment_type='COURSE_END', passed=True).first()
        if not passed_att:
            en.completion_status = 'In Progress'

        notif = LearnerNotification(
            learner_id=en.learner_id,
            course_id=course.id,
            title=f"Course End Assessment Available: {course.name}",
            message=f"The Course End Assessment CSV question bank ({len(q_list)} questions) has been attached to '{course.name}'.",
            notification_type='ASSESSMENT_UNLOCKED'
        )
        db.session.add(notif)

    db.session.commit()
    flash(f"Uploaded {len(q_list)} questions for Course End Assessment.", "success")
    return redirect(url_for('courses.view_course', course_id=course.id))


@courses_bp.route('/<int:course_id>/create_class', methods=['POST'])
@admin_required
def create_course_class(course_id):
    """
    Schedule a Live Class directly within the Course itself (Merged Course & Class Management).
    """

    course = Course.query.get_or_404(course_id)
    
    from app.models.live_class import LiveClass
    from app.services.qr_service import generate_class_qr

    class_mode = request.form.get('class_mode', 'In Person')
    date_str = request.form.get('class_date')
    from datetime import datetime
    class_date = datetime.strptime(date_str, '%Y-%m-%d').date()

    location = request.form.get('location', '').strip()
    branch = request.form.get('branch', '').strip()
    session_time = request.form.get('session_time', 'Morning').strip()
    meet_link = request.form.get('meet_link', '').strip()

    facilitator_id = int(request.form.get('facilitator_id'))
    co_facilitator_id = request.form.get('co_facilitator_id')
    co_facilitator_id = int(co_facilitator_id) if co_facilitator_id else None
    expected_attendance = int(request.form.get('expected_attendance', 30))
    feedback_repo_id = request.form.get('feedback_repo_id')
    feedback_repo_id = int(feedback_repo_id) if feedback_repo_id else None

    class_id = LiveClass.generate_class_id()

    new_cls = LiveClass(
        class_id=class_id,
        class_name='',
        course_id=course.id,
        class_mode=class_mode,
        class_date=class_date,
        location=location,
        branch=branch,
        session_time=session_time,
        meet_link=meet_link,
        facilitator_id=facilitator_id,
        co_facilitator_id=co_facilitator_id,
        duration_hours=course.duration_hours,
        expected_attendance=expected_attendance,
        feedback_repo_id=feedback_repo_id
    )

    course_code = course.name.split()[0] if course.name else 'CRS'
    new_cls.class_name = new_cls.build_class_name(course_code)

    db.session.add(new_cls)
    db.session.commit()

    generate_class_qr(new_cls.class_id)

    pre_file = request.files.get('pre_assessment_file')
    post_file = request.files.get('post_assessment_file')

    if pre_file and pre_file.filename:
        q_list, errs = parse_assessment_csv(pre_file.stream, filename=pre_file.filename)
        for q in q_list:
            ca = CourseAssessment(
                course_id=course.id,
                assessment_type='PRE',
                serial_number=q.get('serial_number'),
                question=q.get('question'),
                option1=q.get('option1'),
                option2=q.get('option2'),
                option3=q.get('option3'),
                option4=q.get('option4'),
                correct_option=q.get('correct_option')
            )
            db.session.add(ca)

    if post_file and post_file.filename:
        q_list, errs = parse_assessment_csv(post_file.stream, filename=post_file.filename)
        for q in q_list:
            ca = CourseAssessment(
                course_id=course.id,
                assessment_type='POST',
                serial_number=q.get('serial_number'),
                question=q.get('question'),
                option1=q.get('option1'),
                option2=q.get('option2'),
                option3=q.get('option3'),
                option4=q.get('option4'),
                correct_option=q.get('correct_option')
            )
            db.session.add(ca)

    db.session.commit()

    flash(f"Live Class '{new_cls.class_name}' ({new_cls.class_id}) created inside course '{course.name}'!", "success")
    return redirect(url_for('courses.view_course', course_id=course.id))


@courses_bp.route('/<int:course_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_course(course_id):

    course = Course.query.get_or_404(course_id)

    if request.method == 'POST':
        course.name = request.form.get('name', '').strip()
        course.description = request.form.get('description', '').strip()
        course.mode = request.form.get('mode', 'Live').strip()
        course.pass_percentage = float(request.form.get('pass_percentage', 80.0))
        fb_id = request.form.get('feedback_repo_id')
        course.feedback_repo_id = int(fb_id) if fb_id else None
        course.has_certificate = (request.form.get('has_certificate', '1') == '1')
        course.is_sequential = (request.form.get('is_sequential', '1') == '1')
        comp_date_str = request.form.get('completion_date', '').strip()
        if comp_date_str:
            try:
                course.completion_date = datetime.strptime(comp_date_str, '%Y-%m-%d')
            except Exception:
                course.completion_date = None
        else:
            course.completion_date = None

        # Handle Thumbnail Upload
        thumb_file = request.files.get('thumbnail_file')
        if thumb_file and thumb_file.filename:
            ext = os.path.splitext(thumb_file.filename)[1].lower()
            if ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp']:
                thumb_filename = f"thumb_{course.course_id}_{uuid.uuid4().hex[:8]}{ext}"
                thumb_dir = os.path.join(current_app.root_path, '..', 'uploads', 'thumbnails')
                os.makedirs(thumb_dir, exist_ok=True)
                thumb_file.save(os.path.join(thumb_dir, thumb_filename))
                course.thumbnail_filename = thumb_filename

        # Live Online & Live In Person duration defined directly by admin at course level
        if course.mode in ['Live Online', 'Live In Person']:
            try:
                course.duration_hours = float(request.form.get('duration_hours', course.duration_hours or 1.0))
            except Exception:
                pass
        else:
            recalculate_course_duration(course.id)

        # Replace CSV questions enforcing mode-based assessment rules
        summative_file = request.files.get('summative_assessment_csv') or request.files.get('course_end_assessment_csv')
        pre_file = request.files.get('pre_assessment_csv')
        post_file = request.files.get('post_assessment_csv')

        if summative_file and summative_file.filename:
            q_list, errs = parse_assessment_csv(summative_file.stream, filename=summative_file.filename)
            if not errs:
                CourseAssessment.query.filter((CourseAssessment.course_id == course.id) & (CourseAssessment.assessment_type == 'COURSE_END') & (CourseAssessment.lesson_id == None)).delete()
                for q in q_list:
                    assessment = CourseAssessment(
                        course_id=course.id,
                        assessment_type='COURSE_END',
                        serial_number=q['serial_number'],
                        question=q['question'],
                        option1=q['option1'],
                        option2=q['option2'],
                        option3=q['option3'],
                        option4=q['option4'],
                        correct_option=q['correct_option']
                    )
                    db.session.add(assessment)

                from app.models.enrollment import AssessmentAttempt
                for en in course.enrollments:
                    passed_att = AssessmentAttempt.query.filter_by(enrollment_id=en.id, assessment_type='COURSE_END', passed=True).first()
                    if not passed_att:
                        en.completion_status = 'In Progress'

        if pre_file and pre_file.filename:
            q_list, errs = parse_assessment_csv(pre_file.stream, filename=pre_file.filename)
            if not errs:
                CourseAssessment.query.filter_by(course_id=course.id, assessment_type='PRE').delete()
                for q in q_list:
                    assessment = CourseAssessment(
                        course_id=course.id,
                        assessment_type='PRE',
                        serial_number=q['serial_number'],
                        question=q['question'],
                        option1=q['option1'],
                        option2=q['option2'],
                        option3=q['option3'],
                        option4=q['option4'],
                        correct_option=q['correct_option']
                    )
                    db.session.add(assessment)

            if post_file and post_file.filename:
                q_list, errs = parse_assessment_csv(post_file.stream, filename=post_file.filename)
                if not errs:
                    CourseAssessment.query.filter_by(course_id=course.id, assessment_type='POST').delete()
                    for q in q_list:
                        assessment = CourseAssessment(
                            course_id=course.id,
                            assessment_type='POST',
                            serial_number=q['serial_number'],
                            question=q['question'],
                            option1=q['option1'],
                            option2=q['option2'],
                            option3=q['option3'],
                            option4=q['option4'],
                            correct_option=q['correct_option']
                        )
                        db.session.add(assessment)

        # Check if feedback repository or course assessment was updated/added:
        # Demote any completed enrollments for this course back to 'In Progress' if feedback or course end assessment is pending!
        from app.models.feedback import FeedbackResponse
        from app.models.enrollment import AssessmentAttempt
        for en in course.enrollments:
            passed_att = AssessmentAttempt.query.filter_by(enrollment_id=en.id, assessment_type='COURSE_END', passed=True).first()
            has_post_exam = CourseAssessment.query.filter_by(course_id=course.id, assessment_type='COURSE_END').count() > 0
            
            fb_repo = course.feedback_repository or FeedbackRepository.query.first()
            fb_resp = FeedbackResponse.query.filter_by(repo_id=fb_repo.id, learner_id=en.learner_id).first() if fb_repo else None
            
            if (has_post_exam and not passed_att) or (fb_repo and not fb_resp):
                if en.completion_status == 'Completed':
                    en.completion_status = 'In Progress'

        db.session.commit()
        flash(f"Course {course.course_id} updated successfully.", "success")
        return redirect(url_for('courses.view_course', course_id=course.id))

    from app.models.feedback import FeedbackRepository
    feedback_repos = FeedbackRepository.query.all()
    return render_template('courses/create_edit.html', course=course, auto_id=course.course_id, feedback_repos=feedback_repos)


@courses_bp.route('/<int:course_id>/archive', methods=['POST'])
@admin_required
def archive_course(course_id):

    course = Course.query.get_or_404(course_id)
    course.is_archived = True
    db.session.commit()
    flash(f"Course '{course.name}' ({course.course_id}) has been successfully archived. It will no longer be visible to learners or available for assignment.", "success")
    return redirect(url_for('courses.list_courses'))


@courses_bp.route('/<int:course_id>/unarchive', methods=['POST'])
@admin_required
def unarchive_course(course_id):

    course = Course.query.get_or_404(course_id)
    course.is_archived = False
    db.session.commit()
    flash(f"Course '{course.name}' ({course.course_id}) has been restored/unarchived successfully.", "success")
    return redirect(url_for('courses.list_courses'))


@courses_bp.route('/<int:course_id>/delete', methods=['POST'])
@admin_required
def delete_course(course_id):
    """
    Safely archives the course instead of deleting database records.
    """
    course = Course.query.get_or_404(course_id)
    course.is_archived = True
    db.session.commit()

    flash(f"Course '{course.name}' ({course.course_id}) has been successfully archived.", "success")
    return redirect(url_for('courses.list_courses'))


@courses_bp.route('/<int:course_id>/upload_material', methods=['POST'])
@admin_required
def upload_material(course_id):

    course = Course.query.get_or_404(course_id)
    title = request.form.get('material_title', '').strip()
    description = request.form.get('material_description', '').strip()
    user_mat_type = request.form.get('material_type', 'Auto').strip()
    external_url = request.form.get('external_url', '').strip()
    material_file = request.files.get('material_file')
    allow_download = request.form.get('allow_download') == 'on' # Checkbox toggle

    if not title:
        flash("Material title is required.", "danger")
        return redirect(url_for('courses.view_course', course_id=course.id))

    filename = None
    material_type = user_mat_type if user_mat_type != 'Auto' else 'External Link'
    size_str = 'N/A'

    if external_url:
        from app.services.gdrive_service import parse_gdrive_url
        is_gdrive, embed_url, g_type, file_id = parse_gdrive_url(external_url)
        if is_gdrive:
            if user_mat_type in ['Auto', 'Google Drive', '']:
                material_type = f"Google Drive ({g_type})"
            size_str = 'Google Drive'
        elif user_mat_type == 'Auto':
            if 'scorm' in external_url.lower():
                material_type = 'SCORM Link'
            else:
                material_type = 'External Link'

    elif material_file and material_file.filename:
        orig_filename = material_file.filename
        ext = os.path.splitext(orig_filename)[1].lower()

        if user_mat_type == 'Auto':
            if ext in ['.pdf']:
                material_type = 'PDF'
            elif ext in ['.ppt', '.pptx']:
                material_type = 'PPT'
            elif ext in ['.mp4', '.webm', '.avi', '.mkv', '.mov']:
                material_type = 'Video'
            elif ext in ['.xlsx', '.xls', '.csv']:
                material_type = 'Excel'
            elif ext in ['.zip', '.rar']:
                material_type = 'SCORM'
            elif ext in ['.doc', '.docx', '.txt']:
                material_type = 'Document'
            else:
                material_type = 'Other File'

        short_id = uuid.uuid4().hex[:8]
        filename = f"mat_{course.course_id}_{short_id}{ext}"
        save_path = os.path.join(current_app.config['MATERIALS_FOLDER'], filename)
        material_file.save(save_path)

        file_size_bytes = os.path.getsize(save_path)
        if file_size_bytes < 1024 * 1024:
            size_str = f"{round(file_size_bytes / 1024, 1)} KB"
        else:
            size_str = f"{round(file_size_bytes / (1024 * 1024), 2)} MB"
    else:
        flash("Please provide a Google Drive URL / External link or upload a file.", "danger")
        return redirect(url_for('courses.view_course', course_id=course.id))

    new_mat = CourseMaterial(
        course_id=course.id,
        title=title,
        description=description if description else None,
        material_type=material_type,
        filename=filename,
        external_url=external_url if external_url else None,
        file_size_str=size_str,
        allow_download=allow_download
    )
    db.session.add(new_mat)
    db.session.commit()

    flash(f"Learning material '{title}' saved successfully.", "success")
    return redirect(url_for('courses.view_course', course_id=course.id))


@courses_bp.route('/material/<int:material_id>/toggle_download', methods=['POST'])
@admin_required
def toggle_download(material_id):

    mat = CourseMaterial.query.get_or_404(material_id)
    mat.allow_download = not mat.allow_download
    db.session.commit()

    status_str = "Download Allowed" if mat.allow_download else "Download Restricted (View-Only)"
    flash(f"Updated permission for '{mat.title}': {status_str}.", "info")
    return redirect(url_for('courses.view_course', course_id=mat.course_id))


@courses_bp.route('/material/<int:material_id>/download')
def download_material(material_id):
    mat = CourseMaterial.query.get_or_404(material_id)

    # Check download permissions for non-admin learners
    is_admin = session.get('admin_logged_in', False)
    force_download = request.args.get('download', '0') == '1'

    if not is_admin and not mat.allow_download and force_download:
        flash("File download restricted by L&D Admin. View inline only.", "warning")
        return redirect(url_for('learners.self_paced_flow', course_id_str=mat.course.course_id))

    if mat.external_url and not mat.filename:
        return redirect(mat.external_url)

    if mat.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], mat.filename)
        if os.path.exists(file_path):
            ext = os.path.splitext(mat.filename)[1].lower()
            is_ppt = ext in ['.ppt', '.pptx'] or ('PPT' in (mat.material_type or '').upper()) or ('POWERPOINT' in (mat.material_type or '').upper())
            as_attach = force_download if is_admin or mat.allow_download else False

            # If user explicitly requested download AND download is allowed:
            if force_download and (is_admin or mat.allow_download):
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=f"{mat.title}{ext}"
                )

            # For PowerPoint inline viewing: Render PPTonPage interactive client-side viewer
            if is_ppt:
                raw_url = url_for('courses.get_material_raw_file', material_id=mat.id)
                js_url = url_for('static', filename='js/pptx-viewer.js')
                return f"""
                <!DOCTYPE html>
                <html>
                <head>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <title>{mat.title} - Interactive PowerPoint Presentation</title>
                    <script src="{js_url}"></script>
                    <style>
                        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                        html, body {{ width: 100%; height: 100%; background: #0E1116; overflow: hidden; font-family: system-ui, -apple-system, sans-serif; }}
                        pptx-viewer {{
                            width: 100%;
                            height: 100%;
                            --pptx-surface: #0E1116;
                            --pptx-accent: #0A4B5C;
                            --pptx-chrome: rgba(14, 17, 22, 0.88);
                            --pptx-on-chrome: #F8FAFC;
                        }}
                    </style>
                </head>
                <body>
                    <pptx-viewer src="{raw_url}" controls="default" animations="on"></pptx-viewer>
                    <script>
                        document.addEventListener('DOMContentLoaded', () => {{
                            const viewer = document.querySelector('pptx-viewer');
                            if (viewer) {{
                                const injectHDStyles = () => {{
                                    if (viewer.shadowRoot && !viewer.shadowRoot.querySelector('#hd-image-patch')) {{
                                        const style = document.createElement('style');
                                        style.id = 'hd-image-patch';
                                        style.textContent = `
                                            img, image, svg, canvas {{
                                                image-rendering: -webkit-optimize-contrast !important;
                                                image-rendering: high-quality !important;
                                                transform: translateZ(0);
                                                backface-visibility: hidden;
                                            }}
                                            .slide-container {{
                                                text-rendering: optimizeLegibility;
                                                -webkit-font-smoothing: antialiased;
                                            }}
                                        `;
                                        viewer.shadowRoot.appendChild(style);
                                    }}
                                }};
                                viewer.addEventListener('pptx-load', injectHDStyles);
                                setInterval(injectHDStyles, 500);
                            }}
                        }});
                    </script>
                </body>
                </html>
                """, 200, {'Content-Type': 'text/html'}

            # Determine MIME type for PDF, Video, Image
            mimetype = None
            if ext == '.pdf':
                mimetype = 'application/pdf'
            elif ext in ['.mp4', '.webm', '.mov']:
                mimetype = f'video/{ext[1:]}'

            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=as_attach,
                download_name=f"{mat.title}{ext}"
            )

    flash("Material file not found on server.", "danger")
    return redirect(url_for('courses.view_course', course_id=mat.course_id))


@courses_bp.route('/courseware/<int:courseware_id>/raw_file', methods=['GET', 'HEAD', 'OPTIONS'])
def get_courseware_raw_file(courseware_id):
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.status_code = 204
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type'
        resp.headers['Access-Control-Max-Age'] = '86400'
        return resp

    cw = LessonCourseware.query.get_or_404(courseware_id)
    if cw.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename)
        if os.path.exists(file_path):
            ext = os.path.splitext(cw.filename)[1].lower()
            mimetype = 'application/vnd.openxmlformats-officedocument.presentationml.presentation' if ext in ['.ppt', '.pptx'] else 'application/octet-stream'
            resp = send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False
            )
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type'
            resp.headers['Access-Control-Expose-Headers'] = 'Content-Length, Content-Range, Accept-Ranges, ETag'
            resp.headers['Accept-Ranges'] = 'bytes'
            return resp
    return jsonify({'error': 'File not found'}), 404


@courses_bp.route('/material/<int:material_id>/raw_file', methods=['GET', 'HEAD', 'OPTIONS'])
def get_material_raw_file(material_id):
    if request.method == 'OPTIONS':
        resp = jsonify({})
        resp.status_code = 204
        resp.headers['Access-Control-Allow-Origin'] = '*'
        resp.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        resp.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type'
        resp.headers['Access-Control-Max-Age'] = '86400'
        return resp

    mat = CourseMaterial.query.get_or_404(material_id)
    if mat.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], mat.filename)
        if os.path.exists(file_path):
            ext = os.path.splitext(mat.filename)[1].lower()
            mimetype = 'application/vnd.openxmlformats-officedocument.presentationml.presentation' if ext in ['.ppt', '.pptx'] else 'application/octet-stream'
            resp = send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False
            )
            resp.headers['Access-Control-Allow-Origin'] = '*'
            resp.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
            resp.headers['Access-Control-Allow-Headers'] = 'Range, Content-Type'
            resp.headers['Access-Control-Expose-Headers'] = 'Content-Length, Content-Range, Accept-Ranges, ETag'
            resp.headers['Accept-Ranges'] = 'bytes'
            return resp
    return jsonify({'error': 'File not found'}), 404


@courses_bp.route('/courseware/<int:courseware_id>/slide_img/<filename>')
def serve_slide_image(courseware_id, filename):
    img_folder = os.path.join(current_app.config['MATERIALS_FOLDER'], 'slides', str(courseware_id))
    img_path = os.path.join(img_folder, filename)
    if os.path.exists(img_path):
        return send_file(img_path)
    return jsonify({'error': 'Image not found'}), 404


@courses_bp.route('/material/<int:material_id>/slide_img/<filename>')
def serve_material_slide_image(material_id, filename):
    img_folder = os.path.join(current_app.config['MATERIALS_FOLDER'], 'slides', f"mat_{material_id}")
    img_path = os.path.join(img_folder, filename)
    if os.path.exists(img_path):
        return send_file(img_path)
    return jsonify({'error': 'Image not found'}), 404


@courses_bp.route('/courseware/<int:courseware_id>/stream')
def stream_courseware(courseware_id):
    cw = LessonCourseware.query.get_or_404(courseware_id)

    # Allow explicit download ONLY when query param download=1 is sent AND allow_download is True
    if request.args.get('download') == '1':
        if cw.allow_download and cw.filename:
            file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename)
            if os.path.exists(file_path):
                return send_file(file_path, as_attachment=True)

    cw_type_upper = (cw.courseware_type or '').upper()
    ext = os.path.splitext(cw.filename)[1].lower() if cw.filename else ''
    
    is_ppt = ('PPT' in cw_type_upper) or ('POWERPOINT' in cw_type_upper) or ('SLIDE' in cw_type_upper) or (ext in ['.ppt', '.pptx'])
    is_pdf = ('PDF' in cw_type_upper) or (ext == '.pdf')

    # 1. PPTonPage INTERACTIVE HTML5 PRESENTATION PLAYER ENGINE FOR PPT / PPTX
    if is_ppt:
        raw_url = url_for('courses.get_courseware_raw_file', courseware_id=cw.id)
        js_url = url_for('static', filename='js/pptx-viewer.js')
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{cw.title} - Interactive PowerPoint Presentation</title>
            <script src="{js_url}"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                html, body {{ width: 100%; height: 100%; background: #0E1116; overflow: hidden; font-family: system-ui, -apple-system, sans-serif; }}
                pptx-viewer {{
                    width: 100%;
                    height: 100%;
                    --pptx-surface: #0E1116;
                    --pptx-accent: #0A4B5C;
                    --pptx-chrome: rgba(14, 17, 22, 0.88);
                    --pptx-on-chrome: #F8FAFC;
                }}
            </style>
        </head>
        <body>
            <pptx-viewer src="{raw_url}" controls="default" animations="on"></pptx-viewer>
            <script>
                document.addEventListener('DOMContentLoaded', () => {{
                    const viewer = document.querySelector('pptx-viewer');
                    if (viewer) {{
                        const injectHDStyles = () => {{
                            if (viewer.shadowRoot && !viewer.shadowRoot.querySelector('#hd-image-patch')) {{
                                const style = document.createElement('style');
                                style.id = 'hd-image-patch';
                                style.textContent = `
                                    img, image, svg, canvas {{
                                        image-rendering: -webkit-optimize-contrast !important;
                                        image-rendering: high-quality !important;
                                        transform: translateZ(0);
                                        backface-visibility: hidden;
                                    }}
                                    .slide-container {{
                                        text-rendering: optimizeLegibility;
                                        -webkit-font-smoothing: antialiased;
                                    }}
                                `;
                                viewer.shadowRoot.appendChild(style);
                            }}
                        }};
                        viewer.addEventListener('pptx-load', injectHDStyles);
                        setInterval(injectHDStyles, 500);
                    }}
                }});
            </script>
        </body>
        </html>
        """, 200, {'Content-Type': 'text/html'}

    # 2. MOZILLA PDF.JS VECTOR PRESENTATION ENGINE FOR PDF
    if is_pdf:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename) if cw.filename else ''
        img_out_dir = os.path.join(current_app.config['MATERIALS_FOLDER'], 'slides', str(cw.id))
        img_rel_prefix = f"/courses/courseware/{cw.id}/slide_img"
        slide_images = render_pdf_to_slide_images(file_path, img_out_dir, img_rel_prefix) if (file_path and os.path.exists(file_path)) else []

        raw_file_url = url_for('courses.get_courseware_raw_file', courseware_id=cw.id)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{cw.title} - Mozilla PDF Viewer</title>
            <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
            <script src="https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js"></script>
            <style>
                * {{ box-sizing: border-box; margin: 0; padding: 0; }}
                body {{ background: #091214; color: #FAFAF9; font-family: system-ui, sans-serif; min-height: 100vh; display: flex; flex-direction: column; overflow: hidden; }}
                .deck-header {{ background: #0F172A; padding: 10px 16px; border-bottom: 1px solid #1E293B; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
                .deck-title {{ font-size: 0.95rem; font-weight: 700; color: #FFFFFF; display: flex; align-items: center; gap: 8px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
                .nav-controls {{ display: flex; align-items: center; gap: 10px; }}
                .btn-nav {{ background: #F59E0B; color: #0F172A; border: none; padding: 6px 14px; border-radius: 6px; font-size: 0.82rem; font-weight: 700; cursor: pointer; transition: all 0.15s ease; display: inline-flex; align-items: center; gap: 6px; }}
                .btn-nav:hover:not(:disabled) {{ background: #D97706; color: #FFFFFF; }}
                .btn-nav:disabled {{ opacity: 0.35; cursor: not-allowed; background: #334155; color: #94A3B8; }}
                .slide-counter {{ font-size: 0.85rem; font-weight: 700; color: #F59E0B; font-family: monospace; background: rgba(245, 158, 11, 0.15); padding: 4px 10px; border-radius: 20px; border: 1px solid rgba(245, 158, 11, 0.3); }}
                .slide-stage {{ flex: 1; padding: 12px; display: flex; align-items: center; justify-content: center; background: radial-gradient(circle at center, #1E293B 0%, #091214 100%); overflow: auto; height: calc(100vh - 52px); }}
                #pdfCanvas {{ max-width: 100%; max-height: calc(100vh - 70px); border-radius: 8px; box-shadow: 0 12px 32px rgba(0,0,0,0.6); background: #FFFFFF; display: block; margin: 0 auto; }}
            </style>
        </head>
        <body>
            <div class="deck-header">
                <div class="deck-title">
                    <i class="fa-solid fa-file-pdf" style="color:#F59E0B;"></i> {cw.title}
                </div>
                <div class="nav-controls">
                    <button class="btn-nav" id="btnPrev" onclick="prevPage()"><i class="fa-solid fa-arrow-left"></i> Prev</button>
                    <span class="slide-counter" id="slideCounter">Page 1 of 1</span>
                    <button class="btn-nav" id="btnNext" onclick="nextPage()">Next <i class="fa-solid fa-arrow-right"></i></button>
                </div>
            </div>

            <div class="slide-stage">
                <canvas id="pdfCanvas"></canvas>
            </div>

            <script>
                pdfjsLib.GlobalWorkerOptions.workerSrc = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js';
                let pdfDoc = null;
                let pageNum = 1;
                const canvas = document.getElementById('pdfCanvas');
                const ctx = canvas.getContext('2d');

                pdfjsLib.getDocument('{raw_file_url}').promise.then(function(doc) {{
                    pdfDoc = doc;
                    renderPage(1);
                }});

                function renderPage(num) {{
                    pdfDoc.getPage(num).then(function(page) {{
                        const viewport = page.getViewport({{ scale: 1.4 }});
                        canvas.height = viewport.height;
                        canvas.width = viewport.width;
                        page.render({{ canvasContext: ctx, viewport: viewport }});
                    }});
                    document.getElementById('slideCounter').textContent = 'Page ' + num + ' of ' + pdfDoc.numPages;
                    document.getElementById('btnPrev').disabled = (num <= 1);
                    document.getElementById('btnNext').disabled = (num >= pdfDoc.numPages);
                }}

                function prevPage() {{ if (pageNum > 1) {{ pageNum--; renderPage(pageNum); }} }}
                function nextPage() {{ if (pageNum < pdfDoc.numPages) {{ pageNum++; renderPage(pageNum); }} }}

                document.addEventListener('keydown', (e) => {{
                    if (e.key === 'ArrowLeft') prevPage();
                    if (e.key === 'ArrowRight') nextPage();
                }});
            </script>
        </body>
        </html>
        """, 200, {'Content-Type': 'text/html'}

    # 3. Handle PDF, Video, or other uploads (NEVER send raw PPT files to browser)
    if cw.filename and ext not in ['.ppt', '.pptx']:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename)
        if os.path.exists(file_path):
            mimetype = None
            if ext == '.pdf':
                mimetype = 'application/pdf'
            elif ext in ['.mp4', '.webm', '.ogg', '.mov']:
                mimetype = f'video/{ext[1:]}'

            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False
            )

    return f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"><style>body{{background:#091214;color:#FAFAF9;font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}}</style></head>
    <body>
        <div style="text-align:center;padding:20px;background:#0F172A;border-radius:12px;border:1px solid #334155;max-width:500px;">
            <h3 style="color:#F59E0B;margin-bottom:10px;">{cw.title}</h3>
            <p style="color:#94A3B8;font-size:0.9rem;">{cw.content_text or 'Presentation deck loaded cleanly.'}</p>
        </div>
    </body>
    </html>
    """, 200, {'Content-Type': 'text/html'}

    # 2. Handle PDF, Video, or other uploads
    if cw.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename)
        if os.path.exists(file_path):
            mimetype = None
            if ext == '.pdf':
                mimetype = 'application/pdf'
            elif ext in ['.mp4', '.webm', '.ogg', '.mov']:
                mimetype = f'video/{ext[1:]}'

            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False
            )

    return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))

    # 2. Handle PDF, Video, or other uploads
    if cw.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], cw.filename)
        if os.path.exists(file_path):
            mimetype = None
            if ext == '.pdf':
                mimetype = 'application/pdf'
            elif ext in ['.mp4', '.webm', '.ogg', '.mov']:
                mimetype = f'video/{ext[1:]}'

            return send_file(
                file_path,
                mimetype=mimetype,
                as_attachment=False
            )

    return redirect(url_for('courses.view_course', course_id=cw.lesson.course_id))


@courses_bp.route('/material/<int:material_id>/delete', methods=['POST'])
@admin_required
def delete_material(material_id):

    mat = CourseMaterial.query.get_or_404(material_id)
    course_id = mat.course_id

    if mat.filename:
        file_path = os.path.join(current_app.config['MATERIALS_FOLDER'], mat.filename)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    db.session.delete(mat)
    db.session.commit()

    flash(f"Learning material '{mat.title}' deleted.", "success")
    return redirect(url_for('courses.view_course', course_id=course_id))


@courses_bp.route('/scorm/content/<scorm_id_str>/<path:filename>')
def serve_scorm_file(scorm_id_str, filename):
    scorm_dir = os.path.abspath(os.path.join(current_app.root_path, '..', 'uploads', 'scorm', scorm_id_str))
    return send_from_directory(scorm_dir, filename)


@courses_bp.route('/<int:course_id>/download_analytics')
@admin_required
def download_analytics(course_id):

    course = Course.query.get_or_404(course_id)
    csv_buffer = generate_course_analytics_csv(course.id)

    safe_name = "".join(c for c in course.name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    filename = f"Course_Analytics_{safe_name}.csv"

    return send_file(
        csv_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@courses_bp.route('/class/<int:class_id>/download_attendance')
@admin_required
def download_attendance(class_id):

    live_cls = LiveClass.query.get_or_404(class_id)
    csv_buffer = generate_class_attendance_csv(live_cls.id)

    safe_name = "".join(c for c in live_cls.class_name if c.isalnum() or c in (' ', '_', '-')).strip().replace(' ', '_')
    filename = f"Attendance_{safe_name}.csv"

    return send_file(
        csv_buffer,
        mimetype='text/csv',
        as_attachment=True,
        download_name=filename
    )


@courses_bp.route('/<int:course_id>/lessons/<int:lesson_id>/author', methods=['GET', 'POST'])
@admin_required
def author_lesson(course_id, lesson_id):
    """
    Admin Course Authoring: Visual editor for lesson slides and document embeds.
    """
    if not current_app.config.get('ENABLE_CONTENT_AUTHORING', False):
        flash("Content authoring tool is currently disabled by system configuration.", "warning")
        return redirect(url_for('courses.view_course', course_id=course_id))

    course = Course.query.get_or_404(course_id)
    lesson = CourseLesson.query.get_or_404(lesson_id)

    # Find or create a default text courseware for this lesson
    cw = LessonCourseware.query.filter_by(lesson_id=lesson.id, courseware_type='Text').first()
    if not cw:
        cw = LessonCourseware(
            lesson_id=lesson.id,
            title=f"Interactive Lesson: {lesson.title}",
            courseware_type='Text',
            content_text=json.dumps([
                {
                    "type": "header",
                    "title": "Welcome to " + lesson.title,
                    "body": "This lesson was created using the modular RISE block builder.",
                    "theme": "navy"
                },
                {
                    "type": "text",
                    "body": "<p>Start building your scrollable lesson here. Add new typography blocks, accordion segments, tabs, or knowledge checks!</p>"
                }
            ])
        )
        db.session.add(cw)
        db.session.commit()

    # Find or create draft version
    draft = RiseCoursewareVersion.query.filter_by(courseware_id=cw.id, status='Draft').first()
    if not draft:
        draft = RiseCoursewareVersion(
            courseware_id=cw.id,
            status='Draft',
            blocks_json=cw.content_text or '[]'
        )
        db.session.add(draft)
        db.session.commit()

    if request.method == 'POST':
        action = request.form.get('action')

        if action == 'upload_doc':
            # Handle local PDF/Excel/Word document upload and add as new courseware
            doc_file = request.files.get('doc_file')
            doc_title = request.form.get('doc_title', 'Lesson Document').strip()
            
            if doc_file and doc_file.filename:
                # Save to uploads folder
                filename = f"doc_{uuid.uuid4().hex}_{doc_file.filename}"
                upload_dir = os.path.join(current_app.root_path, '..', 'uploads', 'materials')
                os.makedirs(upload_dir, exist_ok=True)
                doc_file.save(os.path.join(upload_dir, filename))
                
                # Determine courseware type
                ext = doc_file.filename.split('.')[-1].lower()
                cw_type = 'PDF'
                if ext in ['xls', 'xlsx', 'csv']:
                    cw_type = 'Excel'
                elif ext in ['ppt', 'pptx']:
                    cw_type = 'PPT'
                elif ext in ['doc', 'docx']:
                    cw_type = 'Doc'

                new_cw = LessonCourseware(
                    lesson_id=lesson.id,
                    title=doc_title,
                    courseware_type=cw_type,
                    filename=filename
                )
                db.session.add(new_cw)
                db.session.commit()
                flash(f"Successfully uploaded and added document: {doc_title}", "success")
            else:
                flash("Please choose a valid file to upload.", "warning")
            return redirect(url_for('courses.author_lesson', course_id=course.id, lesson_id=lesson.id))

        elif action == 'embed_url':
            # Handle Google Drive/External document embeds
            embed_url = request.form.get('embed_url', '').strip()
            embed_title = request.form.get('embed_title', 'Embedded Content').strip()
            embed_type = request.form.get('embed_type', 'PDF') # 'PDF', 'Excel', 'Doc', 'PPT'

            if embed_url:
                new_cw = LessonCourseware(
                    lesson_id=lesson.id,
                    title=embed_title,
                    courseware_type=embed_type,
                    external_url=embed_url
                )
                db.session.add(new_cw)
                db.session.commit()
                flash(f"Successfully embedded document: {embed_title}", "success")
            else:
                flash("Please enter a valid URL.", "warning")
            return redirect(url_for('courses.author_lesson', course_id=course.id, lesson_id=lesson.id))

        elif action == 'publish':
            # Publish draft blocks to live courseware
            slides_data = request.form.get('slides_json')
            if slides_data:
                try:
                    json.loads(slides_data)
                    draft.blocks_json = slides_data
                    cw.content_text = slides_data
                    db.session.commit()
                    return jsonify({'status': 'success', 'message': 'Interactive lesson published successfully!'})
                except Exception as e:
                    return jsonify({'status': 'error', 'message': f'Invalid schema: {str(e)}'}), 400
            return jsonify({'status': 'error', 'message': 'No content provided to publish.'}), 400

        else:
            # Handle saving draft blocks
            slides_data = request.form.get('slides_json')
            if slides_data:
                try:
                    # Validate JSON
                    json.loads(slides_data)
                    draft.blocks_json = slides_data
                    db.session.commit()
                    return jsonify({'status': 'success', 'message': 'Draft version saved successfully!'})
                except Exception as e:
                    return jsonify({'status': 'error', 'message': f'Invalid slides data: {str(e)}'}), 400
            
            return jsonify({'status': 'error', 'message': 'No slides data provided.'}), 400

    # Get all other uploaded files/embeds for this lesson
    materials = LessonCourseware.query.filter(
        LessonCourseware.lesson_id == lesson.id,
        LessonCourseware.id != cw.id
    ).all()

    # Load slides structure from Draft
    slides = []
    try:
        slides = json.loads(draft.blocks_json) if draft.blocks_json else []
    except Exception:
        pass

    return render_template(
        'courses/author.html',
        course=course,
        lesson=lesson,
        cw=cw,
        slides=slides,
        materials=materials
    )


@courses_bp.route('/courseware/<int:courseware_id>/track', methods=['POST'])
def track_rise_telemetry(courseware_id):
    """
    Telemetry: Track block-level learner interactions asynchronously.
    """
    learner_id = session.get('learner_id')
    if not learner_id:
        return jsonify({'status': 'error', 'message': 'Learner not authenticated.'}), 401
    
    data = request.json or {}
    block_id = data.get('block_id')
    if not block_id:
        return jsonify({'status': 'error', 'message': 'Missing block ID.'}), 400
    
    progress = LearnerBlockProgress.query.filter_by(
        learner_id=learner_id,
        courseware_id=courseware_id,
        block_id=block_id
    ).first()
    
    if not progress:
        progress = LearnerBlockProgress(
            learner_id=learner_id,
            courseware_id=courseware_id,
            block_id=block_id,
            attempts_count=0,
            time_spent_seconds=0
        )
        db.session.add(progress)
    
    progress.attempts_count = (progress.attempts_count or 0) + 1
    if data.get('is_completed') is not None:
        progress.is_completed = bool(data.get('is_completed'))
    if data.get('score') is not None:
        progress.score = int(data.get('score'))
    if data.get('time_spent') is not None:
        progress.time_spent_seconds = (progress.time_spent_seconds or 0) + int(data.get('time_spent'))
        
    db.session.commit()
    return jsonify({'status': 'success'})


@courses_bp.route('/lesson/<int:lesson_id>/deploy', methods=['POST'])
@admin_required
def deploy_rise_course(lesson_id):
    """
    Auto-Deploy: Package the RISE lesson courseware and deploy it as a new self-paced course.
    """
    lesson = CourseLesson.query.get_or_404(lesson_id)
    cw = LessonCourseware.query.filter_by(lesson_id=lesson.id, courseware_type='Text').first()
    
    if not cw or not cw.content_text:
        return jsonify({'status': 'error', 'message': 'No RISE courseware contents found to deploy.'}), 400
        
    # Generate unique course parameters
    import random
    suffix = random.randint(1000, 9999)
    new_course_id = f"CRS-RISE-{suffix}"
    
    # 1. Create a new course
    new_course = Course(
        course_id=new_course_id,
        name=f"Deployed Course: {lesson.title}",
        duration_hours=lesson.duration_hours or 1.0,
        description=f"Automatically deployed self-paced course from RISE Lesson: {lesson.title}.",
        mode='Self Paced',
        pass_percentage=80.0,
        has_certificate=True,
        is_sequential=True
    )
    db.session.add(new_course)
    db.session.commit()
    
    # 2. Copy lesson
    new_lesson = CourseLesson(
        course_id=new_course.id,
        lesson_number=1,
        title=lesson.title,
        summary=lesson.summary,
        duration_hours=lesson.duration_hours,
        min_time_minutes=lesson.min_time_minutes
    )
    db.session.add(new_lesson)
    db.session.commit()
    
    # 3. Copy text courseware blocks content
    new_cw = LessonCourseware(
        lesson_id=new_lesson.id,
        title=cw.title,
        courseware_type='Text',
        content_text=cw.content_text
    )
    db.session.add(new_cw)
    
    # 4. Copy draft version if available
    draft = RiseCoursewareVersion.query.filter_by(courseware_id=cw.id, status='Draft').first()
    if draft:
        new_draft = RiseCoursewareVersion(
            courseware_id=new_cw.id,
            status='Draft',
            blocks_json=draft.blocks_json
        )
        db.session.add(new_draft)
        
    db.session.commit()
    
    return jsonify({
        'status': 'success',
        'message': f'Course successfully deployed as {new_course_id}!',
        'redirect_url': url_for('courses.view_course', course_id=new_course.id)
    })


@courses_bp.route('/sample_csv/<csv_type>')
@admin_required
def download_sample_csv(csv_type):
    """
    Centralized Sample CSV Template Generator for Admin Portal.
    Generates downloadable CSV files with indicative headers and sample data rows.
    """
    import io
    import csv
    from flask import Response

    output = io.StringIO()
    writer = csv.writer(output)

    filename = f"{csv_type}_sample_template.csv"

    if csv_type == 'assessment':
        writer.writerow(['Serial Number', 'Question', 'Option1', 'Option2', 'Option3', 'Option4', 'Option5', 'Correct Option'])
        writer.writerow(['1', 'What is the primary function of Aditya LMS?', 'Deliver learning content & track progress', 'Manage server hardware', 'Design vector graphics', 'Calculate payroll', '', 'Option1'])
        writer.writerow(['2', 'Which file format is supported for interactive presentation viewing?', '.pptx', '.pdf', '.docx', '.xlsx', '.mp4', 'Option1'])
        writer.writerow(['3', 'What is the passing criteria for Course End Assessment?', '80%', '50%', '10%', '100%', '', 'Option1'])
    elif csv_type in ['learners', 'enrollment']:
        writer.writerow(['Employee ID', 'Name', 'Email', 'Department', 'Role'])
        writer.writerow(['10001', 'Rajesh Kumar', 'rajesh.kumar@aditya.com', 'L&D Academics', 'Learner'])
        writer.writerow(['10002', 'Priya Sharma', 'priya.sharma@aditya.com', 'Engineering', 'Learner'])
        writer.writerow(['10003', 'Anil Verma', 'anil.verma@aditya.com', 'Quality Assurance', 'Learner'])
    elif csv_type == 'attendance':
        writer.writerow(['Employee ID', 'Learner Name', 'Status', 'Attendance Date'])
        writer.writerow(['10001', 'Rajesh Kumar', 'Present', '2026-09-05'])
        writer.writerow(['10002', 'Priya Sharma', 'Absent', '2026-09-05'])
        writer.writerow(['10003', 'Anil Verma', 'Present', '2026-09-05'])
    elif csv_type == 'feedback':
        writer.writerow(['Serial Number', 'Question Text', 'Question Type'])
        writer.writerow(['1', 'Rate the overall course structure and content clarity', 'RATING'])
        writer.writerow(['2', 'Was the presentation and courseware engaging?', 'RATING'])
        writer.writerow(['3', 'Share any additional comments or suggestions for improvement', 'TEXT'])
    elif csv_type in ['users', 'user_management']:
        writer.writerow(['Employee ID', 'Name', 'Email', 'Department', 'Role', 'Manager Employee ID'])
        writer.writerow(['10001', 'Amit Patel', 'amit.patel@aditya.com', 'Technology', 'Super Admin', ''])
        writer.writerow(['10002', 'Sunita Rao', 'sunita.rao@aditya.com', 'Technology', 'Learner', '10001'])
        writer.writerow(['10003', 'Rajesh Kumar', 'rajesh.kumar@aditya.com', 'L&D Academics', 'Learner', '10001'])
    else:
        writer.writerow(['Serial Number', 'Data1', 'Data2', 'Data3'])
        writer.writerow(['1', 'Sample 1', 'Sample 2', 'Sample 3'])

    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    return response