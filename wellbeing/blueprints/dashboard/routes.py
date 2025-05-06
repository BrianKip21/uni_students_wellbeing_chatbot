from bson.objectid import ObjectId
from flask import render_template, session, redirect, url_for, flash, request, jsonify, Response
from datetime import datetime, timezone
import csv
import io
import json
from wellbeing.blueprints.dashboard import dashboard_bp
from wellbeing.utils.decorators import login_required
from wellbeing import mongo, logger
from wellbeing.models.user import find_user_by_id, update_user_settings

@dashboard_bp.route('/dashboard')
@login_required
def index():
    """Dashboard index page with user's overview."""
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Check if we should redirect based on default view
    requested_view = request.args.get('view')
    if not requested_view and settings.get('default_view') != 'dashboard':
        default_view = settings.get('default_view')
        if default_view == 'calendar':
            return redirect(url_for('tracking.index'))
        elif default_view == 'list':
            return redirect(url_for('tracking.list_view'))
    
    # If progress field doesn't exist, initialize it
    if 'progress' not in user:
        user['progress'] = {
            'meditation': 0,
            'exercise': 0
        }
        
        # Save this default structure to the database
        mongo.db.users.update_one(
            {'_id': user_id},
            {'$set': {'progress': user['progress']}}
        )
    
    # Fetch recent chats for the user
    recent_chats = list(mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1).limit(5))
    
    # Fetch recommended resources
    recommended_resources = list(mongo.db.resources.find().limit(2))
    
    # Get latest mood data
    latest_mood = mongo.db.moods.find_one({"user_id": str(user_id)}, sort=[("timestamp", -1)])
    
    return render_template('dashboard.html',
                         user=user,
                         settings=settings,
                         recent_chats=recent_chats,
                         resources=recommended_resources,
                         latest_mood=latest_mood)

@dashboard_bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    """User profile page."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    settings = user.get('settings', {})
    
    # Handle form submission (for profile updates)
    if request.method == 'POST':
        try:
            # Get form data
            first_name = request.form.get('first_name', '').strip()
            last_name = request.form.get('last_name', '').strip()
            email = request.form.get('email', '').strip()
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')
            
            # Basic validation
            errors = []
            
            # Names cannot be changed
            if first_name and first_name != user.get('first_name', ''):
                errors.append('First name cannot be changed.')
                
            if last_name and last_name != user.get('last_name', ''):
                errors.append('Last name cannot be changed.')
            
            # Email cannot be changed
            if email and email != user.get('email', ''):
                errors.append('Email cannot be changed.')
            
            # Password validation - always require current password verification
            if new_password or confirm_password:
                from werkzeug.security import check_password_hash, generate_password_hash
                
                # First check if current password was provided
                if not current_password:
                    errors.append('Current password is required to change your password.')
                else:
                    # Verify current password is correct before allowing password change
                    if not check_password_hash(user.get('password', ''), current_password):
                        errors.append('Current password is incorrect.')
                    else:
                        # Current password is correct, now validate the new password
                        if not new_password:
                            errors.append('New password is required.')
                        elif len(new_password) < 8:
                            errors.append('New password must be at least 8 characters.')
                        
                        if new_password != confirm_password:
                            errors.append('New passwords do not match.')
            
            # If there are validation errors, flash them and redirect
            if errors:
                for error in errors:
                    flash(error, 'error')
                return redirect(url_for('dashboard.profile'))
            
            # Prepare update data
            update_data = {}
            
            # Password change (only if current password is provided and verified)
            if current_password and new_password and check_password_hash(user.get('password', ''), current_password):
                update_data['password'] = generate_password_hash(new_password)
            
            # Update user data if there are changes
            if update_data:
                mongo.db.users.update_one(
                    {'_id': user_id},
                    {'$set': update_data}
                )
                flash('Password updated successfully!', 'success')
                
                # Refresh user data after update
                user = find_user_by_id(user_id)
            else:
                flash('No changes detected.', 'info')
                
        except Exception as e:
            logger.error(f"Profile update error: {e}")
            flash('An error occurred while updating your profile.', 'error')
    
    # Create options for statistics or additional info
    activity_stats = {
        'login_count': user.get('login_count', 0),
        'last_login': user.get('last_login', 'Never'),
        'registration_date': user.get('created_at', 'Unknown')
    }
    
    # Get user's recent activity (mood entries and other tracked actions)
    recent_activity = list(mongo.db.moods.find(
        {"user_id": str(user_id)}
    ).sort("timestamp", -1).limit(5))
    
    return render_template('profile.html', 
                          user=user, 
                          stats=activity_stats,
                          activity=recent_activity,
                          settings=settings)

@dashboard_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    """User settings page."""
    # Fetch user data
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get or initialize user settings
    user_settings = user.get('settings', {})
    
    # Default settings if none exist
    if not user_settings:
        user_settings = {
            'text_size': 'md',
            'contrast': 'normal',
            'theme_mode': 'light',
            'widgets': ['mood_tracker', 'quick_actions', 'resources', 'progress'],
            'default_view': 'dashboard',
            'reminder_time': '09:00',
            'checkin_frequency': 'weekdays'
        }
        
        # Update user with default settings
        update_user_settings(user_id, user_settings)
    
    # Handle form submissions
    if request.method == 'POST':
        form_type = request.form.get('form_type')
        
        try:
            if form_type == 'accessibility':
                # Update accessibility settings
                user_settings['text_size'] = request.form.get('text_size')
                user_settings['contrast'] = request.form.get('contrast')
                flash('Accessibility settings updated successfully!', 'success')
            
            elif form_type == 'theme':
                # Update theme settings
                user_settings['theme_mode'] = request.form.get('theme_mode')
                flash('Theme settings updated successfully!', 'success')
            
            elif form_type == 'dashboard':
                # Update dashboard settings
                widgets = request.form.getlist('widgets')
                if not widgets:
                    # Ensure at least one widget is selected
                    widgets = ['mood_tracker']
                
                user_settings['widgets'] = widgets
                user_settings['default_view'] = request.form.get('default_view')
                flash('Dashboard settings updated successfully!', 'success')
            
            elif form_type == 'reminders':
                # Update reminder settings
                user_settings['reminder_time'] = request.form.get('reminder_time')
                user_settings['checkin_frequency'] = request.form.get('checkin_frequency')
                flash('Reminder settings updated successfully!', 'success')
            
            # Save updated settings to database
            update_user_settings(user_id, user_settings)
            
        except Exception as e:
            logger.error(f"Settings update error: {e}")
            flash('An error occurred while updating settings.', 'error')
    
    return render_template('settings.html', user=user, settings=user_settings)

@dashboard_bp.route('/student_resources')
@login_required
def resources():
    """Student resources page."""
    # Get user from database
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found. Please log in again.', 'error')
        return redirect(url_for('auth.login'))
    
    # Get resources
    resources = list(mongo.db.resources.find())
    
    # Get user settings
    settings = user.get('settings', {})
    
    return render_template('student_resources.html', resources=resources, settings=settings, user=user)

@dashboard_bp.route('/download_data')
@login_required
def download_data():
    """Download user data in CSV format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Create CSV file in memory
        memory_file = io.StringIO()
        writer = csv.writer(memory_file)
        
        # Write user profile data
        writer.writerow(['Profile Information'])
        writer.writerow(['First Name', 'Last Name', 'Email', 'Student ID', 'Role', 'Created At'])
        writer.writerow([
            user.get('first_name', ''),
            user.get('last_name', ''),
            user.get('email', ''),
            user.get('student_id', ''),
            user.get('role', ''),
            user.get('created_at', datetime.now()).strftime('%Y-%m-%d %H:%M:%S')
        ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write mood data
        writer.writerow(['Mood Tracking History'])
        writer.writerow(['Date', 'Mood', 'Notes'])
        
        moods = mongo.db.moods.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for mood in moods:
            writer.writerow([
                mood.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                mood.get('mood', ''),
                mood.get('context', '')
            ])
        
        writer.writerow([])  # Empty row as separator
        
        # Write chat history
        writer.writerow(['Recent Conversations'])
        writer.writerow(['Date', 'Message'])
        
        chats = mongo.db.chats.find({"user_id": str(user_id)}).sort("timestamp", -1)
        for chat in chats:
            writer.writerow([
                chat.get('timestamp', datetime.now()).strftime('%Y-%m-%d %H:%M:%S'),
                chat.get('message', '')
            ])
        
        # Prepare response
        memory_file.seek(0)
        return Response(
            memory_file.getvalue(),
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.csv"}
        )
    
    except Exception as e:
        logger.error(f"Data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))

@dashboard_bp.route('/download_data_json')
@login_required
def download_data_json():
    """Download user data in JSON format."""
    user_id = ObjectId(session['user'])
    user = find_user_by_id(user_id)
    
    if not user:
        flash('User not found.', 'error')
        return redirect(url_for('dashboard.index'))
    
    try:
        # Helper function to handle ObjectId and datetime serialization
        def json_serial(obj):
            if isinstance(obj, ObjectId):
                return str(obj)
            if isinstance(obj, datetime):
                return obj.strftime('%Y-%m-%d %H:%M:%S')
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # Create a copy of user data without password
        user_data = {k: v for k, v in user.items() if k != 'password'}
        
        # Get mood data
        moods = list(mongo.db.moods.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Get chat data
        chats = list(mongo.db.chats.find({"user_id": str(user_id)}, 
                                        {'_id': 0}))  # Exclude _id field
        
        # Combine all data
        export_data = {
            'profile': user_data,
            'moods': moods,
            'chats': chats
        }
        
        # Convert to JSON
        json_data = json.dumps(export_data, default=json_serial, indent=4)
        
        # Prepare response
        return Response(
            json_data,
            mimetype="application/json",
            headers={"Content-disposition": f"attachment; filename=wellbeing_data_{datetime.now().strftime('%Y%m%d')}.json"}
        )
    
    except Exception as e:
        logger.error(f"JSON data download error: {e}")
        flash('An error occurred while generating your data download.', 'error')
        return redirect(url_for('dashboard.settings'))