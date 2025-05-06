from datetime import datetime, timezone, time
from bson.objectid import ObjectId
from flask import render_template, redirect, url_for, request, flash, jsonify, session
from wellbeing.blueprints.tracking import tracking_bp
from wellbeing.utils.decorators import login_required, csrf_protected
from wellbeing import mongo, logger
from wellbeing.models.user import find_user_by_id
from wellbeing.models.mood import track_mood, get_mood_history
from wellbeing.models.journal import create_journal_entry, get_journal_entries, get_journal_entry
from wellbeing.models.goal import create_goal, get_goals, update_goal_progress, delete_goal

@tracking_bp.route('/tracking')
@login_required
def index():
    """Main tracking page with mood, journal, and goals."""
    try:
        # Fetch user data
        user_id = ObjectId(session['user'])
        user = find_user_by_id(user_id)
        
        if not user:
            flash('User not found. Please log in again.', 'error')
            return redirect(url_for('auth.login'))
        
        settings = user.get('settings', {})
        
        # Initialize progress if it doesn't exist
        if 'progress' not in user:
            user['progress'] = {
                'meditation': 0,
                'exercise': 0,
                'sleep': 0,
                'water': 0
            }
            
            # Save the default structure to the database
            mongo.db.users.update_one(
                {'_id': user_id},
                {'$set': {'progress': user['progress']}}
            )
        
        # Get recent mood entries
        mood_history = get_mood_history(str(user_id))
        
        # Get journal entries
        journal_entries = get_journal_entries(str(user_id))
        
        # Get user goals
        goals = get_goals(str(user_id))
        
        # Get today's date for journal entry default
        today_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        # Render the tracking template with all the necessary data
        return render_template(
            'tracking.html',
            user=user,
            mood_history=mood_history,
            journal_entries=journal_entries,
            goals=goals,
            today_date=today_date,
            settings=settings
        )
        
    except Exception as e:
        logger.error(f"Error in tracking route: {e}")
        flash('An error occurred. Please try again.', 'error')
        return redirect(url_for('dashboard.index'))

@tracking_bp.route('/track_mood', methods=['POST'])
@login_required
def track_mood_route():
    """Record a new mood entry."""
    try:
        user_id = str(ObjectId(session['user']))
        
        # Get form data
        mood = request.form.get('mood')
        context = request.form.get('context', '')
        
        # Validate mood
        if not mood:
            flash('Please select a mood.', 'error')
            return redirect(url_for('tracking.index') + '#mood')
        
        # Track the mood
        result = track_mood(user_id, mood, context)
        
        # Flash appropriate message
        if result == "created":
            flash('Mood tracked successfully!', 'success')
        else:
            flash('Mood updated for today!', 'success')
        
        # Redirect back to tracking page with mood tab active
        return redirect(url_for('tracking.index') + '#mood')
        
    except Exception as e:
        logger.error(f"Error tracking mood: {e}")
        flash('There was an error tracking your mood. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#mood')

@tracking_bp.route('/save_journal', methods=['POST'])
@login_required
def save_journal():
    """Save a new journal entry."""
    try:
        user_id = str(ObjectId(session['user']))
        
        # Get form data
        date = request.form.get('date')
        title = request.form.get('title', '')[:100]  # Limit title length
        content = request.form.get('content', '')[:5000]  # Limit content length
        mood = request.form.get('mood')
        gratitude_items = request.form.getlist('gratitude[]')
        
        # Validate required fields
        if not title:
            flash('Title is required.', 'error')
            return redirect(url_for('tracking.index') + '#journal')
        
        if not date:
            date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
        
        # Filter out empty gratitude items and limit length
        gratitude_items = [item[:200] for item in gratitude_items if item.strip()]
        
        # Create the journal entry
        entry_id = create_journal_entry(user_id, title, content, date, mood, gratitude_items)
        
        flash('Journal entry saved successfully!', 'success')
        return redirect(url_for('tracking.index') + '#journal')
        
    except Exception as e:
        logger.error(f"Error saving journal entry: {e}")
        flash('There was an error saving your journal entry. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#journal')

@tracking_bp.route('/view_journal/<entry_id>')
@login_required
def view_journal(entry_id):
    """View a specific journal entry."""
    try:
        user_id = str(ObjectId(session['user']))
        
        # Get the journal entry
        entry = get_journal_entry(entry_id, user_id)
        
        if not entry:
            flash('Journal entry not found.', 'error')
            return redirect(url_for('tracking.index'))
        
        user = find_user_by_id(ObjectId(user_id))
        
        return render_template('view_journal.html', entry=entry, user=user)
        
    except Exception as e:
        logger.error(f"Error viewing journal entry: {e}")
        flash('There was an error viewing the journal entry. Please try again.', 'error')
        return redirect(url_for('tracking.index'))

@tracking_bp.route('/add_goal', methods=['POST'])
@login_required
def add_goal():
    """Add a new goal."""
    try:
        user_id = str(ObjectId(session['user']))
        
        # Get form data
        goal_type = request.form.get('type')
        if goal_type == 'custom':
            goal_type = request.form.get('custom_type', 'custom')[:50]  # Limit length
            
        description = request.form.get('description', '')[:500]  # Limit description length
        
        # Safely convert target to int
        try:
            target = int(request.form.get('target', 1))
            if target <= 0:
                target = 1  # Ensure target is positive
        except ValueError:
            target = 1  # Default to 1 if conversion fails
            
        unit = request.form.get('unit')
        if unit == 'custom':
            unit = request.form.get('custom_unit', 'units')[:20]  # Limit length
            
        frequency = request.form.get('frequency')
        
        # Validate required fields
        if not description:
            flash('Goal description is required.', 'error')
            return redirect(url_for('tracking.index') + '#goals')
        
        # Create the goal
        goal_id = create_goal(user_id, goal_type, description, target, unit, frequency)
        
        flash('Goal added successfully!', 'success')
        return redirect(url_for('tracking.index') + '#goals')
        
    except Exception as e:
        logger.error(f"Error adding goal: {e}")
        flash('There was an error adding your goal. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#goals')

@tracking_bp.route('/update_goal_progress', methods=['POST'])
@login_required
@csrf_protected
def update_goal_progress_route():
    """Update progress for a goal."""
    try:
        user_id = str(ObjectId(session['user']))
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
        
        goal_id = data.get('goal_id')
        if not goal_id:
            return jsonify({'success': False, 'error': 'No goal ID provided'})
        
        # Safely convert increment to int
        try:
            increment = int(data.get('increment', 1))
        except ValueError:
            increment = 1  # Default to 1 if conversion fails
        
        # Update the goal progress
        success, result = update_goal_progress(user_id, goal_id, increment)
        
        if not success:
            return jsonify({'success': False, 'error': result})
        
        return jsonify({
            'success': True,
            'new_progress': result['new_progress'],
            'goal_completed': result['goal_completed']
        })
        
    except Exception as e:
        logger.error(f"Error updating goal progress: {e}")
        return jsonify({'success': False, 'error': str(e)})

@tracking_bp.route('/delete_goal', methods=['POST'])
@login_required
@csrf_protected
def delete_goal_route():
    """Delete a goal."""
    try:
        user_id = str(ObjectId(session['user']))
        data = request.get_json()
        
        if not data:
            return jsonify({'success': False, 'error': 'No data provided'})
        
        goal_id = data.get('goal_id')
        if not goal_id:
            return jsonify({'success': False, 'error': 'No goal ID provided'})
        
        # Delete the goal
        success = delete_goal(user_id, goal_id)
        
        if not success:
            return jsonify({'success': False, 'error': 'Goal not found or not deleted'})
        
        return jsonify({'success': True})
        
    except Exception as e:
        logger.error(f"Error deleting goal: {e}")
        return jsonify({'success': False, 'error': str(e)})

@tracking_bp.route('/update_progress', methods=['POST'])
@login_required
def update_progress():
    """Update progress for predefined progress types."""
    try:
        user_id = ObjectId(session['user'])
        
        # Get form data
        progress_type = request.form.get('type')
        
        # Validate progress type
        valid_progress_types = ['meditation', 'exercise', 'sleep', 'water']
        if progress_type not in valid_progress_types:
            flash('Invalid progress type.', 'error')
            return redirect(url_for('tracking.index') + '#goals')
        
        # Safely convert progress value to int
        try:
            progress_value = int(request.form.get('value', 0))
            if progress_value < 0:
                progress_value = 0  # Ensure non-negative value
            if progress_value > 100:
                progress_value = 100  # Ensure maximum of 100
        except ValueError:
            progress_value = 0  # Default to 0 if conversion fails
        
        # Update user progress
        update_field = f'progress.{progress_type}'
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {update_field: progress_value}}
        )
        
        flash(f'{progress_type.capitalize()} progress updated!', 'success')
        return redirect(url_for('tracking.index') + '#goals')
        
    except Exception as e:
        logger.error(f"Error updating progress: {e}")
        flash('There was an error updating your progress. Please try again.', 'error')
        return redirect(url_for('tracking.index') + '#goals')

@tracking_bp.route('/list_view')
@login_required
def list_view():
    """Alternative list view of tracking data."""
    user_id = str(ObjectId(session['user']))
    user = find_user_by_id(ObjectId(user_id))
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get settings
    settings = user.get('settings', {})
    
    # Get all mood entries
    all_moods = list(mongo.db.moods.find(
        {"user_id": user_id}
    ).sort("timestamp", -1))
    
    # Get all journal entries
    all_journals = list(mongo.db.journals.find(
        {"user_id": user_id}
    ).sort("date", -1))
    
    # Get all goals
    all_goals = list(mongo.db.goals.find(
        {"user_id": user_id}
    ).sort("created_at", -1))
    
    return render_template(
        'tracking_list.html',
        user=user,
        moods=all_moods,
        journals=all_journals,
        goals=all_goals,
        settings=settings
    )