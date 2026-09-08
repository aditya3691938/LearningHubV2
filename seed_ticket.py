from app import create_app
from app.models import db
from app.models.user import Learner
from app.models.issue import LmsIssue

app = create_app()
with app.app_context():
    learner = Learner.query.first()
    if learner:
        issue = LmsIssue(
            learner_id=learner.id, 
            category='Technical', 
            description='Cannot access the video lessons on my mobile device. It just shows a loading spinner.', 
            status='Open'
        )
        db.session.add(issue)
        db.session.commit()
        print('Ticket created successfully!')
    else:
        print('No learners found.')
