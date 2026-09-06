from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file, current_app
import os
from datetime import datetime
from app.models import db
from app.models.certificate import Certificate
from app.models.user import Learner
from app.models.course import Course
from app.services.pdf_service import generate_certificate_pdf

from app.utils.decorators import admin_required

certificates_bp = Blueprint('certificates', __name__)

@certificates_bp.route('/')
@admin_required
def list_certificates():

    search_query = request.args.get('search', '').strip()
    query = Certificate.query.join(Learner).join(Course)

    if search_query:
        query = query.filter(
            (Certificate.certificate_id.ilike(f'%{search_query}%')) |
            (Learner.name.ilike(f'%{search_query}%')) |
            (Learner.global_id.ilike(f'%{search_query}%')) |
            (Course.name.ilike(f'%{search_query}%'))
        )

    certs = query.order_by(Certificate.issue_date.desc()).all()
    return render_template('certificates/list.html', certificates=certs, search_query=search_query)


@certificates_bp.route('/my_certificates')
def my_certificates():
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to view your certificates.", "info")
        return redirect(url_for('auth.learner_login'))
        
    learner = Learner.query.get_or_404(learner_id)
    certificates = Certificate.query.filter_by(learner_id=learner.id).order_by(Certificate.issue_date.desc()).all()
    
    from app.models.external_certificate import ExternalCertificate
    external_certificates = ExternalCertificate.query.filter_by(learner_id=learner.id).order_by(ExternalCertificate.date_earned.desc()).all()
    
    return render_template('learner_portal/certificates.html', learner=learner, certificates=certificates, external_certificates=external_certificates)


@certificates_bp.route('/upload_external', methods=['POST'])
def upload_external():
    learner_id = session.get('learner_id')
    if not learner_id:
        flash("Please log in to upload certificates.", "danger")
        return redirect(url_for('auth.learner_login'))
        
    course_name = request.form.get('course_name', '').strip()
    issuing_org = request.form.get('issuing_org', '').strip()
    date_earned_str = request.form.get('date_earned', '').strip()
    skills = request.form.get('skills', '').strip()
    file = request.files.get('certificate_file')
    
    if not course_name or not issuing_org or not date_earned_str:
        flash("All fields are required.", "danger")
        return redirect(url_for('certificates.my_certificates'))
        
    pdf_filename = None
    if file and file.filename:
        from werkzeug.utils import secure_filename
        import uuid
        ext = os.path.splitext(file.filename)[1]
        pdf_filename = f"ext_cert_{uuid.uuid4().hex}{ext}"
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'external_certs')
        os.makedirs(upload_dir, exist_ok=True)
        file.save(os.path.join(upload_dir, pdf_filename))
        
    try:
        date_earned = datetime.strptime(date_earned_str, '%Y-%m-%d').date()
    except ValueError:
        flash("Invalid date format. Use YYYY-MM-DD.", "danger")
        return redirect(url_for('certificates.my_certificates'))
        
    from app.models.external_certificate import ExternalCertificate
    ext_cert = ExternalCertificate(
        learner_id=learner_id,
        course_name=course_name,
        issuing_org=issuing_org,
        date_earned=date_earned,
        pdf_filename=pdf_filename,
        skills=skills
    )
    db.session.add(ext_cert)
    
    learner = Learner.query.get(learner_id)
    if learner:
        learner.points += 50
        
    db.session.commit()
    
    flash("External certification uploaded successfully! Earned 50 points & updated skill repository.", "success")
    return redirect(url_for('certificates.my_certificates'))

@certificates_bp.route('/download/<cert_id_str>')
def download_certificate(cert_id_str):
    cert = Certificate.query.filter_by(certificate_id=cert_id_str).first_or_404()
    learner = cert.learner
    course = cert.course

    cert_filename = f"cert_{cert.certificate_id}.pdf"
    pdf_dir = os.path.join(certificates_bp.root_path, '..', '..', 'uploads', 'certificates')
    os.makedirs(pdf_dir, exist_ok=True)
    pdf_path = os.path.join(pdf_dir, cert_filename)

    if not os.path.exists(pdf_path):
        date_str = cert.issue_date.strftime('%d-%b-%Y')
        generate_certificate_pdf(learner.name, course.name, date_str, cert.certificate_id, pdf_path)

    return send_file(pdf_path, as_attachment=True, download_name=f"Aditya_Certificate_{cert.certificate_id}.pdf")
