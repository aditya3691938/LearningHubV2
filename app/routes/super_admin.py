from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, send_file, current_app, session
from app.utils.decorators import super_admin_required, admin_required
from app.models import db
import os
import sqlite3

super_admin_bp = Blueprint('super_admin', __name__, url_prefix='/super-admin')

def get_db_file_path():
    # Retrieve SQLite database file path from config
    uri = current_app.config['SQLALCHEMY_DATABASE_URI']
    if uri.startswith('sqlite:///'):
        db_path = uri.replace('sqlite:///', '')
        if not os.path.isabs(db_path):
            db_path = os.path.join(current_app.root_path, '..', db_path)
        return os.path.abspath(db_path)
    return None

@super_admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    if session.get('super_admin_logged_in'):
        return redirect(url_for('super_admin.index'))
        
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        
        # Read from environment variables, defaulting to superadmin/superpassword
        target_user = os.environ.get('SUPER_ADMIN_USERNAME', 'superadmin')
        target_pass = os.environ.get('SUPER_ADMIN_PASSWORD', 'superpassword')
        
        if username == target_user and password == target_pass:
            session['super_admin_logged_in'] = True
            flash("Logged in successfully as IT Super Administrator.", "success")
            return redirect(url_for('super_admin.index'))
        else:
            error = "Invalid Super Admin credentials."
            
    return render_template('super_admin/login.html', error=error)

@super_admin_bp.route('/logout')
def logout():
    session.pop('super_admin_logged_in', None)
    flash("Successfully logged out from IT Super Admin portal.", "info")
    return redirect(url_for('super_admin.login'))

@super_admin_bp.route('/')
@super_admin_required
def index():
    # Gather database information
    tables = []
    metadata = db.metadata
    
    # Get SQLite file size if applicable
    db_path = get_db_file_path()
    db_size_mb = 0
    if db_path and os.path.exists(db_path):
        db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2)
        
    for table_name in sorted(metadata.tables.keys()):
        try:
            count = db.session.execute(db.text(f"SELECT COUNT(*) FROM {table_name}")).scalar()
        except Exception:
            count = "Error"
        tables.append({
            'name': table_name,
            'count': count
        })
        
    return render_template(
        'super_admin/dashboard.html',
        tables=tables,
        db_size_mb=db_size_mb,
        db_path=db_path
    )

@super_admin_bp.route('/table/<table_name>')
@super_admin_required
def view_table(table_name):
    metadata = db.metadata
    if table_name not in metadata.tables:
        flash(f"Table '{table_name}' does not exist.", "danger")
        return redirect(url_for('super_admin.index'))
        
    table_obj = metadata.tables[table_name]
    columns = [col.name for col in table_obj.columns]
    
    # Fetch all records
    try:
        records = db.session.execute(db.text(f"SELECT * FROM {table_name}")).fetchall()
    except Exception as e:
        flash(f"Error querying table: {str(e)}", "danger")
        records = []
        
    # Convert records to lists of values
    rows = [list(r) for r in records]
    
    return render_template(
        'super_admin/table_edit.html',
        table_name=table_name,
        columns=columns,
        rows=rows
    )

@super_admin_bp.route('/table/<table_name>/delete-row', methods=['POST'])
@super_admin_required
def delete_row(table_name):
    row_id = request.form.get('id')
    if not row_id:
        flash("Record ID not specified.", "danger")
        return redirect(url_for('super_admin.view_table', table_name=table_name))
        
    try:
        db.session.execute(
            db.text(f"DELETE FROM {table_name} WHERE id = :id"),
            {'id': int(row_id)}
        )
        db.session.commit()
        flash(f"Successfully deleted record ID {row_id} from '{table_name}'.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to delete row: {str(e)}", "danger")
        
    return redirect(url_for('super_admin.view_table', table_name=table_name))

@super_admin_bp.route('/table/<table_name>/add-row', methods=['POST'])
@super_admin_required
def add_row(table_name):
    metadata = db.metadata
    if table_name not in metadata.tables:
        flash("Invalid table name.", "danger")
        return redirect(url_for('super_admin.index'))
        
    table_obj = metadata.tables[table_name]
    columns = [col.name for col in table_obj.columns if col.name != 'id'] # Skip primary key
    
    insert_data = {}
    for col in columns:
        val = request.form.get(col, '').strip()
        if val == '' and table_obj.columns[col].nullable:
            insert_data[col] = None
        else:
            insert_data[col] = val
            
    try:
        col_names = ", ".join(insert_data.keys())
        placeholders = ", ".join([f":{k}" for k in insert_data.keys()])
        db.session.execute(
            db.text(f"INSERT INTO {table_name} ({col_names}) VALUES ({placeholders})"),
            insert_data
        )
        db.session.commit()
        flash(f"Successfully inserted new row into '{table_name}'.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to insert row: {str(e)}", "danger")
        
    return redirect(url_for('super_admin.view_table', table_name=table_name))

@super_admin_bp.route('/update-cell', methods=['POST'])
@super_admin_required
def update_cell():
    # Inline cell updates via AJAX
    data = request.get_json() or {}
    table_name = data.get('table_name')
    row_id = data.get('row_id')
    column_name = data.get('column_name')
    new_value = data.get('value')
    
    metadata = db.metadata
    if not table_name or table_name not in metadata.tables or not row_id or not column_name:
        return jsonify({'success': False, 'message': 'Invalid parameters provided.'}), 400
        
    try:
        db.session.execute(
            db.text(f"UPDATE {table_name} SET {column_name} = :val WHERE id = :id"),
            {'val': new_value if new_value != '' else None, 'id': int(row_id)}
        )
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@super_admin_bp.route('/sql-runner', methods=['GET', 'POST'])
@super_admin_required
def sql_runner():
    query = ""
    results = None
    headers = None
    error = None
    affected_rows = -1
    
    if request.method == 'POST':
        query = request.form.get('query', '').strip()
        if query:
            try:
                res = db.session.execute(db.text(query))
                if res.returns_rows:
                    headers = list(res.keys())
                    results = [list(r) for r in res.fetchall()]
                else:
                    db.session.commit()
                    affected_rows = res.rowcount
            except Exception as e:
                db.session.rollback()
                error = str(e)
                
    return render_template(
        'super_admin/sql_runner.html',
        query=query,
        results=results,
        headers=headers,
        error=error,
        affected_rows=affected_rows
    )

@super_admin_bp.route('/backup')
@super_admin_required
def backup_db():
    db_path = get_db_file_path()
    if db_path and os.path.exists(db_path):
        return send_file(
            db_path,
            as_attachment=True,
            download_name='lms_backup.db',
            mimetype='application/x-sqlite3'
        )
    flash("Database path not found or server is not running on SQLite.", "danger")
    return redirect(url_for('super_admin.index'))

@super_admin_bp.route('/restore', methods=['POST'])
@super_admin_required
def restore_db():
    file = request.files.get('backup_file')
    if not file or not file.filename.endswith('.db'):
        flash("Please upload a valid SQLite .db file.", "danger")
        return redirect(url_for('super_admin.index'))
        
    db_path = get_db_file_path()
    if not db_path:
        flash("Database target path could not be resolved.", "danger")
        return redirect(url_for('super_admin.index'))
        
    try:
        # Close database connections dynamically before overwriting file
        db.session.remove()
        db.engine.dispose()
        
        file.save(db_path)
        flash("Database file restored successfully. Application is now using the uploaded backup.", "success")
    except Exception as e:
        flash(f"Failed to restore database: {str(e)}", "danger")
        
    return redirect(url_for('super_admin.index'))

@super_admin_bp.route('/users')
@super_admin_required
def users_dashboard():
    from app.models.user import Learner, AdminUser
    page = request.args.get('page', 1, type=int)
    skill_search = request.args.get('skills', '').strip().lower()
    
    matching_learner_ids = None
    if skill_search:
        matching_learner_ids = set()
        terms = [t.strip() for t in skill_search.split(',') if t.strip()]
        for term in terms:
            # 1. Matches in ExternalCertificate skills
            from app.models.external_certificate import ExternalCertificate
            ext_certs = ExternalCertificate.query.filter(ExternalCertificate.skills.ilike(f'%{term}%')).all()
            for cert in ext_certs:
                matching_learner_ids.add(cert.learner_id)
                
            # 2. Matches in completed internal course name/description
            from app.models.enrollment import LearnerEnrollment
            from app.models.course import Course
            completed_enrollments = LearnerEnrollment.query.filter_by(completion_status='Completed').join(Course).filter(
                (Course.name.ilike(f'%{term}%')) | (Course.description.ilike(f'%{term}%'))
            ).all()
            for en in completed_enrollments:
                matching_learner_ids.add(en.learner_id)
                
    query = Learner.query
    if matching_learner_ids is not None:
        if len(matching_learner_ids) > 0:
            query = query.filter(Learner.id.in_(list(matching_learner_ids)))
        else:
            query = query.filter(db.false()) # No matches
            
    learners = query.order_by(Learner.name.asc()).paginate(page=page, per_page=50, error_out=False)
    admins = AdminUser.query.all()
    admin_usernames = {a.username for a in admins}
    
    return render_template(
        'super_admin/user_management.html',
        learners=learners,
        admin_usernames=admin_usernames,
        skill_search=skill_search
    )

@super_admin_bp.route('/users/promote', methods=['POST'])
@super_admin_required
def promote_user():
    from app.models.user import Learner, AdminUser
    learner_id = request.form.get('learner_id')
    learner = Learner.query.get_or_404(learner_id)
    
    existing_admin = AdminUser.query.filter_by(username=learner.global_id).first()
    if existing_admin:
        flash(f"Learner {learner.name} is already an L&D Administrator.", "warning")
    else:
        new_admin = AdminUser(username=learner.global_id, name=learner.name)
        new_admin.set_password(learner.global_id) # Default password is their global_id
        db.session.add(new_admin)
        db.session.commit()
        flash(f"Successfully promoted {learner.name} to L&D Administrator. Default password set to Global ID '{learner.global_id}'.", "success")
        
    return redirect(url_for('super_admin.users_dashboard'))

@super_admin_bp.route('/users/demote', methods=['POST'])
@super_admin_required
def demote_user():
    from app.models.user import Learner, AdminUser
    learner_id = request.form.get('learner_id')
    learner = Learner.query.get_or_404(learner_id)
    
    admin = AdminUser.query.filter_by(username=learner.global_id).first()
    if admin:
        db.session.delete(admin)
        db.session.commit()
        flash(f"Successfully demoted {learner.name} from L&D Administrator.", "success")
    else:
        flash(f"No L&D Administrator account found for {learner.name}.", "danger")
        
    return redirect(url_for('super_admin.users_dashboard'))

@super_admin_bp.route('/users/change-manager', methods=['POST'])
@super_admin_required
def change_manager():
    from app.models.user import Learner
    learner_id = request.form.get('learner_id')
    manager_id_str = request.form.get('manager_id')
    
    learner = Learner.query.get_or_404(learner_id)
    
    if manager_id_str == '' or manager_id_str == 'None':
        learner.manager_id = None
        db.session.commit()
        flash(f"Removed manager assignment for {learner.name}.", "success")
    else:
        manager_id = int(manager_id_str)
        if manager_id == learner.id:
            flash("A learner cannot be assigned as their own manager.", "danger")
        else:
            learner.manager_id = manager_id
            db.session.commit()
            flash(f"Updated manager for {learner.name} successfully.", "success")
            
    return redirect(url_for('super_admin.users_dashboard'))

@super_admin_bp.route('/users/upload-csv', methods=['POST'])
@super_admin_required
def upload_users_csv():
    import csv
    from io import StringIO
    from app.models.user import Learner, AdminUser
    
    file = request.files.get('users_csv')
    if not file or not file.filename.endswith('.csv'):
        flash("Please upload a valid CSV file.", "danger")
        return redirect(url_for('super_admin.users_dashboard'))
        
    try:
        csv_data = StringIO(file.read().decode('utf-8-sig'))
        reader = csv.DictReader(csv_data)
        
        # Clean header keys (trim spaces)
        reader.fieldnames = [name.strip().lower() for name in reader.fieldnames]
        
        added_count = 0
        updated_count = 0
        promoted_count = 0
        
        # Keep track of manager assignments to resolve in a second pass to support forward manager references
        manager_mappings = []
        
        for row in reader:
            global_id = row.get('global_id', '').strip()
            name = row.get('name', '').strip()
            email = row.get('email', '').strip()
            department = row.get('department', 'L&D').strip()
            manager_gid = row.get('manager_global_id', '').strip()
            is_admin = row.get('is_admin', '').strip().lower() in ('yes', '1', 'true')
            
            if not global_id or not name:
                continue
                
            learner = Learner.query.filter_by(global_id=global_id).first()
            if learner:
                learner.name = name
                learner.email = email if email else None
                learner.department = department
                updated_count += 1
            else:
                learner = Learner(global_id=global_id, name=name, email=email if email else None, department=department)
                db.session.add(learner)
                added_count += 1
                
            # Flush changes to assign database IDs to new learners
            db.session.flush()
            
            if manager_gid:
                manager_mappings.append((learner.id, manager_gid))
                
            if is_admin:
                existing_admin = AdminUser.query.filter_by(username=global_id).first()
                if not existing_admin:
                    new_admin = AdminUser(username=global_id, name=name)
                    new_admin.set_password(global_id)
                    db.session.add(new_admin)
                    promoted_count += 1
                    
        db.session.commit()
        
        # Second pass: resolve manager mappings
        resolved_managers = 0
        for learner_id, manager_gid in manager_mappings:
            learner = Learner.query.get(learner_id)
            manager = Learner.query.filter_by(global_id=manager_gid).first()
            if manager and manager.id != learner.id:
                learner.manager_id = manager.id
                resolved_managers += 1
                
        db.session.commit()
        flash(f"CSV import complete. Added: {added_count}, Updated: {updated_count}, Promoted Admins: {promoted_count}, Managers mapped: {resolved_managers}", "success")
        
    except Exception as e:
        db.session.rollback()
        flash(f"Failed to process CSV file: {str(e)}", "danger")
        
    return redirect(url_for('super_admin.users_dashboard'))

@super_admin_bp.route('/users/sample-csv')
@super_admin_required
def download_sample_csv():
    import io
    import csv
    from flask import Response
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['global_id', 'name', 'email', 'department', 'manager_global_id', 'is_admin'])
    writer.writerow(['10001', 'Amit Patel', 'amit.patel@aditya.com', 'Technology', '', 'yes'])
    writer.writerow(['10002', 'Sunita Rao', 'sunita.rao@aditya.com', 'Technology', '10001', 'no'])
    writer.writerow(['10003', 'Vikram Singh', 'vikram.singh@aditya.com', 'L&D', '10001', 'no'])
    
    response = Response(output.getvalue(), mimetype='text/csv')
    response.headers['Content-Disposition'] = 'attachment; filename=users_sample_template.csv'
    return response

@super_admin_bp.route('/guide')
@super_admin_required
def guide():
    return render_template('super_admin/guide.html')





@super_admin_bp.route('/broadcast_notification', methods=['POST'])
@super_admin_required
def broadcast_notification():
    from app.models.notification import LearnerNotification
    from app.models.user import Learner
    
    audience = request.form.get('audience', 'all')
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    
    if not title or not message:
        flash("Title and Message are required.", "danger")
        return redirect(url_for('dashboard.index'))
        
    image_path = None
    image_file = request.files.get('image')
    if image_file and image_file.filename:
        from werkzeug.utils import secure_filename
        import uuid
        import os
        from flask import current_app
        filename = secure_filename(image_file.filename)
        unique_filename = f"{uuid.uuid4().hex}_{filename}"
        upload_dir = os.path.join(current_app.root_path, 'static', 'uploads', 'notifications')
        os.makedirs(upload_dir, exist_ok=True)
        file_path = os.path.join(upload_dir, unique_filename)
        image_file.save(file_path)
        image_path = f"uploads/notifications/{unique_filename}"

    if audience == 'specific':
        raw_gids = request.form.get('global_id', '')
        gids = [g.strip() for g in raw_gids.replace('\r', '\n').split('\n') if g.strip()]
        
        if not gids:
            flash("Please provide at least one Global ID.", "danger")
            return redirect(url_for('dashboard.index'))
            
        success_count = 0
        not_found = []
        for gid in gids:
            learner = Learner.query.filter_by(global_id=gid).first()
            if not learner:
                not_found.append(gid)
                continue
            
            notif = LearnerNotification(
                learner_id=learner.id,
                title=title,
                message=message,
                notification_type='SYSTEM_UPDATE',
                image_path=image_path
            )
            db.session.add(notif)
            success_count += 1
            
        db.session.commit()
        if success_count > 0:
            flash(f"Notification sent to {success_count} learner(s) successfully.", "success")
        if not_found:
            flash(f"Could not find learners for the following Global IDs: {', '.join(not_found)}", "warning")
    else:
        # Broadcast to all learners
        learners = Learner.query.all()
        for learner in learners:
            notif = LearnerNotification(
                learner_id=learner.id,
                title=title,
                message=message,
                notification_type='SYSTEM_UPDATE',
                image_path=image_path
            )
            db.session.add(notif)
        db.session.commit()
        flash(f"Notification broadcasted to all {len(learners)} learners successfully.", "success")
        
    return redirect(url_for('dashboard.index'))


@super_admin_bp.route('/profile')
@super_admin_required
def admin_profile():
    from app.models.course import Course
    from app.models.user import Learner
    from app.models.issue import LmsIssue

    total_courses = Course.query.count()
    total_learners = Learner.query.count()
    open_tickets = LmsIssue.query.filter_by(status='Open').count()

    return render_template(
        'super_admin/profile.html',
        total_courses=total_courses,
        total_learners=total_learners,
        open_tickets=open_tickets
    )



