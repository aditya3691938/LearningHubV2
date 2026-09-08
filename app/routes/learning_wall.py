from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
from app.models import db
from app.models.learning_wall import LearningWallPost, LearningWallReaction, LearningWallComment
from app.models.user import Learner
from app.models.course import Course
from app.utils.tagging import process_tags_and_notify, format_tags_filter
from app.services.learning_wall_service import (
    seed_sample_wall_posts_if_empty,
    check_and_generate_birthday_posts,
    toggle_post_reaction,
    clear_all_wall_posts
)

learning_wall_bp = Blueprint('learning_wall', __name__)

@learning_wall_bp.route('/')
def index():
    """
    Renders the automated news-bulletin Learning Wall feed.
    Accessible to both logged-in Learners and Admins.
    """
    # Require login (Admin or Learner)
    if not session.get('admin_logged_in') and not session.get('learner_id') and not session.get('learner_global_id'):
        flash("Please log in to view the Learning Wall feed.", "info")
        return redirect(url_for('auth.learner_login'))

    # 1. Seed initial milestone posts if empty & check today's birthdays
    seed_sample_wall_posts_if_empty()
    check_and_generate_birthday_posts()

    # 2. Query posts ordered newest first
    posts = LearningWallPost.query.order_by(LearningWallPost.created_at.desc()).all()
    all_learners = Learner.query.order_by(Learner.name).all()
    all_courses = Course.query.order_by(Course.name).all()

    # 3. Resolve user details (Learner or Admin)
    if session.get('admin_logged_in'):
        user_identifier = session.get('admin_username', 'admin')
        user_name = session.get('admin_username', 'L&D Admin')
    else:
        user_identifier = session.get('learner_global_id') or str(session.get('learner_id', 'learner'))
        user_name = session.get('learner_name', 'Learner')

    # 4. Map user's current reactions & summary counts per post
    posts_data = []
    for p in posts:
        rxns = p.reactions
        counts = {'like': 0, 'love': 0, 'celebrate': 0, 'clap': 0, 'fire': 0}
        user_reaction = None
        
        for r in rxns:
            counts[r.reaction_type] = counts.get(r.reaction_type, 0) + 1
            if r.user_identifier == user_identifier:
                user_reaction = r.reaction_type

        posts_data.append({
            'post': p,
            'counts': counts,
            'total_reactions': len(rxns),
            'user_reaction': user_reaction,
            'comments': p.comments
        })

    return render_template(
        'learning_wall/index.html',
        posts_data=posts_data,
        user_identifier=user_identifier,
        user_name=user_name,
        all_learners=all_learners,
        all_courses=all_courses
    )


@learning_wall_bp.route('/react', methods=['POST'])
def react():
    """
    AJAX endpoint for toggling reactions on a Learning Wall post.
    Body JSON or Form: { 'post_id': 1, 'reaction_type': 'like' / 'love' / 'celebrate' / 'clap' / 'fire' }
    """
    if request.is_json:
        data = request.get_json()
    else:
        data = request.form

    post_id = data.get('post_id')
    reaction_type = data.get('reaction_type', 'like').lower()

    valid_reactions = ['like', 'love', 'celebrate', 'clap', 'fire']
    if reaction_type not in valid_reactions:
        return jsonify({'success': False, 'message': 'Invalid reaction type.'}), 400

    user_identifier = session.get('learner_global_id') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    user_name = session.get('learner_name') or (session.get('admin_username') if session.get('admin_logged_in') else None)

    if not user_identifier:
        return jsonify({'success': False, 'message': 'Please log in to react to posts.'}), 401

    res = toggle_post_reaction(post_id, user_identifier, user_name, reaction_type)
    return jsonify(res)


@learning_wall_bp.route('/clear', methods=['POST', 'GET'])
def clear_wall():
    """
    Endpoint to clear all events from the Learning Wall.
    Admin restriction checked.
    """
    if not session.get('admin_logged_in'):
        flash("Only L&D Administrators can clear Learning Wall events.", "danger")
        return redirect(url_for('learning_wall.index'))

    clear_all_wall_posts()
    flash("All events have been removed from the Learning Wall.", "success")
    return redirect(url_for('learning_wall.index'))


@learning_wall_bp.route('/create_post', methods=['POST'])
def create_post():
    """Admin: Create a custom announcement post on the Learning Wall."""
    if not session.get('admin_logged_in'):
        flash("Only L&D Administrators can create posts.", "danger")
        return redirect(url_for('learning_wall.index'))

    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    if not title or not content:
        flash("Post title and content are required.", "danger")
        return redirect(url_for('learning_wall.index'))

    post = LearningWallPost(
        post_type='ADMIN_ANNOUNCEMENT',
        title=title,
        content=content,
        icon='fa-bullhorn',
        badge_color='bg-teal-subtle text-teal'
    )
    db.session.add(post)
    db.session.flush() # Generate post.id
    process_tags_and_notify(content, 'L&D Admin', content)
    db.session.commit()
    flash(f"Announcement '{title}' posted to the Learning Wall.", "success")
    return redirect(url_for('learning_wall.index'))


@learning_wall_bp.route('/delete/<int:post_id>', methods=['POST'])
def delete_post(post_id):
    """Delete a specific Learning Wall post (Admin or the original poster)."""
    post = LearningWallPost.query.get_or_404(post_id)

    is_admin = session.get('admin_logged_in')
    learner_id = session.get('learner_id')
    is_author = post.learner_id and learner_id and int(learner_id) == int(post.learner_id)

    if not (is_admin or is_author):
        flash("You are not authorized to delete this post.", "danger")
        return redirect(url_for('learning_wall.index'))

    db.session.delete(post)
    db.session.commit()
    flash("Learning Wall post deleted.", "success")
    return redirect(url_for('learning_wall.index'))


@learning_wall_bp.route('/comment', methods=['POST'])
def add_comment():
    """Add a comment to a Learning Wall post."""
    post_id = request.form.get('post_id')
    content = request.form.get('content', '').strip()
    
    user_identifier = session.get('learner_global_id') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    user_name = session.get('learner_name') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    
    if not user_identifier:
        return jsonify({'success': False, 'message': 'Please log in to comment.'}), 401
        
    if not post_id or not content:
        return jsonify({'success': False, 'message': 'Invalid comment content.'}), 400
        
    comment = LearningWallComment(
        post_id=post_id,
        user_identifier=user_identifier,
        user_name=user_name,
        content=content
    )
    db.session.add(comment)
    db.session.flush()
    process_tags_and_notify(content, user_name, content)
    
    # Award points & badge for social engagement
    learner_id = session.get('learner_id')
    if learner_id:
        from app.utils.gamification import award_points, award_badge
        award_points(learner_id, 5, "Commenting on Social Wall")
        award_badge(learner_id, "Social Bee 🐝", "fa-comments", "Posted a comment on the Learning Wall!")
        
    db.session.commit()
    
    return jsonify({
        'success': True,
        'comment': {
            'id': comment.id,
            'user_name': comment.user_name,
            'content': format_tags_filter(comment.content),
            'created_at': comment.created_at.strftime('%d-%b-%Y %H:%M')
        }
    })



@learning_wall_bp.route('/comment/delete/<int:comment_id>', methods=['POST'])
def delete_comment(comment_id):
    """Delete a comment from a Learning Wall post."""
    comment = LearningWallComment.query.get_or_404(comment_id)
    
    user_identifier = session.get('learner_global_id') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    is_admin = bool(session.get('admin_logged_in'))
    
    if not user_identifier:
        return jsonify({'success': False, 'message': 'Please log in.'}), 401
        
    if comment.user_identifier != user_identifier and not is_admin:
        return jsonify({'success': False, 'message': 'Unauthorized to delete this comment.'}), 403
        
    db.session.delete(comment)
    db.session.commit()
    return jsonify({'success': True})


@learning_wall_bp.route('/create_moment', methods=['POST'])
def create_moment():
    """Allows Learners or Admins to post a custom Learning Moment."""
    user_identifier = session.get('learner_global_id') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    user_name = session.get('learner_name') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    learner_id = session.get('learner_id')
    
    if not user_identifier:
        flash("Please log in to post on the Learning Wall.", "danger")
        return redirect(url_for('learning_wall.index'))
        
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    badge_color = request.form.get('badge_color', 'bg-teal-subtle text-teal')
    icon = request.form.get('icon', 'fa-lightbulb')
    
    if not title or not content:
        flash("Post title and content are required.", "danger")
        return redirect(url_for('learning_wall.index'))
        
    post = LearningWallPost(
        post_type='LEARNER_MOMENT',
        title=f"{user_name}: {title}" if not session.get('admin_logged_in') else title,
        content=content,
        learner_id=learner_id if not session.get('admin_logged_in') else None,
        icon=icon,
        badge_color=badge_color
    )
    db.session.add(post)
    db.session.flush()
    process_tags_and_notify(content, user_name, content)
    
    if learner_id:
        from app.utils.gamification import award_points
        award_points(learner_id, 10, "Sharing a learning moment")
        
    db.session.commit()
    
    flash("Successfully posted your learning moment!", "success")
    return redirect(url_for('learning_wall.index'))


@learning_wall_bp.route('/share_course', methods=['POST'])
def share_course():
    """Share a recommended course on the Learning Wall."""
    user_identifier = session.get('learner_global_id') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    user_name = session.get('learner_name') or (session.get('admin_username') if session.get('admin_logged_in') else None)
    learner_id = session.get('learner_id')
    
    if not user_identifier:
        flash("Please log in to share a course.", "danger")
        return redirect(url_for('learning_wall.index'))
        
    course_id = request.form.get('course_id')
    note = request.form.get('note', '').strip()
    
    if not course_id:
        flash("Course is required.", "danger")
        return redirect(url_for('learning_wall.index'))
        
    course = Course.query.get(course_id)
    if not course:
        flash("Course not found.", "danger")
        return redirect(url_for('learning_wall.index'))
        
    post = LearningWallPost(
        post_type='COURSE_RECOMMENDATION',
        title=f"{user_name} recommends: {course.name}",
        content=note if note else f"Check out this interesting course: {course.name}.",
        learner_id=learner_id if not session.get('admin_logged_in') else None,
        course_id=course.id,
        icon='fa-share-nodes',
        badge_color='bg-primary-subtle text-primary'
    )
    db.session.add(post)
    db.session.flush()
    process_tags_and_notify(post.content, user_name, post.content)
    
    if learner_id:
        from app.utils.gamification import award_points
        award_points(learner_id, 20, "Recommending a course")
        
    db.session.commit()
    
    flash(f"Recommended course '{course.name}' on the Learning Wall!", "success")
    return redirect(url_for('learning_wall.index'))

