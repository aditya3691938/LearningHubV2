from app import create_app
from app.models import db
from sqlalchemy import text

app = create_app()
with app.app_context():
    try:
        db.session.execute(text("ALTER TABLE course_assessments ADD COLUMN option5 VARCHAR(255);"))
        db.session.commit()
        print("Successfully added option5 to course_assessments")
    except Exception as e:
        print(f"Error: {e}")
        db.session.rollback()
